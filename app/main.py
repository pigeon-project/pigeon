from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Header, Response

from .auth import get_current_user
from .models import (
    BoardCreate,
    BoardOut,
    BoardUpdate,
    CardCreate,
    CardMove,
    CardOut,
    CardUpdate,
    ColumnCreate,
    ColumnMove,
    ColumnOut,
    ColumnUpdate,
    Board,
    Column,
    Card,
)
from .storage import storage

app = FastAPI(title="Pigeon API", version="1.0.0")


# === Helpers ===


def board_out(board: Board, user_id: str) -> BoardOut:
    role = board.members.get(user_id)
    return BoardOut(
        id=board.id,
        name=board.name,
        description=board.description,
        owner=board.owner,
        createdAt=board.created_at,
        updatedAt=board.updated_at,
        myRole=role or "reader",
        membersCount=len(board.members),
    )


def column_out(column: Column) -> ColumnOut:
    return ColumnOut(
        id=column.id,
        boardId=column.board_id,
        name=column.name,
        sortKey=column.sort_key,
        createdAt=column.created_at,
        updatedAt=column.updated_at,
    )


def card_out(card: Card) -> CardOut:
    return CardOut(
        id=card.id,
        boardId=card.board_id,
        columnId=card.column_id,
        title=card.title,
        description=card.description,
        sortKey=card.sort_key,
        createdAt=card.created_at,
        updatedAt=card.updated_at,
        version=card.version,
    )


def check_role(board: Board, user_id: str, roles: list[str]) -> None:
    role = board.members.get(user_id)
    if role not in roles:
        raise HTTPException(status_code=403, detail="forbidden")


# === Health & metadata ===


@app.get("/v1/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/v1/version")
def version() -> dict:
    return {"version": "1.0.0"}


# === Board endpoints ===


@app.post("/v1/boards", response_model=BoardOut, status_code=201)
def create_board(payload: BoardCreate, user: str = Depends(get_current_user)):
    board = storage.create_board(user, payload.name, payload.description)
    return board_out(board, user)


@app.get("/v1/boards", response_model=dict)
def list_boards(user: str = Depends(get_current_user)):
    boards = [board_out(b, user) for b in storage.list_boards_for_user(user)]
    return {"boards": boards, "nextCursor": None}


@app.get("/v1/boards/{board_id}", response_model=dict)
def get_board(board_id: str, response: Response, user: str = Depends(get_current_user)):
    board = storage.get_board(board_id)
    check_role(board, user, ["admin", "writer", "reader"])
    response.headers["ETag"] = f'"{board.version}"'
    columns = sorted(board.columns.values(), key=lambda c: (c.sort_key, c.created_at, c.id))
    cards = sorted(board.cards.values(), key=lambda c: (c.sort_key, c.created_at, c.id))
    return {
        "board": board_out(board, user),
        "columns": [column_out(c) for c in columns],
        "cards": [card_out(c) for c in cards],
    }


@app.patch("/v1/boards/{board_id}", response_model=BoardOut)
def update_board(
    board_id: str,
    payload: BoardUpdate,
    user: str = Depends(get_current_user),
    if_match: str = Header(..., alias="If-Match"),
):
    board = storage.get_board(board_id)
    check_role(board, user, ["admin", "writer"])
    if if_match.strip('"') != str(board.version):
        raise HTTPException(status_code=412, detail="precondition_failed")
    if payload.name is not None:
        board.name = payload.name.strip()
    if payload.description is not None:
        board.description = payload.description.strip() if payload.description else None
    board.version += 1
    board.updated_at = datetime.now(timezone.utc)
    return board_out(board, user)


@app.delete("/v1/boards/{board_id}", status_code=204)
def delete_board(
    board_id: str,
    user: str = Depends(get_current_user),
    if_match: str = Header(..., alias="If-Match"),
):
    board = storage.get_board(board_id)
    check_role(board, user, ["admin"])
    if if_match.strip('"') != str(board.version):
        raise HTTPException(status_code=412, detail="precondition_failed")
    storage.delete_board(board_id)
    return Response(status_code=204)


# === Column endpoints ===


@app.post("/v1/boards/{board_id}/columns", response_model=ColumnOut, status_code=201)
def create_column(
    board_id: str,
    payload: ColumnCreate,
    user: str = Depends(get_current_user),
):
    board = storage.get_board(board_id)
    check_role(board, user, ["admin", "writer"])
    column = storage.create_column(board, payload.name, payload.beforeColumnId, payload.afterColumnId)
    return column_out(column)


