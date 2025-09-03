from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Path, Query, Request, Response
from starlette import status

from sqlalchemy import asc, desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import schemas
from .auth import User, get_current_user
from .db import (
    Board,
    BoardMembership,
    Card,
    ColumnModel,
    SessionLocal,
    init_db,
    now_utc,
)
from .utils import etag_from, lexo_midpoint, new_uuid, sha256_hex


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


app = FastAPI(title="TODO Service", version="1.0.0")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/v1/health", response_model=schemas.Health)
def health():
    return schemas.Health(status="ok")


@app.get("/v1/version", response_model=schemas.Version)
def version():
    return schemas.Version(version=app.version)


def get_role(db: Session, board: Board, user: User) -> str | None:
    if board.owner == user.id:
        return "admin"
    m = db.execute(
        select(BoardMembership).where(
            BoardMembership.board_id == board.id, BoardMembership.user_id == user.id, BoardMembership.status == "active"
        )
    ).scalar_one_or_none()
    return m.role if m else None


def ensure_role(required: set[str], role: Optional[str]):
    if not role or role not in required:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")


def board_to_out(db: Session, board: Board, me: User) -> schemas.BoardOut:
    role = get_role(db, board, me) or "reader"
    members_count = db.query(BoardMembership).filter(
        BoardMembership.board_id == board.id, BoardMembership.status == "active"
    ).count()
    return schemas.BoardOut(
        id=board.id,
        name=board.name,
        description=board.description,
        owner=board.owner,
        createdAt=board.created_at,
        updatedAt=board.updated_at,
        myRole=role,
        membersCount=members_count,
    )


