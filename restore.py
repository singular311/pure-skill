"""Restore the site's git-tracked files to a previously created stable
snapshot (see backup.py).

This creates a NEW commit that makes the working tree match the tagged
snapshot, then pushes it — it does not rewrite git history, so it's always
safe and reversible (you can restore forward again just as easily).

Important: this only restores files tracked in git (website/, publish.py,
etc). It does NOT touch anything already uploaded to R2, and does NOT modify
.publish-state.json or website/data/last-updated.js retroactively beyond
what's in the snapshot — after restoring, a normal `python publish.py
--publish` run will simply pick up from wherever R2 actually is.

Usage:
    python restore.py                 # list available stable snapshots
    python restore.py <tag-name>      # restore to that snapshot
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent


def run(command: list[str], check: bool = True):
    print("+", " ".join(command))
    return subprocess.run(
        command, check=check, cwd=PROJECT_DIR, capture_output=True, text=True
    )


def list_tags() -> list[str]:
    result = run(["git", "tag", "--list", "stable-*", "--sort=-creatordate"])
    return [line for line in result.stdout.splitlines() if line.strip()]


def main() -> None:
    tags = list_tags()
    if not tags:
        print("Стабільних знімків ще немає. Спочатку створіть один: python backup.py")
        return

    if len(sys.argv) > 1:
        tag = sys.argv[1]
        if tag not in tags:
            print(f"Тег '{tag}' не знайдено.")
            print("Доступні знімки:")
            for t in tags:
                print(" -", t)
            return
    else:
        print("Доступні стабільні знімки (від найновішого):")
        for t in tags:
            print(" -", t)
        print()
        print("Запустіть знову з назвою знімка: python restore.py <tag>")
        return

    print()
    print(f"УВАГА: це поверне файли сайту до стану '{tag}' і задеплоїть це на прод.")
    print("R2 (завантажені картинки) це не торкнеться.")
    confirm = input("Продовжити? (так/ні): ").strip().lower()
    if confirm not in ("так", "yes", "y"):
        print("Скасовано.")
        return

    run(["git", "checkout", tag, "--", "."])
    run(["git", "add", "-A"])
    staged = run(["git", "diff", "--cached", "--quiet"], check=False)
    if staged.returncode == 0:
        print("Поточний стан уже ідентичний цьому знімку — коміт не потрібен.")
        return

    subprocess.run(
        ["git", "commit", "-m", f"Restore to stable snapshot {tag}"],
        check=True, cwd=PROJECT_DIR,
    )
    subprocess.run(["git", "push"], check=True, cwd=PROJECT_DIR)

    print()
    print(f"Готово. Сайт відновлено до '{tag}' і запушено — деплой запуститься автоматично.")


if __name__ == "__main__":
    main()
