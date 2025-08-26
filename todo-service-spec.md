# The TODO service

A backend service for managing the “TODO” boards, columns and cards.

## Functional requirements

-   **Create a board**: User can create a board to aggregate columns. For example, User can create a board named "Project Pigeon". Each board has a unique ID and includes fields such as `name`, `description`, `owner` and `columnsOrder`. All fields can be updated except the ID. `columnsOrder` is an array of columns ids, the order of the array represent the order of the columns.
    
-   **Create a column**: User can create a column for a specific board. For example, User can create columns "TODO", "InProgress", "Done" in the "Project Pigeon" board. Each column must have a unique ID. It als contains the `name`  field which is required, non‑empty and can be updated.
    
-   **Create a card**: User can create a card for any column in a board. For example, create a card titled "Write the TODO specification" in the "TODO" column. Each card has a unique ID. Updatable fields: `title` (required, non‑empty), `description` (optional, can be empty) and `cardsOrder`
    
-   **Move card**: User can move a card from one column to another **within the same board**.
    
-   **Move column**: User can change the order of columns.
    
-   **Remove card**: User can remove a card.
    
-   **Remove column**: User can remove a column. When removed, **all cards in the column are also removed**.
    
-   **Remove board**: User can remove a board. When removed, **all columns and their cards are also removed**.
    
-   **List boards**: List boards available for the authenticated user.
    
-   **List a board**: Return the board detail **including columns and cards**.
    

## Non-functional requirements (selected)

-   **Availability**: High availability.
    
-   **Scalability**: Capable of handling thousands of requests per second.
    
-   **Durability**: Data persists unless explicitly deleted by the user.
    
-   **Consistency**: Strongly consistent. Once an update completes, subsequent reads reflect it.
    

## Building blocks

-   **OAuth2 / JWT** – Each request must include an `Authorization: Bearer <JWT>` header. The service validates the token and authorizes access to user data.
    
-   **Storage** – Distributed database for boards, columns and cards. Thanks to it, service data will survive restarts.
    
-   **Kubernetes** – Service is deployed to and managed by Kubernetes. It supports horizontal scaling and traffic routing.

----------

# API (REST over HTTP)

**Base URL**: `https://api.todo.{domain}.com/v1`
**Auth**: `Authorization: Bearer <JWT>` (required unless explicitly stated).
**Content Type**: `application/json; charset=utf-8`
**Versioning**: URI prefix `/v1`; backwards-compatible changes may add fields 
**Standard error**:

```
{
  "error": {
    "code": "string",          // e.g., "validation_error", "not_found"
    "message": "human-readable",
    "details": {"field": "reason"},
    "requestId": "uuid"
  }
}
```

**Common status codes**: `200 OK`, `201 Created`, `204 No Content`, `400 Bad Request`, `401 Unauthorized`, `403 Forbidden`, `404 Not Found`, `409 Conflict`, `412 Precondition Failed`, `422 Unprocessable Entity`, `429 Too Many Requests`, `500 Internal Server Error`.

----------

## Resource model (simplified)

```
// Board
{
  "id": "uuid",
  "name": "string",
  "description": "string|null",
  "owner": "userId",
  "createdAt": "ISO-8601",
  "updatedAt": "ISO-8601",
  "columnsOrder": ["idOfColumnA", "idOfColumnB", "idOfColumnC", ...]
}

// Column
{
  "id": "uuid",
  "boardId": "uuid",
  "name": "string",
  "createdAt": "ISO-8601",
  "updatedAt": "ISO-8601",
  "cardsOrder": ["idOfCardX", "idOfCardY", "idOfCardZ", ...]
}

// Card
{
  "id": "uuid",
  "boardId": "uuid",
  "columnId": "uuid",
  "title": "string",
  "description": "string|null",
  "createdAt": "ISO-8601",
  "updatedAt": "ISO-8601"
}
```

----------

## Boards

### Create a board

**Request**

```
POST /v1/boards
Authorization: Bearer <JWT>
Content-Type: application/json

{
  "name": "Project Pigeon",
  "description": "Internal tooling"
}
```

**Rules**: `name` required, non-empty. `description` optional, can be empty.

**Response**

```
201 Created
Location: /v1/boards/8a6d...
Content-Type: application/json

{
  "id": "8a6d...",
  "name": "Project Pigeon",
  "description": "Internal tooling",
  "owner": "user_123",
  "createdAt": "2025-08-25T09:42:15Z",
  "updatedAt": "2025-08-25T09:42:15Z"
}
```

