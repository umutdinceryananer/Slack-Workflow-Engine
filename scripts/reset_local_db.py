"""Utility script to reset the local SQLite database.

Usage:
    python scripts/reset_local_db.py

Environment:
    Ensure DATABASE_URL (and other required settings) are available in
    the current shell before running this script.
"""

from __future__ import annotations

from slack_workflow_engine.db import get_engine
from slack_workflow_engine.models import Base


def reset_database() -> None:
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    print("Local database reset.")


if __name__ == "__main__":
    reset_database()
