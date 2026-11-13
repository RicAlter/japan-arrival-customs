"""Portable WorkBuddy entrypoint; no workspace absolute paths."""
from arrival_core.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
