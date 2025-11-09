"""Helpers for computing workflow approval state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence

from slack_workflow_engine.models import ApprovalDecision

from .models import WorkflowDefinition


@dataclass(frozen=True)
class LevelRuntime:
    status: str
    level: int | None
    total_levels: int
    quorum: int | None
    approvals: int
    rejections: int
    waiting_on: List[str]
    awaiting_tie_breaker: bool
    tie_breaker: str | None


def pending_status(level: int) -> str:
    return f"PENDING_L{max(level, 1)}"


def extract_level_from_status(status: str) -> int | None:
    if status == "PENDING":
        return 1

    if status.startswith("PENDING_L"):
        _, _, suffix = status.partition("_L")
        try:
            return int(suffix)
        except ValueError:
            return None

    return None


def is_pending_status(status: str) -> bool:
    return status.startswith("PENDING")


def derive_initial_status(definition: WorkflowDefinition) -> str:
    return pending_status(1) if definition.approvers.levels else "PENDING"


def _latest_decisions(decisions: Sequence[ApprovalDecision], level: int) -> dict[str, ApprovalDecision]:
    """Return the latest decision per user for *level* preserving overrides."""

    latest: dict[str, ApprovalDecision] = {}
    for decision in sorted(decisions, key=lambda item: item.decided_at):
        if decision.level != level:
            continue
        latest[decision.decided_by] = decision
    return latest


def compute_level_runtime(
    *,
    definition: WorkflowDefinition,
    status: str,
    decisions: Sequence[ApprovalDecision] | Iterable[ApprovalDecision],
) -> LevelRuntime:
    total_levels = len(definition.approvers.levels)
    level_index = extract_level_from_status(status)
    if not level_index or level_index < 1 or level_index > total_levels:
        return LevelRuntime(
            status=status,
            level=None,
            total_levels=total_levels,
            quorum=None,
            approvals=0,
            rejections=0,
            waiting_on=[],
            awaiting_tie_breaker=False,
            tie_breaker=None,
        )

    level_def = definition.approvers.levels[level_index - 1]
    quorum = level_def.quorum or len(level_def.members)
    member_order = list(dict.fromkeys(level_def.members))
    latest = _latest_decisions(list(decisions), level_index)
    approvals = sum(1 for decision in latest.values() if decision.decision == "APPROVED")
    rejections = sum(1 for decision in latest.values() if decision.decision == "REJECTED")
    waiting_on = [user for user in member_order if user not in latest]

    awaiting_tie_breaker = False
    tie_breaker = level_def.tie_breaker
    if not waiting_on and tie_breaker and approvals == rejections and approvals > 0:
        awaiting_tie_breaker = tie_breaker not in latest
        if awaiting_tie_breaker:
            waiting_on = [tie_breaker]

    return LevelRuntime(
        status=status,
        level=level_index,
        total_levels=total_levels,
        quorum=quorum,
        approvals=approvals,
        rejections=rejections,
        waiting_on=waiting_on,
        awaiting_tie_breaker=awaiting_tie_breaker,
        tie_breaker=tie_breaker,
    )


def format_status_text(runtime: LevelRuntime) -> str:
    label = runtime.status.replace("_", " ").title()
    if runtime.level is None or runtime.quorum is None:
        if runtime.waiting_on:
            waiting = ", ".join(f"<@{user}>" for user in runtime.waiting_on)
            return f"*Status:* {label} · Waiting on {waiting}."
        return f"*Status:* {label}"

    level_label = f"Level {runtime.level}/{max(runtime.total_levels, runtime.level)}"
    progress = f"{runtime.approvals}/{runtime.quorum} approvals"

    if runtime.awaiting_tie_breaker and runtime.tie_breaker:
        waiting_label = f"Awaiting tie-breaker <@{runtime.tie_breaker}>"
    elif runtime.waiting_on:
        waiting_label = "Waiting on " + ", ".join(f"<@{user}>" for user in runtime.waiting_on)
    else:
        waiting_label = "Waiting on next response"

    return f"*Status:* {label} ({level_label}) · {progress}. {waiting_label}."