# Boards
@app.post("/v1/boards", response_model=schemas.BoardOut, status_code=status.HTTP_201_CREATED)
def create_board(
    payload: schemas.BoardIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name must not be empty")
    b = Board(id=new_uuid(), name=name, description=payload.description, owner=user.id)
    db.add(b)
    # owner is implicit admin; add active membership for owner as admin for count/queries
    db.add(
        BoardMembership(
            board_id=b.id,
            user_id=user.id,
            role="admin",
            status="active",
            invited_by=None,
            display_name=user.id,
            avatar_url=None,
        )
    )
    db.commit()
    db.refresh(b)
    return board_to_out(db, b, user)


@app.get("/v1/boards", response_model=schemas.BoardsPage)
def list_boards(
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[str] = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Simple pagination by created_at,id after owner/membership filter
    q = (
        db.query(Board)
        .join(BoardMembership, Board.id == BoardMembership.board_id)
        .filter(BoardMembership.user_id == user.id, BoardMembership.status == "active")
        .order_by(desc(Board.created_at), desc(Board.id))
    )
    if cursor:
        # cursor format: createdAtIso|boardId
        try:
            created_at_str, bid = cursor.split("|", 1)
            created_at = datetime.fromisoformat(created_at_str)
            q = q.filter((Board.created_at < created_at) | ((Board.created_at == created_at) & (Board.id < bid)))
        except Exception:
            raise HTTPException(status_code=400, detail="invalid cursor")
    items = q.limit(limit + 1).all()
    has_next = len(items) > limit
    items = items[:limit]
    next_cursor = (
        f"{items[-1].created_at.isoformat()}|{items[-1].id}" if has_next and items else None
    )
    return schemas.BoardsPage(boards=[board_to_out(db, b, user) for b in items], nextCursor=next_cursor)


def load_board_or_404(db: Session, board_id: str) -> Board:
    b = db.get(Board, board_id)
    if not b:
        raise HTTPException(status_code=404, detail="board not found")
    return b


@app.get("/v1/boards/{board_id}", response_model=schemas.BoardView)
def get_board(
    board_id: str = Path(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    b = load_board_or_404(db, board_id)
    role = get_role(db, b, user)
    if not role:
        raise HTTPException(status_code=403, detail="forbidden")
    cols = (
        db.query(ColumnModel)
        .filter(ColumnModel.board_id == b.id)
        .order_by(asc(ColumnModel.sort_key), asc(ColumnModel.created_at), asc(ColumnModel.id))
        .all()
    )
    cards = (
        db.query(Card)
        .filter(Card.board_id == b.id)
        .order_by(asc(Card.column_id), asc(Card.sort_key), asc(Card.created_at), asc(Card.id))
        .all()
    )
    return schemas.BoardView(
        board=board_to_out(db, b, user),
        columns=[
            schemas.ColumnOut(
                id=c.id,
                boardId=c.board_id,
                name=c.name,
                sortKey=c.sort_key,
                createdAt=c.created_at,
                updatedAt=c.updated_at,
            )
            for c in cols
        ],
        cards=[
            schemas.CardOut(
                id=cd.id,
                boardId=cd.board_id,
                columnId=cd.column_id,
                title=cd.title,
                description=cd.description,
                sortKey=cd.sort_key,
                createdAt=cd.created_at,
                updatedAt=cd.updated_at,
                version=cd.version,
            )
            for cd in cards
        ],
    )


@app.patch("/v1/boards/{board_id}", response_model=schemas.BoardOut)
def update_board(
    board_id: str,
    payload: schemas.BoardIn,
    if_match: Optional[str] = Header(default=None, alias="If-Match"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    b = load_board_or_404(db, board_id)
    role = get_role(db, b, user)
    ensure_role({"admin", "writer"}, role)
    current_etag = etag_from(b.updated_at.isoformat())
    if if_match and if_match != current_etag:
        raise HTTPException(status_code=412, detail="etag mismatch")
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name must not be empty")
    b.name = name
    b.description = payload.description
    b.updated_at = now_utc()
    db.commit()
    db.refresh(b)
    return board_to_out(db, b, user)


@app.delete("/v1/boards/{board_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_board(
    board_id: str,
    if_match: Optional[str] = Header(default=None, alias="If-Match"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    b = load_board_or_404(db, board_id)
    role = get_role(db, b, user)
    ensure_role({"admin"}, role)
    current_etag = etag_from(b.updated_at.isoformat())
    if if_match and if_match != current_etag:
        raise HTTPException(status_code=412, detail="etag mismatch")
    db.delete(b)
    db.commit()
    return Response(status_code=204)


# Columns
def compute_column_sort_key(db: Session, board_id: str, before_id: Optional[str], after_id: Optional[str]) -> str:
    left = None
    right = None
    if before_id:
        before = db.get(ColumnModel, before_id)
        if not before or before.board_id != board_id:
            raise HTTPException(status_code=422, detail="invalid beforeColumnId")
        right = before.sort_key
    if after_id:
        after = db.get(ColumnModel, after_id)
        if not after or after.board_id != board_id:
            raise HTTPException(status_code=422, detail="invalid afterColumnId")
        left = after.sort_key
    return lexo_midpoint(left, right)


@app.post("/v1/boards/{board_id}/columns", response_model=schemas.ColumnOut, status_code=status.HTTP_201_CREATED)
def create_column(
    board_id: str,
    payload: schemas.ColumnIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    b = load_board_or_404(db, board_id)
    role = get_role(db, b, user)
    ensure_role({"admin", "writer"}, role)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name must not be empty")
    sort_key = compute_column_sort_key(db, b.id, payload.beforeColumnId, payload.afterColumnId)
    c = ColumnModel(id=new_uuid(), board_id=b.id, name=name, sort_key=sort_key)
    db.add(c)
    db.commit()
    db.refresh(c)
    return schemas.ColumnOut(
        id=c.id,
        boardId=c.board_id,
        name=c.name,
        sortKey=c.sort_key,
        createdAt=c.created_at,
        updatedAt=c.updated_at,
    )


@app.patch("/v1/boards/{board_id}/columns/{column_id}", response_model=schemas.ColumnOut)
def rename_column(
    board_id: str,
    column_id: str,
    payload: schemas.ColumnPatch,
    if_match: Optional[str] = Header(default=None, alias="If-Match"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    b = load_board_or_404(db, board_id)
    role = get_role(db, b, user)
    ensure_role({"admin", "writer"}, role)
    c = db.get(ColumnModel, column_id)
    if not c or c.board_id != b.id:
        raise HTTPException(status_code=404, detail="column not found")
    current_etag = etag_from(c.updated_at.isoformat())
    if if_match and if_match != current_etag:
        raise HTTPException(status_code=412, detail="etag mismatch")
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name must not be empty")
    c.name = name
    c.updated_at = now_utc()
    db.commit()
    db.refresh(c)
    return schemas.ColumnOut(
        id=c.id, boardId=c.board_id, name=c.name, sortKey=c.sort_key, createdAt=c.created_at, updatedAt=c.updated_at
    )


@app.post("/v1/boards/{board_id}/columns/{column_id}:move", response_model=schemas.ColumnOut)
def move_column(
    board_id: str,
    column_id: str,
    payload: schemas.ColumnIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    b = load_board_or_404(db, board_id)
    role = get_role(db, b, user)
    ensure_role({"admin", "writer"}, role)
    c = db.get(ColumnModel, column_id)
    if not c or c.board_id != b.id:
        raise HTTPException(status_code=404, detail="column not found")
    new_key = compute_column_sort_key(db, b.id, payload.beforeColumnId, payload.afterColumnId)
    c.sort_key = new_key
    c.updated_at = now_utc()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # retry with slightly deeper midpoint using current neighbors
        new_key = new_key + "m"
        c.sort_key = new_key
        db.commit()
    db.refresh(c)
    return schemas.ColumnOut(
        id=c.id, boardId=c.board_id, name=c.name, sortKey=c.sort_key, createdAt=c.created_at, updatedAt=c.updated_at
    )


@app.delete("/v1/boards/{board_id}/columns/{column_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_column(
    board_id: str,
    column_id: str,
    if_match: Optional[str] = Header(default=None, alias="If-Match"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    b = load_board_or_404(db, board_id)
    role = get_role(db, b, user)
    ensure_role({"admin", "writer"}, role)
    c = db.get(ColumnModel, column_id)
    if not c or c.board_id != b.id:
        raise HTTPException(status_code=404, detail="column not found")
    current_etag = etag_from(c.updated_at.isoformat())
    if if_match and if_match != current_etag:
        raise HTTPException(status_code=412, detail="etag mismatch")
    db.delete(c)
    db.commit()
    return Response(status_code=204)


# Cards
def get_card_anchors(db: Session, board_id: str, to_column_id: str, before_id: Optional[str], after_id: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    left = None
    right = None
    if before_id:
        before = db.get(Card, before_id)
        if not before or before.board_id != board_id or before.column_id != to_column_id:
            raise HTTPException(status_code=422, detail="invalid beforeCardId")
        right = before.sort_key
    if after_id:
        after = db.get(Card, after_id)
        if not after or after.board_id != board_id or after.column_id != to_column_id:
            raise HTTPException(status_code=422, detail="invalid afterCardId")
        left = after.sort_key
    return left, right


@app.post("/v1/boards/{board_id}/columns/{column_id}/cards", response_model=schemas.CardOut, status_code=status.HTTP_201_CREATED)
def create_card(
    board_id: str,
    column_id: str,
    payload: schemas.CardIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    b = load_board_or_404(db, board_id)
    role = get_role(db, b, user)
    ensure_role({"admin", "writer"}, role)
    col = db.get(ColumnModel, column_id)
    if not col or col.board_id != b.id:
        raise HTTPException(status_code=404, detail="column not found")
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=422, detail="title must not be empty")
    left, right = get_card_anchors(db, b.id, col.id, payload.beforeCardId, payload.afterCardId)
    sort_key = lexo_midpoint(left, right)
    cd = Card(
        id=new_uuid(),
        board_id=b.id,
        column_id=col.id,
        title=title,
        description=payload.description,
        sort_key=sort_key,
        version=0,
    )
    db.add(cd)
    db.commit()
    db.refresh(cd)
    return schemas.CardOut(
        id=cd.id,
        boardId=cd.board_id,
        columnId=cd.column_id,
        title=cd.title,
        description=cd.description,
        sortKey=cd.sort_key,
        createdAt=cd.created_at,
        updatedAt=cd.updated_at,
        version=cd.version,
    )


@app.patch("/v1/boards/{board_id}/columns/{column_id}/cards/{card_id}", response_model=schemas.CardOut)
def update_card(
    board_id: str,
    column_id: str,
    card_id: str,
    payload: schemas.CardPatch,
    if_match: Optional[str] = Header(default=None, alias="If-Match"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    b = load_board_or_404(db, board_id)
    role = get_role(db, b, user)
    ensure_role({"admin", "writer"}, role)
    cd = db.get(Card, card_id)
    if not cd or cd.board_id != b.id or cd.column_id != column_id:
        raise HTTPException(status_code=404, detail="card not found")
    if if_match:
        # If-Match accepts version as integer in quotes or hashed updated_at; here we accept version string
        expected = if_match.strip('"')
        if expected != str(cd.version):
            raise HTTPException(status_code=412, detail="version mismatch")
    if payload.title is not None:
        title = payload.title.strip()
        if not title:
            raise HTTPException(status_code=422, detail="title must not be empty")
        cd.title = title
    if payload.description is not None:
        cd.description = payload.description
    cd.version += 1
    db.commit()
    db.refresh(cd)
    return schemas.CardOut(
        id=cd.id,
        boardId=cd.board_id,
        columnId=cd.column_id,
        title=cd.title,
        description=cd.description,
        sortKey=cd.sort_key,
        createdAt=cd.created_at,
        updatedAt=cd.updated_at,
        version=cd.version,
    )


@app.post("/v1/boards/{board_id}/cards/{card_id}:move", response_model=schemas.CardOut)
def move_card(
    board_id: str,
    card_id: str,
    payload: schemas.CardMove,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    b = load_board_or_404(db, board_id)
    role = get_role(db, b, user)
    ensure_role({"admin", "writer"}, role)
    cd = db.get(Card, card_id)
    if not cd or cd.board_id != b.id:
        raise HTTPException(status_code=404, detail="card not found")
    to_column_id = payload.toColumnId or cd.column_id
    to_col = db.get(ColumnModel, to_column_id)
    if not to_col or to_col.board_id != b.id:
        raise HTTPException(status_code=409, detail="invalid_move")
    if payload.expectedVersion is not None and payload.expectedVersion != cd.version:
        raise HTTPException(status_code=412, detail="version mismatch")
    left, right = get_card_anchors(db, b.id, to_column_id, payload.beforeCardId, payload.afterCardId)
    new_key = lexo_midpoint(left, right)
    cd.column_id = to_column_id
    cd.sort_key = new_key
    cd.version += 1
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # refine key
        cd.sort_key = new_key + "m"
        cd.version += 1
        db.commit()
    db.refresh(cd)
    return schemas.CardOut(
        id=cd.id,
        boardId=cd.board_id,
        columnId=cd.column_id,
        title=cd.title,
        description=cd.description,
        sortKey=cd.sort_key,
        createdAt=cd.created_at,
        updatedAt=cd.updated_at,
        version=cd.version,
    )


@app.delete("/v1/boards/{board_id}/columns/{column_id}/cards/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_card(
    board_id: str,
    column_id: str,
    card_id: str,
    if_match: Optional[str] = Header(default=None, alias="If-Match"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    b = load_board_or_404(db, board_id)
    role = get_role(db, b, user)
    ensure_role({"admin", "writer"}, role)
    cd = db.get(Card, card_id)
    if not cd or cd.board_id != b.id or cd.column_id != column_id:
        raise HTTPException(status_code=404, detail="card not found")
    if if_match:
        expected = if_match.strip('"')
        if expected != str(cd.version):
            raise HTTPException(status_code=412, detail="version mismatch")
    db.delete(cd)
    db.commit()
    return Response(status_code=204)


# Members (minimal implementation)
@app.get("/v1/boards/{board_id}/members", response_model=list[schemas.MemberOut])
def list_members(
    board_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    b = load_board_or_404(db, board_id)
    role = get_role(db, b, user)
    if not role:
        raise HTTPException(status_code=403, detail="forbidden")
    rows = db.query(BoardMembership).filter(BoardMembership.board_id == b.id, BoardMembership.status == "active").all()
    out = []
    for r in rows:
        out.append(
            schemas.MemberOut(
                boardId=r.board_id,
                userId=r.user_id,
                role=r.role,
                status=r.status,
                invitedBy=r.invited_by,
                createdAt=r.created_at,
                updatedAt=r.updated_at,
                user=schemas.UserSummary(id=r.user_id, displayName=r.display_name or r.user_id, avatarUrl=r.avatar_url),
            )
        )
    return out


@app.post(
    "/v1/boards/{board_id}/members",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
)
def invite_member(
    board_id: str,
    payload: schemas.MemberIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    b = load_board_or_404(db, board_id)
    role = get_role(db, b, user)
    ensure_role({"admin"}, role)
    if not payload.role or payload.role not in {"admin", "writer", "reader"}:
        raise HTTPException(status_code=422, detail="invalid role")
    target_user_id = payload.userId
    token = None
    if target_user_id:
        # direct add as pending then active for simplicity
        m = BoardMembership(
            board_id=b.id,
            user_id=target_user_id,
            role=payload.role,
            status="active",
            invited_by=user.id,
            display_name=target_user_id,
            avatar_url=None,
        )
        db.add(m)
        db.commit()
        return {"membership": {
            "boardId": m.board_id, "userId": m.user_id, "role": m.role, "status": m.status,
            "invitedBy": m.invited_by, "createdAt": m.created_at, "updatedAt": m.updated_at,
            "user": {"id": m.user_id, "displayName": m.display_name or m.user_id, "avatarUrl": m.avatar_url}
        }, "invitation": None}
    else:
        # email invite; return token once
        from .db import Invitation

        inv_id = new_uuid()
        token = new_uuid()
        inv = Invitation(
            id=inv_id,
            board_id=b.id,
            email=payload.email,
            role=payload.role,
            status="pending",
            token_hash=sha256_hex(token),
        )
        db.add(inv)
        db.commit()
        return {
            "membership": None,
            "invitation": {
                "id": inv.id,
                "boardId": inv.board_id,
                "email": inv.email,
                "role": inv.role,
                "status": inv.status,
                "token": token,
            },
        }


@app.post("/v1/invitations/accept", response_model=dict)
def accept_invitation(
    payload: schemas.InvitationAccept,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from .db import Invitation

    token_hash = sha256_hex(payload.token)
    inv = db.query(Invitation).filter(Invitation.token_hash == token_hash, Invitation.status == "pending").first()
    if not inv:
        raise HTTPException(status_code=404, detail="invalid or expired token")
    # add membership as reader by default to demonstrate
    m = BoardMembership(
        board_id=inv.board_id,
        user_id=user.id,
        role="reader",
        status="active",
        invited_by=None,
        display_name=user.id,
        avatar_url=None,
    )
    db.add(m)
    inv.status = "accepted"
    db.commit()
    return {"boardId": inv.board_id, "status": "accepted"}


@app.patch("/v1/boards/{board_id}/members/{user_id}", response_model=schemas.MemberOut)
def change_member_role(
    board_id: str,
    user_id: str,
    payload: schemas.MemberPatch,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    b = load_board_or_404(db, board_id)
    role = get_role(db, b, user)
    ensure_role({"admin"}, role)
    m = db.query(BoardMembership).filter(BoardMembership.board_id == b.id, BoardMembership.user_id == user_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="member not found")
    if payload.role not in {"admin", "writer", "reader"}:
        raise HTTPException(status_code=422, detail="invalid role")
    # last admin rule
    if m.role == "admin" and payload.role != "admin":
        admins = db.query(BoardMembership).filter(BoardMembership.board_id == b.id, BoardMembership.role == "admin").count()
        if admins <= 1:
            raise HTTPException(status_code=409, detail="last_admin_required")
    m.role = payload.role
    db.commit()
    return schemas.MemberOut(
        boardId=m.board_id,
        userId=m.user_id,
        role=m.role,
        status=m.status,
        invitedBy=m.invited_by,
        createdAt=m.created_at,
        updatedAt=m.updated_at,
        user=schemas.UserSummary(id=m.user_id, displayName=m.display_name or m.user_id, avatarUrl=m.avatar_url),
    )


@app.delete("/v1/boards/{board_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    board_id: str,
    user_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    b = load_board_or_404(db, board_id)
    role = get_role(db, b, user)
    ensure_role({"admin"}, role)
    m = db.query(BoardMembership).filter(BoardMembership.board_id == b.id, BoardMembership.user_id == user_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="member not found")
    if m.role == "admin":
        admins = db.query(BoardMembership).filter(BoardMembership.board_id == b.id, BoardMembership.role == "admin").count()
        if admins <= 1:
            raise HTTPException(status_code=409, detail="last_admin_required")
    db.delete(m)
    db.commit()
    return Response(status_code=204)


@app.post("/v1/boards/{board_id}:transfer-ownership", response_model=schemas.BoardOut)
def transfer_ownership(
    board_id: str,
    payload: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    b = load_board_or_404(db, board_id)
    role = get_role(db, b, user)
    ensure_role({"admin"}, role)
    new_owner = payload.get("newOwnerUserId")
    if not new_owner:
        raise HTTPException(status_code=422, detail="newOwnerUserId required")
    # ensure member exists
    m = db.query(BoardMembership).filter(BoardMembership.board_id == b.id, BoardMembership.user_id == new_owner).first()
    if not m:
        raise HTTPException(status_code=422, detail="user must be a member")
    b.owner = new_owner
    db.commit()
    return board_to_out(db, b, user)


@app.post("/v1/boards/{board_id}:leave", status_code=status.HTTP_204_NO_CONTENT)
def leave_board(
    board_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    b = load_board_or_404(db, board_id)
    m = db.query(BoardMembership).filter(BoardMembership.board_id == b.id, BoardMembership.user_id == user.id).first()
    if not m:
        return Response(status_code=204)
    if m.role == "admin":
        admins = db.query(BoardMembership).filter(BoardMembership.board_id == b.id, BoardMembership.role == "admin").count()
        if admins <= 1:
            raise HTTPException(status_code=409, detail="last_admin_required")
    db.delete(m)
    db.commit()
    return Response(status_code=204)


# Utility: echo ETag where appropriate
@app.middleware("http")
async def add_correlation(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id") or os.urandom(8).hex()
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    response.headers.setdefault("Content-Type", "application/json; charset=utf-8")
    return response
