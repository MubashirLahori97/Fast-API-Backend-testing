"""PostToolUse hook: lint-fix and format a Python file right after Claude edits it.

Claude Code sends details about the edit as JSON on stdin. We read the file path
from it and, if it's a .py file in this repo, run `ruff check --fix` and `ruff format`
on it. Problems ruff can't fix are reported back to Claude so it can fix them itself.
"""

import json
import os
import subprocess
import sys

data = json.load(sys.stdin)
path = data.get("tool_input", {}).get("file_path", "")


def inside(path: str, root: str) -> bool:
    path, root = (os.path.normcase(os.path.abspath(p)) for p in (path, root))
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:  # on different drives (Windows)
        return False


if not path.endswith(".py"):
    sys.exit(0)  # not Python: nothing to do
project = os.environ.get("CLAUDE_PROJECT_DIR")
if project and not inside(path, project):
    sys.exit(0)  # outside this repo, such as a scratch file: not ours to lint

ruff = [sys.executable, "-m", "ruff"]
# Fix first (e.g. remove unused imports), then format, so no stray blank lines remain.
result = subprocess.run(
    [*ruff, "check", "--fix", "--quiet", path], capture_output=True, text=True, check=False
)
subprocess.run([*ruff, "format", "--quiet", path], check=False)

if result.returncode != 0:
    # Exit code 2 sends stderr back to Claude as feedback on the edit.
    print(f"ruff found problems it couldn't fix in {path}:\n{result.stdout}", file=sys.stderr)
    sys.exit(2)
