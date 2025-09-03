from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional

from pydantic import BaseModel, Field


# === Domain objects used by the in-memory store ===


@dataclass
class Column:
    id: str
    board_id: str
    name: str
    sort_key: str
    created_at: datetime
    updated_at: datetime
    version: int = 0


@dataclass
class Card:
    id: str
    board_id: str
    column_id: str
    title: str
    description: Optional[str]
    sort_key: str
    created_at: datetime
    updated_at: datetime
    version: int = 0


@dataclass
class Board:
    id: str
    name: str
    description: Optional[str]
    owner: str
    created_at: datetime
    updated_at: datetime
    version: int = 0
    members: Dict[str, str] = field(default_factory=dict)  # userId -> role
    columns: Dict[str, Column] = field(default_factory=dict)
    cards: Dict[str, Card] = field(default_factory=dict)


# === API Schemas ===


class BoardCreate(BaseModel):
    name: str = Field(min_length=1, max_length=140)
    description: Optional[str] = Field(default=None, max_length=2000)


class BoardUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=140)
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


class ColumnCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    beforeColumnId: Optional[str] = None
    afterColumnId: Optional[str] = None


class ColumnUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class ColumnMove(BaseModel):
    beforeColumnId: Optional[str] = None
    afterColumnId: Optional[str] = None


class ColumnOut(BaseModel):
    id: str
    boardId: str
    name: str
    sortKey: str
    createdAt: datetime
    updatedAt: datetime


class CardCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=8000)
    beforeCardId: Optional[str] = None
    afterCardId: Optional[str] = None


class CardUpdate(BaseModel):
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
