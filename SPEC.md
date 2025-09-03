# TODO Service Specification

## Product Overview

### What this product is
A collaborative **kanban-style task manager** (Trello-like) where users create **boards** that contain **columns**
(lists) and **cards** (tasks). Boards can be shared with teammates using roles (admin/writer/reader).

### Who uses it
- **Individuals**: organize personal projects.
- **Teams**: plan and track work on shared boards.
- **Managers/Admins**: configure boards and membership, keep work flowing.

### Core value
- **Simple planning**: make boards/lists/cards fast.
- **Flexible ordering**: drag to reorder columns/cards freely.
- **Easy sharing**: add people with precise permissions.
- **Reliable**: changes are instantly visible to everyone.

### Key user workflows
1. Create a board, add “To Do / Doing / Done” columns.
2. Add cards; reorder cards and columns by drag & drop.
3. Invite teammates; set their roles.
4. Move cards between columns as work progresses.
5. Archive/delete when work is finished.

### Roles & capabilities
- **Admin**: full read/write, manage members, transfer ownership, delete board.
- **Writer**: read/write content (board, columns, cards); cannot manage members or delete board.
- **Reader**: read-only.

### Out of scope (v1)
- User management (assume external auth system).
- Public/anonymous boards.
- Attachments/comments/checklists.
- Webhooks/integrations.
- Full-text search across all boards.

---

# Technical Specification

## 1. Architecture Overview

- **API**: REST over HTTPS, stateless, JSON.
- **Auth**: OAuth2/JWT (Bearer token).
- **Storage**: Distributed DB holding boards, columns, cards, memberships, invitations. The SQLite database recommended for now.
- **Ordering**: Variable-length **lexicographic keys** (LexoRank-like) on columns and cards to support constant-time reordering without multi-row transactions.
- **Consistency**: Read-after-write for single-resource reads and board views.
- **Deployment**: Kubernetes (HPA, rolling updates). Multiple replicas; no sticky sessions.
- **Observability**: Structured logs with `requestId`, metrics, traces.

---

## 2. API Conventions

- **Base URL**: `https://api.todo.{domain}.com/v1`
- **Auth**: `Authorization: Bearer <JWT>`
- **Content Type**: `application/json; charset=utf-8`
- **Timestamps**: ISO-8601 UTC.
- **Idempotency**: `Idempotency-Key` header on POST that create/move.
- **Optimistic concurrency**: `ETag` header on GET; clients provide `If-Match` on PATCH/DELETE (*or* use body `expectedVersion` where specified).
- **Pagination**: cursor-based  
  Query: `?limit={1..200}&cursor={opaque}`; Response includes `nextCursor` or `null`.
- **Correlation**: `X-Request-Id` echoed back.
- **Versioning**: stable `/v1`; backward-compatible fields may be added.

### Standard Error Envelope
```json
{
  "error": {
    "code": "string",        // e.g., "validation_error", "not_found"
    "message": "human-readable",
    "details": { "field": "reason" },
    "requestId": "uuid"
  }
}
```

### Common Status Codes
`200 OK`, `201 Created`, `204 No Content`, `400 Bad Request`, `401 Unauthorized`, `403 Forbidden`, `404 Not Found`,
`409 Conflict`, `412 Precondition Failed`, `422 Unprocessable Entity`, `429 Too Many Requests`, `500 Internal Server Error`.

---

## 3. Security & Authorization

### JWT (required on all endpoints except health/version)
- **Claims** (minimum):
    - `sub` (string): userId
    - `exp`, `iat`, `iss`, `aud`
- API **must** validate signature, expiration, issuer, audience.

### Board-level RBAC
- Requester’s role computed from:
    - Owner ⇒ implicit `admin`.
    - Membership record ⇒ `admin|writer|reader`.

| Action | Owner/Admin | Writer | Reader | Non-member |
|---|---:|---:|---:|---:|
| List my boards | ✅ | ✅ | ✅ | ❌ |
| Get board (read) | ✅ | ✅ | ✅ | ❌ |
| Update board meta | ✅ | ✅ | ❌ | ❌ |
| Delete board | ✅ | ❌ | ❌ | ❌ |
| Create/Update/Delete column | ✅ | ✅ | ❌ | ❌ |
| Reorder columns | ✅ | ✅ | ❌ | ❌ |
| Create/Update/Move/Delete card | ✅ | ✅ | ❌ | ❌ |
| Invite/change/remove members | ✅ | ❌ | ❌ | ❌ |
| Transfer ownership | ✅ | ❌ | ❌ | ❌ |