@app.patch("/v1/boards/{board_id}/columns/{column_id}", response_model=ColumnOut)
def rename_column(
    board_id: str,
    column_id: str,
    payload: ColumnUpdate,
    user: str = Depends(get_current_user),
    if_match: str = Header(..., alias="If-Match"),
):
    board = storage.get_board(board_id)
    check_role(board, user, ["admin", "writer"])
    column = board.columns[column_id]
    if if_match.strip('"') != str(column.version):
        raise HTTPException(status_code=412, detail="precondition_failed")
    column.name = payload.name.strip()
    column.version += 1
    column.updated_at = datetime.now(timezone.utc)
    return column_out(column)


@app.post("/v1/boards/{board_id}/columns/{column_id}:move", response_model=ColumnOut)
def move_column(
    board_id: str,
    column_id: str,
    payload: ColumnMove,
    user: str = Depends(get_current_user),
):
    board = storage.get_board(board_id)
    check_role(board, user, ["admin", "writer"])
    column = board.columns[column_id]
    column = storage.move_column(board, column, payload.beforeColumnId, payload.afterColumnId)
    return column_out(column)


@app.delete("/v1/boards/{board_id}/columns/{column_id}", status_code=204)
def delete_column(
    board_id: str,
    column_id: str,
    user: str = Depends(get_current_user),
    if_match: str = Header(..., alias="If-Match"),
):
    board = storage.get_board(board_id)
    check_role(board, user, ["admin", "writer"])
    column = board.columns[column_id]
    if if_match.strip('"') != str(column.version):
        raise HTTPException(status_code=412, detail="precondition_failed")
    storage.delete_column(board, column_id)
    return Response(status_code=204)


# === Card endpoints ===


@app.post("/v1/boards/{board_id}/columns/{column_id}/cards", response_model=CardOut, status_code=201)
def create_card(
    board_id: str,
    column_id: str,
    payload: CardCreate,
    user: str = Depends(get_current_user),
):
    board = storage.get_board(board_id)
    check_role(board, user, ["admin", "writer"])
    column = board.columns[column_id]
    card = storage.create_card(
        board,
        column,
        payload.title,
        payload.description,
        payload.beforeCardId,
        payload.afterCardId,
    )
    return card_out(card)


@app.patch("/v1/boards/{board_id}/columns/{column_id}/cards/{card_id}", response_model=CardOut)
def update_card(
    board_id: str,
    column_id: str,
    card_id: str,
    payload: CardUpdate,
    user: str = Depends(get_current_user),
    if_match: str = Header(..., alias="If-Match"),
):
    board = storage.get_board(board_id)
    check_role(board, user, ["admin", "writer"])
    card = board.cards[card_id]
    if card.column_id != column_id:
        raise HTTPException(status_code=400, detail="wrong_column")
    if if_match.strip('"') != str(card.version):
        raise HTTPException(status_code=412, detail="precondition_failed")
    if payload.title is not None:
        card.title = payload.title.strip()
    if payload.description is not None:
        card.description = payload.description.strip() if payload.description else None
    card.version += 1
    card.updated_at = datetime.now(timezone.utc)
    return card_out(card)


@app.post("/v1/boards/{board_id}/cards/{card_id}:move", response_model=CardOut)
def move_card(
    board_id: str,
    card_id: str,
    payload: CardMove,
    user: str = Depends(get_current_user),
):
    board = storage.get_board(board_id)
    check_role(board, user, ["admin", "writer"])
    card = board.cards[card_id]
    if payload.expectedVersion is not None and payload.expectedVersion != card.version:
        raise HTTPException(status_code=412, detail="precondition_failed")
    to_column_id = payload.toColumnId or card.column_id
    if to_column_id not in board.columns:
        raise HTTPException(status_code=409, detail="invalid_move")
    to_column = board.columns[to_column_id]
    card = storage.move_card(board, card, to_column, payload.beforeCardId, payload.afterCardId)
    return card_out(card)


@app.delete("/v1/boards/{board_id}/columns/{column_id}/cards/{card_id}", status_code=204)
def delete_card(
    board_id: str,
    column_id: str,
    card_id: str,
    user: str = Depends(get_current_user),
    if_match: str = Header(..., alias="If-Match"),
):
    board = storage.get_board(board_id)
    check_role(board, user, ["admin", "writer"])
    card = board.cards[card_id]
    if card.column_id != column_id:
        raise HTTPException(status_code=400, detail="wrong_column")
    if if_match.strip('"') != str(card.version):
        raise HTTPException(status_code=412, detail="precondition_failed")
    storage.delete_card(board, card_id)
    return Response(status_code=204)
