"""Small compatibility boundary for the reused B4 store, not the rc.5 engine."""
from datetime import datetime, timezone


class Rejected(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()