**Rules**:
- A board must always have **≥1 admin** (cannot remove/demote the last admin).
- Transfer ownership only to an existing member (recipient becomes owner; previous owner remains admin unless changed).

---

## 4. Data Model (JSON Contracts & Constraints)

### UserSummary
```json
{
  "id": "userId",
  "displayName": "string",         // 1..128
  "avatarUrl": "string|null"       // URL or null
}
```

### Board
```json
{
  "id": "uuid",
  "name": "string",                // 1..140
  "description": "string|null",    // 0..2000
  "owner": "userId",
  "createdAt": "ISO-8601",
  "updatedAt": "ISO-8601",
  "myRole": "admin|writer|reader",
  "membersCount": 1
}
```

### Column
```json
{
  "id": "uuid",
  "boardId": "uuid",
  "name": "string",                // 1..80
  "sortKey": "string",             // LexoRank-like (base-36, lowercase)
  "createdAt": "ISO-8601",
  "updatedAt": "ISO-8601"
}
```

### Card
```json
{
  "id": "uuid",
  "boardId": "uuid",
  "columnId": "uuid",
  "title": "string",               // 1..200
  "description": "string|null",    // 0..8000
  "sortKey": "string",             // LexoRank-like (base-36, lowercase)
  "createdAt": "ISO-8601",
  "updatedAt": "ISO-8601",
  "version": 0                     // monotonic int
}
```

### BoardMembership
```json
{
  "boardId": "uuid",
  "userId": "userId",
  "role": "admin|writer|reader",
  "status": "active|pending",
  "invitedBy": "userId",
  "createdAt": "ISO-8601",
  "updatedAt": "ISO-8601",
  "user": { "id": "userId", "displayName": "string", "avatarUrl": "string|null" }
}
```

### Invitation
```json
{
  "id": "uuid",
  "boardId": "uuid",
  "email": "string",                       // present if invited by email
  "role": "admin|writer|reader",
  "status": "pending|accepted|expired|revoked",
  "token": "opaqueString"                  // returned once to admins on creation
}
```

**General constraints**
- All IDs are UUIDv4 strings unless stated.
- `name/title` trimmed; must not be empty after trimming.
- Strings normalized to NFC; `sortKey` strictly `[0-9a-z]+` (lowercase).
- Max request body size: **1 MiB**.

---

## 5. Ordering: LexoRank-like (Normative)

- **Alphabet**: `0123456789abcdefghijklmnopqrstuvwxyz` (base-36, lowercase).
- **Collation**: bytewise/binary (Postgres `COLLATE "C"`, MySQL `utf8mb4_bin`).
- **Sort**: primary `sortKey` ASC; tiebreakers `createdAt` ASC, `id` ASC.
- **Generation** (server-only): given left key `L` and right key `R` in the same sequence:
    1. Compare digits from left to right.
    2. If at any position `r - l ≥ 2`, choose the middle digit and **stop**.
    3. If differences are `0` or `1` across the shared prefix, **copy** the current digit from `L` and continue one level deeper; if needed, **append** one new digit between min (`'0'`) and the next digit in `R`.
    4. If no room at all levels, append `'m'` (or alphabetic mid) to `L`.  
       This guarantees `L < M < R`.
- **Anchors**:
    - Insert **at start**: `mid(None, firstKey)` (treat `None` as infinite `'0'`).
    - Insert **at end**: `mid(lastKey, None)` (treat `None` as infinite `'z'`).
    - Insert **between** two known neighbors: `mid(L, R)`.
- **Concurrency**:
    - Update only the moved row (card/column).
    - If unique `(boardId, columnId, sortKey, id)` conflicts, recompute with refined anchors and retry.
- **Validation**:
    - Server validates provided anchors exist and belong to the target container (board or column).

---

## 6. Endpoints

### 6.1 Boards

#### Create a board
```
POST /v1/boards
Authorization: Bearer <JWT>
Content-Type: application/json
Idempotency-Key: <uuid>

{ "name": "Project Pigeon", "description": "Internal tooling" }
```
**Rules**: `name` required, 1..140; `description` optional.  
**Responses**:
- `201 Created` with board.
- `422` on validation error.

#### List boards (paginated)
```
GET /v1/boards?limit=50&cursor=opaque
Authorization: Bearer <JWT>
```
**Response**
```json
{
  "boards": [
    {
      "id":"...","name":"...","description":"...","owner":"...",
      "createdAt":"...","updatedAt":"...","myRole":"writer","membersCount":4
    }
  ],
  "nextCursor": "opaque-or-null"
}
```