### List boards

```
GET /v1/boards
Authorization: Bearer <JWT>
```

**Response**

```
{
  "boards: [
  {"id":"...","name":"...","description":"...","owner":"...","createdAt":"...","updatedAt":"..."},
  ...
  ]
}
```

### Get a board (with columns and cards)

```
GET /v1/boards/{boardId}
Authorization: Bearer <JWT>
```

**Response**

```
{
  "board:{"id":"...","name":"...","description":"...","owner":"...","createdAt":"...","updatedAt":"..."},
  "columns": [
    {"id":"...","boardId":"...","name":"TODO","order":0},
    {"id":"...","name":"InProgress","order":1},
    ...],
  "cards": [
    {"id":"...","boardId":"...","columnId":"...","title":"Write the TODO specification","description":null},
    ...]
}
```

### Update a board

```
PATCH /v1/boards/{boardId}
Authorization: Bearer <JWT>
Content-Type: application/json

{ "name": "Project Falcon",
  "description": "Updated",
  "columnsOrder": ["id-of-todo-column","id-of-inprogress-column","id-of-done-column"] // List of all columns ids in desired order
}
```

**Response**  `200 OK` with updated resource.

### Delete a board (cascading)

```
DELETE /v1/boards/{boardId}
Authorization: Bearer <JWT>
```

**Response**  `204 No Content`. Removes all columns and cards of the board.

----------

## Columns

### Create a column

```
POST /v1/boards/{boardId}/columns
Authorization: Bearer <JWT>
Content-Type: application/json

{ "name": "InProgress"}
```

**Rules**: `name` required, not-empty.

**Response**  `201 Created` with column resource.

### Update a column

```
PATCH /v1/boards/{boardId}/columns/{columnId}
Authorization: Bearer <JWT>
Content-Type: application/json

{ "name": "Doing", "cardsOrder": ["idOfCardX", "idOfCardY", "idOfCardZ", ...]}
```

**Response**  `200 OK` with updated resource.

### Delete a column (cascading)

```
DELETE /v1/boards/{boardId}/columns/{columnId}
Authorization: Bearer <JWT>
```

**Response**  `204 No Content`. Removes the column and all its cards.

----------

## Cards

### Create a card

```
POST /v1/boards/{boardId}/columns/{columnId}/cards
Authorization: Bearer <JWT>
Idempotency-Key: <uuid>
Content-Type: application/json

{ "title": "Write the TODO specification", "description": null }
```

**Rules**: `title` is **required**, non-empty.

**Response**  `201 Created` with card resource.

### Update a card

```
PATCH /v1/boards/{boardId}/columns/{columnId}/cards/{cardId}
Authorization: Bearer <JWT>
Content-Type: application/json

{ "title": "Polish the README", "description": "Add examples" }
```

**Response**  `200 OK` with updated resource.

### Move a card (within the same board)

```
POST /v1/boards/{boardId}/cards/{cardId}:move
Authorization: Bearer <JWT>
Content-Type: application/json

{ "toColumnId": "id-of-col-inprog", "toIndex": 0 }
```

**Rules**: `toColumnId` must belong to the same board. `toIndex` optional (append if omitted).

**Response**  `200 OK` with updated card (new `columnId`).

### Delete a card

```
DELETE /v1/boards/{boardId}/columns/{columnId}/cards/{cardId}
Authorization: Bearer <JWT>
```

**Response**  `204 No Content`.

----------

## Validation & error examples

### Empty title

```
POST /v1/boards/{b}/columns/{c}/cards
...
{ "title": "" }
```

**Response**  `422 Unprocessable Entity`

```
{ "error": { "code": "validation_error", "message": "title must not be empty", "details": {"title": "required_non_empty"}, "requestId": "..." } }
```

### Cross-board move rejected

```
POST /v1/boards/{boardA}/cards/{card}:move
...
{ "toColumnId": "column-from-board-B" }
```

**Response**  `409 Conflict`

```
{ "error": { "code": "invalid_move", "message": "Card can be moved only within the same board.", "requestId": "..." } }
```

----------

## Health & metadata

-   `GET /v1/health` → `200 OK`  `{ "status": "ok" }`
    
-   `GET /v1/version` → `200 OK`  `{ "version": "1.2.3" }`
    

----------

## Notes

-   All list endpoints are **strongly consistent**; writes are visible after success.    

-   New fields may appear in responses; clients should ignore unknown properties.

-   Soft delete is **not** supported; deletions are permanent.

