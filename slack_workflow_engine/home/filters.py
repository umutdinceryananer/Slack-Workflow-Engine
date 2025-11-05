"""Input validation helpers for App Home filters and sorting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable, Sequence


VALID_SORT_FIELDS = {"created_at", "status", "type"}
VALID_SORT_ORDERS = {"asc", "desc"}


def _clean_sequence(values: Sequence[str] | Iterable[str] | None) -> list[str] | None:
    if values is None:
        return None

    cleaned: list[str] = []
    for value in values:
        if value is None:
            continue
        item = str(value).strip()
        if item:
            cleaned.append(item)
    return cleaned or None


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    text = str(value).strip()
    if not text:
        return None

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


@dataclass(frozen=True)
class HomeFilters:
    workflow_types: list[str] | None
    statuses: list[str] | None
    start_at: datetime | None
    end_at: datetime | None
    sort_by: str
    sort_order: str
    limit: int
    offset: int


@dataclass(frozen=True)
class PaginationState:
    offset: int = 0
    limit: int = 10
    has_previous: bool = False
    has_more: bool = False


def clamp_limit(value: int | None, *, default: int, minimum: int = 1, maximum: int = 50) -> int:
    if value is None:
        return default

    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return default

    return max(minimum, min(maximum, numeric))


def clamp_offset(value: int | None) -> int:
    if value is None:
        return 0

    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return 0

    return max(0, numeric)


def validate_sort_field(value: str | None, *, default: str = "created_at") -> str:
    candidate = (value or "").strip().lower()
    if candidate in VALID_SORT_FIELDS:
        return candidate
    return default


def validate_sort_order(value: str | None, *, default: str = "desc") -> str:
    candidate = (value or "").strip().lower()
    if candidate in VALID_SORT_ORDERS:
        return candidate
    return default


def normalise_filters(
    *,
    workflow_types: Sequence[str] | Iterable[str] | None = None,
    statuses: Sequence[str] | Iterable[str] | None = None,
    start_at: str | datetime | None = None,
    end_at: str | datetime | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    default_limit: int = 10,
) -> HomeFilters:
    return HomeFilters(
        workflow_types=_clean_sequence(workflow_types),
        statuses=_clean_sequence(statuses),
        start_at=_parse_datetime(start_at),
        end_at=_parse_datetime(end_at),
        sort_by=validate_sort_field(sort_by),
        sort_order=validate_sort_order(sort_order, default="asc" if sort_by == "type" else "desc"),
        limit=clamp_limit(limit, default=default_limit),
        offset=clamp_offset(offset),
    )