#### Get a board (with sorted columns and cards)
```
GET /v1/boards/{boardId}
Authorization: Bearer <JWT>
```
**Behavior**: returns the board, **columns sorted by `sortKey`**, and **cards sorted by `sortKey`** within their columns.  
**Response**
```json
{
  "board": { "id":"...","name":"...","description":"...","owner":"...","createdAt":"...","updatedAt":"...","myRole":"admin","membersCount":3 },
  "columns": [
    {"id":"col-a","boardId":"...","name":"TODO","sortKey":"5n","createdAt":"...","updatedAt":"..."},
    {"id":"col-b","boardId":"...","name":"InProgress","sortKey":"g","createdAt":"...","updatedAt":"..."}
  ],
  "cards": [
    {"id":"card-1","boardId":"...","columnId":"col-a","title":"Write spec","description":null,"sortKey":"6","createdAt":"...","updatedAt":"...","version":2},
    {"id":"card-2","boardId":"...","columnId":"col-a","title":"Polish README","description":"Add examples","sortKey":"6m","createdAt":"...","updatedAt":"...","version":1}
  ]
}
```

#### Update a board
```
PATCH /v1/boards/{boardId}
Authorization: Bearer <JWT>
If-Match: "ETag"
Content-Type: application/json

{ "name": "Project Falcon", "description": "Updated" }
```
**Responses**: `200 OK`, `412 Precondition Failed` (stale ETag), `422`.

#### Delete a board (cascading)
```
DELETE /v1/boards/{boardId}
Authorization: Bearer <JWT>
If-Match: "ETag"
```
**Responses**: `204 No Content`, `412`, `403` (not admin).

---

### 6.2 Columns

#### Create a column
```
POST /v1/boards/{boardId}/columns
Authorization: Bearer <JWT>
Content-Type: application/json
Idempotency-Key: <uuid>

{ "name": "InProgress", "beforeColumnId": null, "afterColumnId": "col-z" }
```
**Rules**: `name` required. If both anchors omitted ⇒ insert at **end**.  
**Response** `201 Created` with column.

#### Rename a column
```
PATCH /v1/boards/{boardId}/columns/{columnId}
Authorization: Bearer <JWT>
If-Match: "ETag"
Content-Type: application/json

{ "name": "Doing" }
```
**Responses**: `200 OK`, `412`, `422`.

#### Move (reorder) a column
```
POST /v1/boards/{boardId}/columns/{columnId}:move
Authorization: Bearer <JWT>
Content-Type: application/json
Idempotency-Key: <uuid>

{ "beforeColumnId": "col-a", "afterColumnId": "col-c" }
```
**Behavior**: server computes a new `sortKey` strictly between anchors (must be on the same board).  
**Responses**: `200 OK`, `409 invalid_move`, `422`.

#### Delete a column (cascading)
```
DELETE /v1/boards/{boardId}/columns/{columnId}
Authorization: Bearer <JWT>
If-Match: "ETag"
```
**Response** `204 No Content`. Also deletes all cards in the column.

---

### 6.3 Cards

#### Create a card
```
POST /v1/boards/{boardId}/columns/{columnId}/cards
Authorization: Bearer <JWT>
Idempotency-Key: <uuid>
Content-Type: application/json

{
  "title": "Write the TODO specification",
  "description": null,
  "beforeCardId": null,
  "afterCardId": "card-123"
}
```
**Rules**: `title` required; insert at end if no anchors given.  
**Response** `201 Created` with card (server generates `sortKey`).

#### Update a card
```
PATCH /v1/boards/{boardId}/columns/{columnId}/cards/{cardId}
Authorization: Bearer <JWT>
If-Match: "ETag"
Content-Type: application/json

{ "title": "Polish README", "description": "Add examples" }
```
**Responses**: `200 OK`, `412`, `422`.

#### Move a card (within the same board)
```
POST /v1/boards/{boardId}/cards/{cardId}:move
Authorization: Bearer <JWT>
Content-Type: application/json
Idempotency-Key: <uuid>

{
  "toColumnId": "col-b",
  "beforeCardId": "card-7",
  "afterCardId": "card-12",
  "expectedVersion": 7
}
```
**Behavior**:
- If `toColumnId` omitted ⇒ remain in current column.
- Anchors must reference cards **in `toColumnId`**.
- Server computes new `sortKey` via LexoRank midpoint; single-row update with optimistic lock (`expectedVersion` or `If-Match`).  
  **Responses**: `200 OK`, `409 invalid_move` (cross-board), `412` (stale), `422`.

