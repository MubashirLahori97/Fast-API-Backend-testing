"""PreToolUse hook: stop Claude from editing files that must change some other way.

- .env (and .env.local etc.) holds passwords. Edit it yourself.
- uv.lock must only change through `uv add` / `uv remove` / `uv lock`.
- The user stories in docs/requirements/ are generated from the BA's Google Doc by
  scripts/sync_user_stories.py, so a hand edit would be overwritten on the next sync.
- A migration that's already pushed may have run on someone else's database. Changing it
  would leave their database different from the code; add a new migration instead.
  Migrations that are only local can still be edited or regenerated.
.env.example is allowed: it has no real secrets.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

GENERATED_STORIES = {
    "client-user-stories.md",
    "admin-user-stories.md",
    "super-admin-user-stories.md",
    "user-stories-export.md",
}


def block(message: str) -> None:
    # Exit code 2 blocks the edit; stderr tells Claude why.
    print(f"Blocked: {message}", file=sys.stderr)
    sys.exit(2)


def is_pushed(path: Path) -> bool:
    """True when a remote branch already has this file. Unsure (no git, no remote) is False,
    so the hook never gets in the way of local work."""
    project = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    try:
        result = subprocess.run(
            ["git", "-C", project, "log", "--remotes", "-1", "--format=%h", "--", str(path)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


data = json.load(sys.stdin)
path = Path(data.get("tool_input", {}).get("file_path", ""))
name = path.name
parts = [part.lower() for part in path.parts]

if name.startswith(".env") and name != ".env.example":
    block(f"don't edit {name} directly (it may hold secrets).")
if name in {"uv.lock", "package-lock.json"}:
    block(f"don't edit {name} directly (change it with uv or npm commands instead).")
if name in GENERATED_STORIES and "requirements" in parts:
    block(
        f"{name} is generated from the BA's Google Doc by scripts/sync_user_stories.py. "
        "Change the doc (or the script) and run the sync instead."
    )
if path.suffix == ".py" and "versions" in parts and "migrations" in parts and path.exists():
    if is_pushed(path):
        block(
            f"{name} is already pushed, so other databases may have run it. "
            "Add a new migration (/new-migration) instead of changing this one."
        )
