"""Phase 6 test utilities."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Optional, Sequence


class FakeDB:
    """Small in-memory DB double for Phase 6 unit tests."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, dict[str, Any]]] = []
        self.one_responses: dict[str, Mapping[str, Any] | None] = {}
        self.all_responses: dict[str, Sequence[Mapping[str, Any]]] = {}

    def set_one(self, marker: str, value: Mapping[str, Any] | None) -> None:
        self.one_responses[marker] = value

    def set_all(self, marker: str, value: Sequence[Mapping[str, Any]]) -> None:
        self.all_responses[marker] = value

    def fetch_one(self, sql: str, params: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
        for marker, value in self.one_responses.items():
            if marker in sql:
                return value
        rows = self.fetch_all(sql, params)
        return rows[0] if rows else None

    def fetch_all(self, sql: str, params: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        for marker, value in self.all_responses.items():
            if marker in sql:
                return list(value)
        return []

    def execute(self, sql: str, params: Mapping[str, Any]) -> None:
        self.executed.append((sql, dict(params)))