#### Delete a card
```
DELETE /v1/boards/{boardId}/columns/{columnId}/cards/{cardId}
Authorization: Bearer <JWT>
If-Match: "ETag"
```
**Response** `204 No Content`.

---

### 6.4 Membership & Sharing

#### List members
```
GET /v1/boards/{boardId}/members
Authorization: Bearer <JWT>
```
**Auth**: any member.  
**Response** `200 OK` with member list.

#### Invite a member (email or userId)
```
POST /v1/boards/{boardId}/members
Authorization: Bearer <JWT>
Content-Type: application/json
Idempotency-Key: <uuid>

{ "email": "teammate@example.com", "role": "writer" }
-- OR --
{ "userId": "user_456", "role": "reader" }
```
**Auth**: admin.  
**Responses**: `201 Created` with `membership` (pending) and `invitation` (token shown once), `422`.

#### Accept invitation (token-based)
```
POST /v1/invitations/accept
Authorization: Bearer <JWT>
Content-Type: application/json

{ "token": "<opaque-shown-once>" }
```
**Responses**: `200 OK { "boardId":"...", "status":"accepted" }`, `400/404/410` on invalid/expired.

#### Change a member’s role
```
PATCH /v1/boards/{boardId}/members/{userId}
Authorization: Bearer <JWT>
Content-Type: application/json

{ "role": "reader" }
```
**Responses**: `200 OK`, `409 last_admin_required`, `422`.

#### Remove a member
```
DELETE /v1/boards/{boardId}/members/{userId}
Authorization: Bearer <JWT>
```
**Responses**: `204 No Content`, `409 last_admin_required`.

#### Transfer ownership
```
POST /v1/boards/{boardId}:transfer-ownership
Authorization: Bearer <JWT>
Content-Type: application/json

{ "newOwnerUserId": "user_456" }
```
**Responses**: `200 OK`, `403`, `422`.

#### Leave a board (self)
```
POST /v1/boards/{boardId}:leave
Authorization: Bearer <JWT>
```
**Responses**: `204 No Content`, `409 last_admin_required`.

---

### 6.5 Health & Metadata

- `GET /v1/health` → `200 { "status": "ok" }`
- `GET /v1/version` → `200 { "version": "1.0.0" }`

---

## 7. Validation Rules (Selected)

- **Board.name**: 1..140 chars; trimmed; non-empty.
- **Column.name**: 1..80 chars; trimmed; non-empty.
- **Card.title**: 1..200 chars; trimmed; non-empty.
- **Descriptions**: up to 8,000 chars.
- **sortKey**: server-generated; accepts only `[0-9a-z]+`.
- **Anchors**:
    - Column move: anchors must be columns of the same board.
    - Card move: anchors must be cards of `toColumnId` (or current column if `toColumnId` omitted).
- **Cross-board card move**: **not allowed** → `409 invalid_move`.
- **ETag/Version**: mismatch → `412 precondition_failed`.

---

## 8. Concurrency & Idempotency

- **Optimistic locking**:
    - Cards carry `version` (int). Payloads for move/update may include `expectedVersion`; otherwise use `If-Match` ETag.
    - On mismatch: `412` and client must refresh and retry.
- **Idempotency**:
    - For POST create/move, clients send `Idempotency-Key` (UUID).
    - Server stores a 24h key→response cache; duplicate keys return the original response (safe retries).
- **Atomicity**:
    - Moves are **single-row** updates (change `columnId` and `sortKey` of the target card only).
- **Deterministic order**:
    - When two concurrent inserts compute same `sortKey`, final sort is `(sortKey, createdAt, id)`; server may retry with a refined midpoint to minimize equality.

---

## 9. Rate Limiting

- Default: **1000 RPH** per user; **600 RPH** per IP (burst-friendly).
- Headers:
  `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, `Retry-After`.
- On exceed: `429 Too Many Requests`.

---

## 10. Performance & Limits

- **SLO**: p95 latency ≤ 150ms for read, ≤ 250ms for simple writes at 1k RPS.
- **Max per board**: 100 columns, 1k cards (soft limits; return `422` if exceeded).
- **List paging**: default `limit=50`; max `limit=200`.

---

## 11. Persistence (Reference: Postgres)

**Collation note**: ensure bytewise ordering for `sort_key`.

```sql
CREATE TABLE boards (
  id uuid PRIMARY KEY,
  name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 140),
  description text,
  owner text NOT NULL,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL
);

CREATE TABLE columns (
  id uuid PRIMARY KEY,
  board_id uuid NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
  name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 80),
  sort_key text NOT NULL COLLATE "C" CHECK (sort_key ~ '^[0-9a-z]+$'),
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL
);
CREATE INDEX idx_columns_list ON columns (board_id, sort_key, id);

