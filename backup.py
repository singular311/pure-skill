"""Create a named, permanent snapshot ("stable" tag) of the current site state.

This does NOT touch R2 — it only tags the current git commit (all files
under version control: website/, publish.py, workflows, etc). Use this right
after you've verified the live site works correctly, so you always have a
known-good point to roll back to with restore.py.

Usage:
    python backup.py "короткий опис чому це стабільна версія"
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent


def run(command: list[str]) -> None:
    print("+", " ".join(command))
    subprocess.run(command, check=True, cwd=PROJECT_DIR)


def main() -> None:
    message = sys.argv[1] if len(sys.argv) > 1 else "стабільна версія"
    tag = f"stable-{time.strftime('%Y%m%d-%H%M%S')}"

    run(["git", "add", "-A"])
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=PROJECT_DIR, check=False
    )
    if staged.returncode != 0:
        run(["git", "commit", "-m", f"Snapshot before tagging: {message}"])
        run(["git", "push"])

    run(["git", "tag", "-a", tag, "-m", message])
    run(["git", "push", "origin", tag])

    print()
    print(f"Готово. Створено стабільний знімок: {tag}")
    print(f"Щоб відновити цю версію пізніше: python restore.py {tag}")


if __name__ == "__main__":
    main()
