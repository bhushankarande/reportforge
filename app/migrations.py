"""Migration stubs for the MVP SQLite schema."""

from app.database import init_db


def run_migrations() -> None:
    """Run MVP migrations by creating missing SQLite tables."""
    init_db()