CREATE TABLE cards (
  id uuid PRIMARY KEY,
  board_id uuid NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
  column_id uuid NOT NULL REFERENCES columns(id) ON DELETE CASCADE,
  title text NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 200),
  description text,
  sort_key text NOT NULL COLLATE "C" CHECK (sort_key ~ '^[0-9a-z]+$'),
  version int NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL
);
CREATE INDEX idx_cards_list ON cards (board_id, column_id, sort_key, id);

CREATE TABLE memberships (
  board_id uuid NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
  user_id text NOT NULL,
  role text NOT NULL CHECK (role IN ('admin','writer','reader')),
  status text NOT NULL CHECK (status IN ('active','pending')),
  invited_by text NOT NULL,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  PRIMARY KEY (board_id, user_id)
);

CREATE TABLE invitations (
  id uuid PRIMARY KEY,
  board_id uuid NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
  email text,
  role text NOT NULL CHECK (role IN ('admin','writer','reader')),
  status text NOT NULL CHECK (status IN ('pending','accepted','expired','revoked')),
  token text NOT NULL,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL
);
```

**Note**: Store `token` hashed (e.g., SHA-256) and compare with constant-time checks.

---

## 12. LexoRank Midpoint (Reference Pseudocode)

```
ALPH = "0123456789abcdefghijklmnopqrstuvwxyz"
A2I = {ch: i for i, ch in enumerate(ALPH)}
I2A = {i: ch for i, ch in enumerate(ALPH)}
MIN = 0
MAX = 35

# left or right may be None
def midpoint(left, right):
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
```

---

## 13. Validation & Error Examples

### Empty title
```
POST /v1/boards/{b}/columns/{c}/cards
{ "title": "" }
```
**422**
```json
{ "error": { "code": "validation_error", "message": "title must not be empty", "details": {"title":"required_non_empty"}, "requestId":"..." } }
```

### Cross-board move rejected
```
POST /v1/boards/{boardA}/cards/{card}:move
{ "toColumnId": "column-from-board-B" }
```
**409**
```json
{ "error": { "code": "invalid_move", "message": "Card can be moved only within the same board.", "requestId":"..." } }
```

### Attempt to delete last admin
```
DELETE /v1/boards/{b}/members/{lastAdmin}
```
**409**
```json
{ "error": { "code": "last_admin_required", "message": "Board must have at least one admin.", "requestId":"..." } }
```

### ETag mismatch
```
PATCH /v1/boards/{b}
If-Match: "stale"
```
**412 Precondition Failed**

---

## 14. Operational Concerns

- **Clock**: rely on server time; ignore client-provided timestamps.
- **Retries**: safe to retry `POST` with same `Idempotency-Key`. Clients should retry on 409/412 after refetch.
- **Soft deletes**: **not supported** (deletions are permanent).
- **Backward compatibility**: New fields may appear; clients must ignore unknown fields.
- **PII**: Only minimal identifiers; redact emails from member listings for non-admins if required by policy.

---

## 15. Quality Gates (Acceptance Criteria)

- Reordering columns/cards does **one** persistent mutation (no multi-row transaction).
- Concurrent reorders never corrupt order; final list sorted by `(sortKey, createdAt, id)`.
- Moving a card across columns within a board is allowed; across boards is rejected with `409 invalid_move`.
- Every write guarded by optimistic concurrency (`If-Match` or `expectedVersion`); stale updates refuse with `412`.
- All list endpoints are strongly consistent; GET after 200/201/204 reflects latest state.
- Pagination returns stable cursors; repeated calls with unchanged data are deterministic.
- Rate limiting returns proper headers and `429` on exceed.
- Health returns `{ "status": "ok" }`; Version returns `{ "version": "1.0.0" }`.

---

## 16. Example Flows

### Create → Invite → Move
1. `POST /boards` → 201 board.
2. `POST /boards/{b}/columns` (three times) → 201 each; names “To Do”, “Doing”, “Done”.
3. `POST /boards/{b}/columns/{todo}/cards` (several) → 201 cards.
4. `POST /boards/{b}/members` with `{ "userId": "u2", "role":"writer" }` → 201.
5. `POST /boards/{b}/cards/{card}:move` with `toColumnId=doing` and anchors → 200.

---

## 17. UI

Create a simple UI to demonstrate core flows:
- Board creation.
- Adding/reordering columns.
- Adding/reordering/moving cards.
- Inviting members.

Use ReactJS or similar; focus on functionality over styling.

*End of specification.*
