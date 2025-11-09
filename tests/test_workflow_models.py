from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

from slack_workflow_engine.workflows.models import ApproverConfig  # noqa: E402


def test_approver_config_accepts_legacy_list() -> None:
    config = ApproverConfig.model_validate(["U1", "U2"])

    assert config.strategy == "sequential"
    assert [config.levels[0].members, config.levels[0].quorum] == [["U1", "U2"], 2]


def test_approver_config_accepts_members_alias() -> None:
    config = ApproverConfig.model_validate({"members": ["U1"], "strategy": "parallel"})

    assert config.strategy == "parallel"
    assert config.levels[0].members == ["U1"]
    assert config.levels[0].quorum == 1


def test_approver_config_rejects_duplicate_ids() -> None:
    with pytest.raises(ValueError):
        ApproverConfig(strategy="parallel", levels=[["U1", "U1"]])


def test_approver_config_requires_levels() -> None:
    with pytest.raises(ValueError):
        ApproverConfig(strategy="sequential", levels=[])
