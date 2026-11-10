"""Turn the BA's Google Doc export into the Markdown files in docs/requirements/.

Usage: uv run python scripts/sync_user_stories.py <export.txt>

<export.txt> is the Google Doc's text as the Google Drive connector returns it
(the "fileContent" value). The script writes:

- docs/requirements/source/user-stories-export.md: the whole export as-is, so
  `git diff` shows exactly what the BA changed since the last sync.
- docs/requirements/client-user-stories.md, super-admin-user-stories.md and
  admin-user-stories.md: those sections, cleaned up.

To rebuild the cleaned files from the export already in the repo:
uv run python scripts/sync_user_stories.py docs/requirements/source/user-stories-export.md
"""

import re
import sys
from pathlib import Path

DOC_URL = "https://docs.google.com/document/d/1u94uQ0yDgEwk5TF1tu9VB97aF9NtCG7pdAm-MYp9NVs/edit"
REQUIREMENTS = Path(__file__).resolve().parent.parent / "docs" / "requirements"

SECTIONS = {
    "Client": "client-user-stories.md",
    "Super Admin": "super-admin-user-stories.md",
    "Admin": "admin-user-stories.md",
}
# Only the Client stories are being built (docs/PLAN.md).
SCOPE = {
    "Client": "In scope for the backend: the build order and decisions are in `docs/PLAN.md`.",
    "Super Admin": "Out of scope for the backend for now (see `docs/PLAN.md`).",
    "Admin": "Out of scope for the backend for now (see `docs/PLAN.md`).",
}


def split_sections(text: str) -> dict[str, list[str]]:
    """Group lines under each top-level `# Heading`."""
    sections: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("# "):
            current = line[2:].strip()
            sections[current] = []
        elif current:
            sections[current].append(line)
    return sections


def clean(lines: list[str]) -> list[str]:
    out = []
    for line in lines:
        if not line.strip() or line.strip() in ("-----", "<!-- end list -->"):
            continue
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        text = stripped.replace("*", "").replace("\\", "").rstrip()
        if text.startswith("#"):
            hashes, _, title = text.partition(" ")
            if not title.strip():
                continue  # a heading left empty by the export, e.g. "### **"
            out.append(f"{hashes} {title.strip()}")
        elif text.startswith("- "):
            level = max(0, (indent - 2) // 4)
            out.append("  " * level + text)
        else:
            out.append(text.strip())
    return out


def main() -> None:
    export = Path(sys.argv[1]).read_text(encoding="utf-8")
    source = REQUIREMENTS / "source" / "user-stories-export.md"
    source.parent.mkdir(exist_ok=True)
    source.write_text(export, encoding="utf-8")

    sections = split_sections(export)
    for name, filename in SECTIONS.items():
        if name not in sections:
            sys.exit(f"Section '# {name}' not found in the export")
        header = [
            f"# {name} user stories",
            "",
            f"{name} section of *Genesis Health/The Oracle - User Stories* (BA: Atiya Abid), "
            f"synced from {DOC_URL} by "
            "`scripts/sync_user_stories.py`. Do not edit by hand: changes are overwritten "
            f"on the next sync. {SCOPE[name]}",
            "",
            "",
        ]
        body = re.sub(r"\n{3,}", "\n\n", "\n".join(clean(sections[name])))
        (REQUIREMENTS / filename).write_text("\n".join(header) + body + "\n", encoding="utf-8")
        print(f"wrote {filename}")
    print(f"wrote {source.relative_to(REQUIREMENTS.parent.parent)}")


if __name__ == "__main__":
    main()
