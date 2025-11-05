from datetime import UTC, datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

from slack_workflow_engine.home.filters import (  # noqa: E402
    HomeFilters,
    clamp_limit,
    clamp_offset,
    normalise_filters,
    validate_sort_field,
    validate_sort_order,
)


def test_clamp_limit_enforces_bounds():
    assert clamp_limit(None, default=10) == 10
    assert clamp_limit("5", default=10) == 5
    assert clamp_limit(-1, default=10) == 1
    assert clamp_limit(200, default=10, maximum=50) == 50


def test_clamp_offset_non_negative():
    assert clamp_offset(None) == 0
    assert clamp_offset("3") == 3
    assert clamp_offset(-5) == 0


def test_validate_sort_helpers_use_defaults():
    assert validate_sort_field("status") == "status"
    assert validate_sort_field("invalid") == "created_at"
    assert validate_sort_order("asc") == "asc"
    assert validate_sort_order(None) == "desc"


def test_normalise_filters_parses_sequences_and_dates():
    start = "2024-01-01T00:00:00+00:00"
    end = datetime(2024, 1, 31, tzinfo=UTC)

    filters = normalise_filters(
        workflow_types=[" refund ", ""],
        statuses=("pending", " "),
        start_at=start,
        end_at=end,
        sort_by="type",
        sort_order="asc",
        limit="25",
        offset="2",
        default_limit=10,
    )

    assert isinstance(filters, HomeFilters)
    assert filters.workflow_types == ["refund"]
    assert filters.statuses == ["pending"]
    assert filters.start_at == datetime(2024, 1, 1, tzinfo=UTC)
    assert filters.end_at == end
    assert filters.sort_by == "type"
    assert filters.sort_order == "asc"
    assert filters.limit == 25
    assert filters.offset == 2


def test_normalise_filters_defaults_when_invalid():
    filters = normalise_filters(
        sort_by="unknown",
        sort_order="invalid",
        limit="oops",
        offset="oops",
        default_limit=7,
    )

    assert filters.sort_by == "created_at"
    assert filters.sort_order == "desc"
    assert filters.limit == 7
    assert filters.offset == 0
