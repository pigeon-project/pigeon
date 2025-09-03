from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .lexorank import midpoint
from .models import Board, Card, Column


class Storage:
    """In-memory store for boards, columns and cards."""

    def __init__(self) -> None:
        self.boards: Dict[str, Board] = {}

    # === Board operations ===
    def create_board(self, owner: str, name: str, description: Optional[str]) -> Board:
        now = datetime.now(timezone.utc)
        board = Board(
            id=str(uuid.uuid4()),
            name=name.strip(),
            description=description.strip() if description else None,
            owner=owner,
            created_at=now,
            updated_at=now,
            version=1,
            members={owner: "admin"},
        )
        self.boards[board.id] = board
        return board

    def list_boards_for_user(self, user_id: str) -> List[Board]:
        return [b for b in self.boards.values() if user_id in b.members]

    def get_board(self, board_id: str) -> Board:
        return self.boards[board_id]

    def delete_board(self, board_id: str) -> None:
        del self.boards[board_id]

    # === Column operations ===
    def create_column(
        self,
        board: Board,
        name: str,
        before_id: Optional[str],
        after_id: Optional[str],
    ) -> Column:
        now = datetime.now(timezone.utc)
        col_id = str(uuid.uuid4())
        columns = board.columns
        left = columns[before_id].sort_key if before_id else None
        right = columns[after_id].sort_key if after_id else None
        sort_key = midpoint(left, right)
        column = Column(
            id=col_id,
            board_id=board.id,
            name=name.strip(),
            sort_key=sort_key,
            created_at=now,
            updated_at=now,
            version=1,
        )
        columns[col_id] = column
        board.version += 1
        board.updated_at = now
        return column

    def move_column(
        self,
        board: Board,
        column: Column,
        before_id: Optional[str],
        after_id: Optional[str],
    ) -> Column:
        left = board.columns[before_id].sort_key if before_id else None
        right = board.columns[after_id].sort_key if after_id else None
        column.sort_key = midpoint(left, right)
        column.updated_at = datetime.now(timezone.utc)
        column.version += 1
        board.version += 1
        board.updated_at = column.updated_at
        return column

    # === Card operations ===
    def create_card(
        self,
        board: Board,
        column: Column,
        title: str,
        description: Optional[str],
        before_id: Optional[str],
        after_id: Optional[str],
    ) -> Card:
        now = datetime.now(timezone.utc)
        cards = [c for c in board.cards.values() if c.column_id == column.id]
        lookup = {c.id: c for c in cards}
        left = lookup[before_id].sort_key if before_id else None
        right = lookup[after_id].sort_key if after_id else None
        sort_key = midpoint(left, right)
        card = Card(
            id=str(uuid.uuid4()),
            board_id=board.id,
            column_id=column.id,
            title=title.strip(),
            description=description.strip() if description else None,
            sort_key=sort_key,
            created_at=now,
            updated_at=now,
            version=1,
        )
        board.cards[card.id] = card
        board.version += 1
        board.updated_at = now
        column.updated_at = now
        column.version += 1
        return card

    def move_card(
        self,
        board: Board,
        card: Card,
        to_column: Column,
        before_id: Optional[str],
        after_id: Optional[str],
    ) -> Card:
        cards_in_dest = [c for c in board.cards.values() if c.column_id == to_column.id]
        lookup = {c.id: c for c in cards_in_dest}
        left = lookup[before_id].sort_key if before_id else None
        right = lookup[after_id].sort_key if after_id else None
        card.sort_key = midpoint(left, right)
        card.column_id = to_column.id
        now = datetime.now(timezone.utc)
        card.updated_at = now
        card.version += 1
        board.version += 1
        board.updated_at = now
        return card

    def delete_column(self, board: Board, column_id: str) -> None:
        # remove column and its cards
        to_remove = [cid for cid, c in board.cards.items() if c.column_id == column_id]
        for cid in to_remove:
            del board.cards[cid]
        del board.columns[column_id]
        board.version += 1
        board.updated_at = datetime.now(timezone.utc)

    def delete_card(self, board: Board, card_id: str) -> None:
        del board.cards[card_id]
        board.version += 1
        board.updated_at = datetime.now(timezone.utc)


storage = Storage()
