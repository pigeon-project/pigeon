from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./todo.db")


class Base(DeclarativeBase):
    pass


class Board(Base):
    __tablename__ = "boards"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(140))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    columns: Mapped[list[ColumnModel]] = relationship(
        back_populates="board", cascade="all, delete-orphan"
    )
    cards: Mapped[list[Card]] = relationship(
        back_populates="board", cascade="all, delete-orphan"
    )
    memberships: Mapped[list[BoardMembership]] = relationship(
        back_populates="board", cascade="all, delete-orphan"
    )


class ColumnModel(Base):
    __tablename__ = "columns"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    board_id: Mapped[str] = mapped_column(String(36), ForeignKey("boards.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(80))
    sort_key: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    board: Mapped[Board] = relationship(back_populates="columns")
    cards: Mapped[list[Card]] = relationship(
        back_populates="column", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("board_id", "sort_key", "id", name="uq_columns_order"),
    )


class Card(Base):
    __tablename__ = "cards"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    board_id: Mapped[str] = mapped_column(String(36), ForeignKey("boards.id", ondelete="CASCADE"))
    column_id: Mapped[str] = mapped_column(String(36), ForeignKey("columns.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_key: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    board: Mapped[Board] = relationship(back_populates="cards")
    column: Mapped[ColumnModel] = relationship(back_populates="cards")

    __table_args__ = (
        UniqueConstraint("board_id", "column_id", "sort_key", "id", name="uq_cards_order"),
    )


class BoardMembership(Base):
    __tablename__ = "board_memberships"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    board_id: Mapped[str] = mapped_column(String(36), ForeignKey("boards.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16))  # admin|writer|reader
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|pending
    invited_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    board: Mapped[Board] = relationship(back_populates="memberships")

    __table_args__ = (
        UniqueConstraint("board_id", "user_id", name="uq_member"),
    )


class Invitation(Base):
    __tablename__ = "invitations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    board_id: Mapped[str] = mapped_column(String(36), ForeignKey("boards.id", ondelete="CASCADE"))
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    role: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))  # pending|accepted|expired|revoked
    token_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
