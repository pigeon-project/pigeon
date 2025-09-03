from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ErrorEnvelope(BaseModel):
    code: str
    message: str
    details: Optional[dict[str, Any]] = None
    requestId: Optional[str] = None


class Health(BaseModel):
    status: str = "ok"


class Version(BaseModel):
    version: str = "1.0.0"


class UserSummary(BaseModel):
    id: str
    displayName: str
    avatarUrl: Optional[str] = None


class BoardIn(BaseModel):
    name: str = Field(min_length=1, max_length=140)
    description: Optional[str] = Field(default=None, max_length=2000)


class BoardOut(BaseModel):
    id: str
    name: str
    description: Optional[str]
    owner: str
    createdAt: datetime
    updatedAt: datetime
    myRole: str
    membersCount: int


class BoardsPage(BaseModel):
    boards: list[BoardOut]
    nextCursor: Optional[str] = None


class ColumnIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    beforeColumnId: Optional[str] = None
    afterColumnId: Optional[str] = None


class ColumnPatch(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class ColumnOut(BaseModel):
    id: str
    boardId: str
    name: str
    sortKey: str
    createdAt: datetime
    updatedAt: datetime


class CardIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=8000)
    beforeCardId: Optional[str] = None
    afterCardId: Optional[str] = None


class CardPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=8000)


class CardMove(BaseModel):
    toColumnId: Optional[str] = None
    beforeCardId: Optional[str] = None
    afterCardId: Optional[str] = None
    expectedVersion: Optional[int] = None


class CardOut(BaseModel):
    id: str
    boardId: str
    columnId: str
    title: str
    description: Optional[str]
    sortKey: str
    createdAt: datetime
    updatedAt: datetime
    version: int


class BoardView(BaseModel):
    board: BoardOut
    columns: list[ColumnOut]
    cards: list[CardOut]


class MemberIn(BaseModel):
    email: Optional[str] = None
    userId: Optional[str] = None
    role: str


class MemberPatch(BaseModel):
    role: str


class MemberOut(BaseModel):
    boardId: str
    userId: str
    role: str
    status: str
    invitedBy: Optional[str]
    createdAt: datetime
    updatedAt: datetime
    user: UserSummary


class InvitationOut(BaseModel):
    id: str
    boardId: str
    email: Optional[str]
    role: str
    status: str
    token: Optional[str] = None


class InvitationAccept(BaseModel):
    token: str
