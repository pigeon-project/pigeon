import json
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs


# Simple in-repo Kanban API implementing a useful subset of SPEC.md
# - SQLite for storage
# - Basic Bearer token handling: if token is a JWT, extract sub without signature verification;
#   if token is a raw string, treat that string as user id. Health/version are public.


DB_PATH = "./data.sqlite3"
API_PREFIX = "/v1"
VERSION = "1.0.0"


ALPH = "0123456789abcdefghijklmnopqrstuvwxyz"
A2I = {ch: i for i, ch in enumerate(ALPH)}
I2A = {i: ch for i, ch in enumerate(ALPH)}
MIN = 0
MAX = 35


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def gen_uuid() -> str:
    return str(uuid.uuid4())


def midpoint(left: str | None, right: str | None) -> str:
    L = left or ""
    R = right or ""
    i = 0
    out = []
    while True:
        l = A2I[L[i]] if i < len(L) else MIN
        r = A2I[R[i]] if i < len(R) else MAX
        if l + 1 < r:
            mid = (l + r) // 2
            out.append(I2A[mid])
            return "".join(out)
        out.append(I2A[l])
        i += 1


def ensure_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS boards (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          description TEXT,
          owner TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          version INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS board_memberships (
          board_id TEXT NOT NULL,
          user_id TEXT NOT NULL,
          role TEXT NOT NULL CHECK(role IN ('admin','writer','reader')),
          status TEXT NOT NULL CHECK(status IN ('active','pending')),
          invited_by TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY (board_id, user_id),
          FOREIGN KEY(board_id) REFERENCES boards(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS columns (
          id TEXT PRIMARY KEY,
          board_id TEXT NOT NULL,
          name TEXT NOT NULL,
          sort_key TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          version INTEGER NOT NULL,
          FOREIGN KEY(board_id) REFERENCES boards(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS cards (
          id TEXT PRIMARY KEY,
          board_id TEXT NOT NULL,
          column_id TEXT NOT NULL,
          title TEXT NOT NULL,
          description TEXT,
          sort_key TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          version INTEGER NOT NULL,
          FOREIGN KEY(board_id) REFERENCES boards(id) ON DELETE CASCADE,
          FOREIGN KEY(column_id) REFERENCES columns(id) ON DELETE CASCADE
        );
        """
    )
    conn.commit()
    conn.close()


def json_error(code: int, message: str, details: dict | None = None, request_id: str | None = None):
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "requestId": request_id or gen_uuid(),
        }
    }


def parse_bearer(auth_header: str | None) -> str | None:
    if not auth_header:
        return None
    if not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header.split(" ", 1)[1].strip()
    # Accept raw user id tokens for local/dev
    if token and "." not in token:
        return token
    # Best-effort parse JWT payload without signature verification.
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1] + "=="
        import base64

        data = json.loads(base64.urlsafe_b64decode(payload_b64.encode("utf-8")).decode("utf-8"))
        sub = data.get("sub")
        return sub
    except Exception:
        return None


def role_for_user(conn: sqlite3.Connection, board_id: str, user_id: str | None) -> str | None:
    if user_id is None:
        return None
    cur = conn.execute(
        "SELECT owner FROM boards WHERE id = ?",
        (board_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    if row[0] == user_id:
        return "admin"
    cur = conn.execute(
        "SELECT role FROM board_memberships WHERE board_id = ? AND user_id = ? AND status = 'active'",
        (board_id, user_id),
    )
    r = cur.fetchone()
    return r[0] if r else None


def require_member(role: str | None, min_role: str) -> bool:
    order = {"reader": 1, "writer": 2, "admin": 3}
    if role is None:
        return False
    return order.get(role, 0) >= order.get(min_role, 0)


class Handler(BaseHTTPRequestHandler):
    server_version = "TodoService/1.0"

    # Utilities
    def send_json(self, status: int, body: dict, headers: dict | None = None):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1024 * 1024:
            return None, json_error(400, "payload too large")
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}, None
        try:
            return json.loads(raw.decode("utf-8")), None
        except Exception:
            return None, json_error(400, "invalid_json")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == f"{API_PREFIX}/health":
            return self.send_json(200, {"status": "ok"})
        if path == f"{API_PREFIX}/version":
            return self.send_json(200, {"version": VERSION})

        # Auth
        user_id = parse_bearer(self.headers.get("Authorization"))
        if user_id is None:
            return self.send_json(401, json_error(401, "unauthorized"))

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            # GET /v1/boards
            if path == f"{API_PREFIX}/boards":
                q = parse_qs(parsed.query)
                limit = int(q.get("limit", [50])[0])
                limit = max(1, min(200, limit))
                cur = conn.execute(
                    """
                    SELECT b.*, 
                           COALESCE((SELECT role FROM board_memberships m WHERE m.board_id=b.id AND m.user_id=? AND m.status='active'),
                                    CASE WHEN b.owner=? THEN 'admin' END) as myRole,
                           (SELECT COUNT(*) FROM board_memberships m2 WHERE m2.board_id=b.id AND m2.status='active') + 1 as membersCount
                    FROM boards b
                    WHERE b.owner = ? OR EXISTS (
                        SELECT 1 FROM board_memberships m WHERE m.board_id=b.id AND m.user_id=? AND m.status='active'
                    )
                    ORDER BY b.created_at DESC
                    LIMIT ?
                    """,
                    (user_id, user_id, user_id, user_id, limit),
                )
                boards = []
                for r in cur.fetchall():
                    boards.append(
                        {
                            "id": r["id"],
                            "name": r["name"],
                            "description": r["description"],
                            "owner": r["owner"],
                            "createdAt": r["created_at"],
                            "updatedAt": r["updated_at"],
                            "myRole": r["myRole"] or "reader",
                            "membersCount": r["membersCount"] or 1,
                        }
                    )
                return self.send_json(200, {"boards": boards, "nextCursor": None})

            # GET /v1/boards/{boardId}
            m = re.fullmatch(fr"{API_PREFIX}/boards/([0-9a-f-]+)", path)
            if m:
                board_id = m.group(1)
                role = role_for_user(conn, board_id, user_id)
                if not require_member(role, "reader"):
                    return self.send_json(404, json_error(404, "not_found"))
                cur = conn.execute("SELECT * FROM boards WHERE id=?", (board_id,))
                b = cur.fetchone()
                if not b:
                    return self.send_json(404, json_error(404, "not_found"))
                cur = conn.execute(
                    "SELECT * FROM columns WHERE board_id = ? ORDER BY sort_key ASC, created_at ASC, id ASC",
                    (board_id,),
                )
                columns = [
                    {
                        "id": c["id"],
                        "boardId": c["board_id"],
                        "name": c["name"],
                        "sortKey": c["sort_key"],
                        "createdAt": c["created_at"],
                        "updatedAt": c["updated_at"],
                    }
                    for c in cur.fetchall()
                ]
                cur = conn.execute(
                    "SELECT * FROM cards WHERE board_id = ? ORDER BY sort_key ASC, created_at ASC, id ASC",
                    (board_id,),
                )
                cards = [
                    {
                        "id": r["id"],
                        "boardId": r["board_id"],
                        "columnId": r["column_id"],
                        "title": r["title"],
                        "description": r["description"],
                        "sortKey": r["sort_key"],
                        "createdAt": r["created_at"],
                        "updatedAt": r["updated_at"],
                        "version": r["version"],
                    }
                    for r in cur.fetchall()
                ]
                # myRole and membersCount
                cur = conn.execute(
                    "SELECT COUNT(*) FROM board_memberships WHERE board_id=? AND status='active'",
                    (board_id,),
                )
                members_count = cur.fetchone()[0] + 1
                body = {
                    "board": {
                        "id": b["id"],
                        "name": b["name"],
                        "description": b["description"],
                        "owner": b["owner"],
                        "createdAt": b["created_at"],
                        "updatedAt": b["updated_at"],
                        "myRole": role,
                        "membersCount": members_count,
                    },
                    "columns": columns,
                    "cards": cards,
                }
                return self.send_json(200, body)

            # GET /v1/boards/{boardId}/members
            m = re.fullmatch(fr"{API_PREFIX}/boards/([0-9a-f-]+)/members", path)
            if m:
                board_id = m.group(1)
                role = role_for_user(conn, board_id, user_id)
                if not require_member(role, "reader"):
                    return self.send_json(404, json_error(404, "not_found"))
                cur = conn.execute(
                    "SELECT user_id, role, status, invited_by, created_at, updated_at FROM board_memberships WHERE board_id=?",
                    (board_id,),
                )
                members = []
                for r in cur.fetchall():
                    members.append(
                        {
                            "boardId": board_id,
                            "userId": r["user_id"],
                            "role": r["role"],
                            "status": r["status"],
                            "invitedBy": r["invited_by"],
                            "createdAt": r["created_at"],
                            "updatedAt": r["updated_at"],
                            "user": {"id": r["user_id"], "displayName": r["user_id"], "avatarUrl": None},
                        }
                    )
                return self.send_json(200, {"members": members})

            return self.send_json(404, json_error(404, "not_found"))
        finally:
            conn.close()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == f"{API_PREFIX}/health" or path == f"{API_PREFIX}/version":
            return self.send_json(405, json_error(405, "method_not_allowed"))

        user_id = parse_bearer(self.headers.get("Authorization"))
        if user_id is None:
            return self.send_json(401, json_error(401, "unauthorized"))
        body, err = self.read_json()
        if err:
            return self.send_json(400, err)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            # POST /v1/boards
            if path == f"{API_PREFIX}/boards":
                name = (body.get("name") or "").strip()
                if len(name) == 0 or len(name) > 140:
                    return self.send_json(422, json_error(422, "validation_error", {"name": "1..140"}))
                description = body.get("description")
                if description is not None and len(description) > 2000:
                    return self.send_json(422, json_error(422, "validation_error", {"description": "0..2000"}))
                board_id = gen_uuid()
                now = now_iso()
                conn.execute(
                    "INSERT INTO boards(id,name,description,owner,created_at,updated_at,version) VALUES (?,?,?,?,?,?,?)",
                    (board_id, name, description, user_id, now, now, 1),
                )
                # Owner implicit admin. No explicit membership row for owner.
                conn.commit()
                return self.send_json(
                    201,
                    {
                        "id": board_id,
                        "name": name,
                        "description": description,
                        "owner": user_id,
                        "createdAt": now,
                        "updatedAt": now,
                        "myRole": "admin",
                        "membersCount": 1,
                    },
                )

            # POST /v1/boards/{boardId}/columns
            m = re.fullmatch(fr"{API_PREFIX}/boards/([0-9a-f-]+)/columns", path)
            if m and self.command == "POST":
                board_id = m.group(1)
                role = role_for_user(conn, board_id, user_id)
                if not require_member(role, "writer"):
                    return self.send_json(403, json_error(403, "forbidden"))
                name = (body.get("name") or "").strip()
                if len(name) == 0 or len(name) > 80:
                    return self.send_json(422, json_error(422, "validation_error", {"name": "1..80"}))
                before_id = body.get("beforeColumnId")
                after_id = body.get("afterColumnId")
                # Fetch anchors in order (same board)
                def get_key(cid):
                    if not cid:
                        return None
                    cur = conn.execute("SELECT sort_key FROM columns WHERE id=? AND board_id=?", (cid, board_id))
                    r = cur.fetchone()
                    return r[0] if r else None

                left_key = get_key(after_id)
                right_key = get_key(before_id)
                sort_key = midpoint(left_key, right_key)
                col_id = gen_uuid()
                now = now_iso()
                conn.execute(
                    "INSERT INTO columns(id,board_id,name,sort_key,created_at,updated_at,version) VALUES (?,?,?,?,?,?,1)",
                    (col_id, board_id, name, sort_key, now, now),
                )
                conn.commit()
                return self.send_json(
                    201,
                    {
                        "id": col_id,
                        "boardId": board_id,
                        "name": name,
                        "sortKey": sort_key,
                        "createdAt": now,
                        "updatedAt": now,
                    },
                )

            # POST /v1/boards/{boardId}/columns/{columnId}/cards
            m = re.fullmatch(fr"{API_PREFIX}/boards/([0-9a-f-]+)/columns/([0-9a-f-]+)/cards", path)
            if m:
                board_id, column_id = m.group(1), m.group(2)
                role = role_for_user(conn, board_id, user_id)
                if not require_member(role, "writer"):
                    return self.send_json(403, json_error(403, "forbidden"))
                # Verify column belongs to board
                cur = conn.execute("SELECT id, sort_key FROM columns WHERE id=? AND board_id=?", (column_id, board_id))
                col = cur.fetchone()
                if not col:
                    return self.send_json(404, json_error(404, "not_found"))
                title = (body.get("title") or "").strip()
                if len(title) == 0 or len(title) > 200:
                    return self.send_json(422, json_error(422, "validation_error", {"title": "1..200"}))
                description = body.get("description")
                if description is not None and len(description) > 8000:
                    return self.send_json(422, json_error(422, "validation_error", {"description": "0..8000"}))
                before_id = body.get("beforeCardId")
                after_id = body.get("afterCardId")
                def get_card_key(cid):
                    if not cid:
                        return None
                    cur = conn.execute(
                        "SELECT sort_key FROM cards WHERE id=? AND board_id=? AND column_id=?",
                        (cid, board_id, column_id),
                    )
                    r = cur.fetchone()
                    return r[0] if r else None

                left_key = get_card_key(after_id)
                right_key = get_card_key(before_id)
                sort_key = midpoint(left_key, right_key)
                card_id = gen_uuid()
                now = now_iso()
                conn.execute(
                    """
                    INSERT INTO cards(id,board_id,column_id,title,description,sort_key,created_at,updated_at,version)
                    VALUES (?,?,?,?,?,?,?, ?, 1)
                    """,
                    (card_id, board_id, column_id, title, description, sort_key, now, now),
                )
                conn.commit()
                return self.send_json(
                    201,
                    {
                        "id": card_id,
                        "boardId": board_id,
                        "columnId": column_id,
                        "title": title,
                        "description": description,
                        "sortKey": sort_key,
                        "createdAt": now,
                        "updatedAt": now,
                        "version": 1,
                    },
                )

            # POST /v1/boards/{boardId}/cards/{cardId}:move
            m = re.fullmatch(fr"{API_PREFIX}/boards/([0-9a-f-]+)/cards/([0-9a-f-]+):move", path)
            if m:
                board_id, card_id = m.group(1), m.group(2)
                role = role_for_user(conn, board_id, user_id)
                if not require_member(role, "writer"):
                    return self.send_json(403, json_error(403, "forbidden"))
                cur = conn.execute("SELECT * FROM cards WHERE id=?", (card_id,))
                card = cur.fetchone()
                if not card:
                    return self.send_json(404, json_error(404, "not_found"))
                if card["board_id"] != board_id:
                    return self.send_json(409, json_error(409, "invalid_move", {"reason": "cross_board"}))
                to_column_id = body.get("toColumnId") or card["column_id"]
                # Ensure to_column belongs to same board
                cur = conn.execute("SELECT id FROM columns WHERE id=? AND board_id=?", (to_column_id, board_id))
                if not cur.fetchone():
                    return self.send_json(422, json_error(422, "invalid_move", {"toColumnId": "not_in_board"}))
                before_id = body.get("beforeCardId")
                after_id = body.get("afterCardId")
                expected_version = body.get("expectedVersion")
                if expected_version is None or int(expected_version) != int(card["version"]):
                    return self.send_json(412, json_error(412, "precondition_failed"))

                def get_key(cid):
                    if not cid:
                        return None
                    cur = conn.execute(
                        "SELECT sort_key FROM cards WHERE id=? AND board_id=? AND column_id=?",
                        (cid, board_id, to_column_id),
                    )
                    r = cur.fetchone()
                    return r[0] if r else None

                left_key = get_key(after_id)
                right_key = get_key(before_id)
                new_key = midpoint(left_key, right_key)
                now = now_iso()
                conn.execute(
                    "UPDATE cards SET column_id=?, sort_key=?, updated_at=?, version=version+1 WHERE id=?",
                    (to_column_id, new_key, now, card_id),
                )
                conn.commit()
                cur = conn.execute("SELECT * FROM cards WHERE id=?", (card_id,))
                c = cur.fetchone()
                body = {
                    "id": c["id"],
                    "boardId": c["board_id"],
                    "columnId": c["column_id"],
                    "title": c["title"],
                    "description": c["description"],
                    "sortKey": c["sort_key"],
                    "createdAt": c["created_at"],
                    "updatedAt": c["updated_at"],
                    "version": c["version"],
                }
                return self.send_json(200, body)

            # POST /v1/boards/{boardId}/columns/{columnId}:move
            m = re.fullmatch(fr"{API_PREFIX}/boards/([0-9a-f-]+)/columns/([0-9a-f-]+):move", path)
            if m:
                board_id, column_id = m.group(1), m.group(2)
                role = role_for_user(conn, board_id, user_id)
                if not require_member(role, "writer"):
                    return self.send_json(403, json_error(403, "forbidden"))
                cur = conn.execute("SELECT * FROM columns WHERE id=? AND board_id=?", (column_id, board_id))
                col = cur.fetchone()
                if not col:
                    return self.send_json(404, json_error(404, "not_found"))
                before_id = body.get("beforeColumnId")
                after_id = body.get("afterColumnId")
                def get_key(cid):
                    if not cid:
                        return None
                    cur = conn.execute(
                        "SELECT sort_key FROM columns WHERE id=? AND board_id=?",
                        (cid, board_id),
                    )
                    r = cur.fetchone()
                    return r[0] if r else None

                left_key = get_key(after_id)
                right_key = get_key(before_id)
                new_key = midpoint(left_key, right_key)
                now = now_iso()
                conn.execute(
                    "UPDATE columns SET sort_key=?, updated_at=?, version=version+1 WHERE id=?",
                    (new_key, now, column_id),
                )
                conn.commit()
                return self.send_json(200, {
                    "id": col["id"],
                    "boardId": col["board_id"],
                    "name": col["name"],
                    "sortKey": new_key,
                    "createdAt": col["created_at"],
                    "updatedAt": now,
                })

            # POST /v1/boards/{boardId}:leave
            m = re.fullmatch(fr"{API_PREFIX}/boards/([0-9a-f-]+):leave", path)
            if m:
                board_id = m.group(1)
                role = role_for_user(conn, board_id, user_id)
                if role is None:
                    return self.send_json(404, json_error(404, "not_found"))
                if role == "admin":
                    # Check there is another admin
                    cur = conn.execute(
                        "SELECT COUNT(*) FROM board_memberships WHERE board_id=? AND role='admin' AND status='active'",
                        (board_id,),
                    )
                    admin_count = cur.fetchone()[0]
                    if admin_count == 0:
                        return self.send_json(409, json_error(409, "last_admin_required"))
                conn.execute(
                    "DELETE FROM board_memberships WHERE board_id=? AND user_id=?",
                    (board_id, user_id),
                )
                conn.commit()
                return self.send_json(204, {})

            return self.send_json(404, json_error(404, "not_found"))
        finally:
            conn.close()

    def do_PATCH(self):
        parsed = urlparse(self.path)
        path = parsed.path
        user_id = parse_bearer(self.headers.get("Authorization"))
        if user_id is None:
            return self.send_json(401, json_error(401, "unauthorized"))
        body, err = self.read_json()
        if err:
            return self.send_json(400, err)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            # PATCH /v1/boards/{boardId}
            m = re.fullmatch(fr"{API_PREFIX}/boards/([0-9a-f-]+)", path)
            if m:
                board_id = m.group(1)
                role = role_for_user(conn, board_id, user_id)
                if not require_member(role, "writer"):
                    return self.send_json(403, json_error(403, "forbidden"))
                cur = conn.execute("SELECT * FROM boards WHERE id=?", (board_id,))
                b = cur.fetchone()
                if not b:
                    return self.send_json(404, json_error(404, "not_found"))
                if_match = self.headers.get("If-Match")
                if if_match is None or if_match.strip('"') != str(b["version"]):
                    return self.send_json(412, json_error(412, "precondition_failed"))
                name = body.get("name", b["name"])
                description = body.get("description", b["description"])
                name = (name or "").strip()
                if len(name) == 0 or len(name) > 140:
                    return self.send_json(422, json_error(422, "validation_error", {"name": "1..140"}))
                now = now_iso()
                conn.execute(
                    "UPDATE boards SET name=?, description=?, updated_at=?, version=version+1 WHERE id=?",
                    (name, description, now, board_id),
                )
                conn.commit()
                cur = conn.execute("SELECT * FROM boards WHERE id=?", (board_id,))
                nb = cur.fetchone()
                return self.send_json(200, {
                    "id": nb["id"],
                    "name": nb["name"],
                    "description": nb["description"],
                    "owner": nb["owner"],
                    "createdAt": nb["created_at"],
                    "updatedAt": nb["updated_at"],
                    "myRole": role,
                    "membersCount": 1 + conn.execute("SELECT COUNT(*) FROM board_memberships WHERE board_id=? AND status='active'", (board_id,)).fetchone()[0],
                }, headers={"ETag": f'"{nb["version"]}"'})

            # PATCH /v1/boards/{boardId}/columns/{columnId}
            m = re.fullmatch(fr"{API_PREFIX}/boards/([0-9a-f-]+)/columns/([0-9a-f-]+)", path)
            if m:
                board_id, column_id = m.group(1), m.group(2)
                role = role_for_user(conn, board_id, user_id)
                if not require_member(role, "writer"):
                    return self.send_json(403, json_error(403, "forbidden"))
                cur = conn.execute("SELECT * FROM columns WHERE id=? AND board_id=?", (column_id, board_id))
                col = cur.fetchone()
                if not col:
                    return self.send_json(404, json_error(404, "not_found"))
                if_match = self.headers.get("If-Match")
                if if_match is None or if_match.strip('"') != str(col["version"]):
                    return self.send_json(412, json_error(412, "precondition_failed"))
                name = (body.get("name") or col["name"]).strip()
                if len(name) == 0 or len(name) > 80:
                    return self.send_json(422, json_error(422, "validation_error", {"name": "1..80"}))
                now = now_iso()
                conn.execute(
                    "UPDATE columns SET name=?, updated_at=?, version=version+1 WHERE id=?",
                    (name, now, column_id),
                )
                conn.commit()
                cur = conn.execute("SELECT * FROM columns WHERE id=?", (column_id,))
                col = cur.fetchone()
                return self.send_json(200, {
                    "id": col["id"],
                    "boardId": col["board_id"],
                    "name": col["name"],
                    "sortKey": col["sort_key"],
                    "createdAt": col["created_at"],
                    "updatedAt": col["updated_at"],
                }, headers={"ETag": f'"{col["version"]}"'})

            # PATCH /v1/boards/{boardId}/columns/{columnId}/cards/{cardId}
            m = re.fullmatch(fr"{API_PREFIX}/boards/([0-9a-f-]+)/columns/([0-9a-f-]+)/cards/([0-9a-f-]+)", path)
            if m:
                board_id, column_id, card_id = m.group(1), m.group(2), m.group(3)
                role = role_for_user(conn, board_id, user_id)
                if not require_member(role, "writer"):
                    return self.send_json(403, json_error(403, "forbidden"))
                cur = conn.execute("SELECT * FROM cards WHERE id=? AND board_id=? AND column_id=?", (card_id, board_id, column_id))
                card = cur.fetchone()
                if not card:
                    return self.send_json(404, json_error(404, "not_found"))
                if_match = self.headers.get("If-Match")
                if if_match is None or if_match.strip('"') != str(card["version"]):
                    return self.send_json(412, json_error(412, "precondition_failed"))
                title = (body.get("title") or card["title"]).strip()
                if len(title) == 0 or len(title) > 200:
                    return self.send_json(422, json_error(422, "validation_error", {"title": "1..200"}))
                description = body.get("description") if "description" in body else card["description"]
                if description is not None and len(description) > 8000:
                    return self.send_json(422, json_error(422, "validation_error", {"description": "0..8000"}))
                now = now_iso()
                conn.execute(
                    "UPDATE cards SET title=?, description=?, updated_at=?, version=version+1 WHERE id=?",
                    (title, description, now, card_id),
                )
                conn.commit()
                cur = conn.execute("SELECT * FROM cards WHERE id=?", (card_id,))
                c = cur.fetchone()
                return self.send_json(200, {
                    "id": c["id"],
                    "boardId": c["board_id"],
                    "columnId": c["column_id"],
                    "title": c["title"],
                    "description": c["description"],
                    "sortKey": c["sort_key"],
                    "createdAt": c["created_at"],
                    "updatedAt": c["updated_at"],
                    "version": c["version"],
                }, headers={"ETag": f'"{c["version"]}"'})

            return self.send_json(404, json_error(404, "not_found"))
        finally:
            conn.close()

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path
        user_id = parse_bearer(self.headers.get("Authorization"))
        if user_id is None:
            return self.send_json(401, json_error(401, "unauthorized"))
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            # DELETE /v1/boards/{boardId}
            m = re.fullmatch(fr"{API_PREFIX}/boards/([0-9a-f-]+)", path)
            if m:
                board_id = m.group(1)
                role = role_for_user(conn, board_id, user_id)
                if not require_member(role, "admin"):
                    return self.send_json(403, json_error(403, "forbidden"))
                cur = conn.execute("SELECT version FROM boards WHERE id=?", (board_id,))
                r = cur.fetchone()
                if not r:
                    return self.send_json(404, json_error(404, "not_found"))
                if_match = self.headers.get("If-Match")
                if if_match is None or if_match.strip('"') != str(r["version"]):
                    return self.send_json(412, json_error(412, "precondition_failed"))
                conn.execute("DELETE FROM boards WHERE id=?", (board_id,))
                conn.commit()
                self.send_response(204)
                self.end_headers()
                return

            # DELETE /v1/boards/{boardId}/columns/{columnId}
            m = re.fullmatch(fr"{API_PREFIX}/boards/([0-9a-f-]+)/columns/([0-9a-f-]+)", path)
            if m:
                board_id, column_id = m.group(1), m.group(2)
                role = role_for_user(conn, board_id, user_id)
                if not require_member(role, "writer"):
                    return self.send_json(403, json_error(403, "forbidden"))
                cur = conn.execute("SELECT version FROM columns WHERE id=? AND board_id=?", (column_id, board_id))
                col = cur.fetchone()
                if not col:
                    return self.send_json(404, json_error(404, "not_found"))
                if_match = self.headers.get("If-Match")
                if if_match is None or if_match.strip('"') != str(col["version"]):
                    return self.send_json(412, json_error(412, "precondition_failed"))
                conn.execute("DELETE FROM columns WHERE id=?", (column_id,))
                conn.commit()
                self.send_response(204)
                self.end_headers()
                return

            # DELETE /v1/boards/{boardId}/columns/{columnId}/cards/{cardId}
            m = re.fullmatch(fr"{API_PREFIX}/boards/([0-9a-f-]+)/columns/([0-9a-f-]+)/cards/([0-9a-f-]+)", path)
            if m:
                board_id, column_id, card_id = m.group(1), m.group(2), m.group(3)
                role = role_for_user(conn, board_id, user_id)
                if not require_member(role, "writer"):
                    return self.send_json(403, json_error(403, "forbidden"))
                cur = conn.execute("SELECT version FROM cards WHERE id=? AND board_id=? AND column_id=?", (card_id, board_id, column_id))
                c = cur.fetchone()
                if not c:
                    return self.send_json(404, json_error(404, "not_found"))
                if_match = self.headers.get("If-Match")
                if if_match is None or if_match.strip('"') != str(c["version"]):
                    return self.send_json(412, json_error(412, "precondition_failed"))
                conn.execute("DELETE FROM cards WHERE id=?", (card_id,))
                conn.commit()
                self.send_response(204)
                self.end_headers()
                return

            return self.send_json(404, json_error(404, "not_found"))
        finally:
            conn.close()


def run(host="0.0.0.0", port=8000):
    ensure_db()
    httpd = HTTPServer((host, port), Handler)
    print(f"Listening on {host}:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    run()

