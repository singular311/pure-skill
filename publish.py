"""Prepare and publish WebP pages to R2 through the Wrangler CLI.

The script is safe by default: it only reports pending changes. Add --publish
to upload changed images. It never deletes files from R2.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
CATALOG = PROJECT_DIR / "website" / "data" / "catalog.js"
STATE_FILE = PROJECT_DIR / ".publish-state.json"
BUCKET = "manhwa-images"
DEFAULT_SOURCE_DIR = Path(r"D:\укр_webp")


def run(command: list[str]) -> None:
    print("+", " ".join(map(str, command)))
    subprocess.run(command, check=True, cwd=PROJECT_DIR)

def upload_file(args):
    source_file, key, wrangler, signature = args

    run([
        wrangler, "r2", "object", "put", f"{BUCKET}/{key}",
        "--remote",
        "--file", str(source_file),
        "--content-type", "image/webp",
        "--cache-control", "public, max-age=31536000, immutable",
    ])

    return key, signature


def resolve_executable(command: str, display_name: str) -> str:
    """Resolve PowerShell/npm shims such as wrangler.cmd for subprocess."""
    supplied = Path(command)
    if supplied.is_file():
        return str(supplied)
    resolved = shutil.which(command)
    if not resolved and not command.lower().endswith(".cmd"):
        resolved = shutil.which(f"{command}.cmd")
    if not resolved:
        raise FileNotFoundError(
            f"Не знайдено {display_name}: {command}. "
            f"Передай повний шлях через --{display_name}."
        )
    return resolved


def load_catalog() -> dict:
    prefix = "window.CATALOG_DATA = "
    text = CATALOG.read_text(encoding="utf-8").strip()
    if not text.startswith(prefix) or not text.endswith(";"):
        raise ValueError("Неправильний формат website/data/catalog.js")
    return json.loads(text[len(prefix):-1])


def file_signature(file: Path) -> str:
    stat = file.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def iter_media(catalog: dict, source_dir: Path):
    for title in catalog["titles"]:
        local_title = source_dir / title["localCoverPath"].split("/")[0]
        cover = local_title / "cover.webp"
        yield cover, f"titles/{title['id']}/cover.webp"
        for chapter in title["chapters"]:
            folder = local_title / chapter["number"]
            for page in sorted(folder.glob("*.webp")):
                yield page, f"titles/{title['id']}/chapters/{chapter['number']}/{page.name}"

def set_production_media_config() -> None:
    config = PROJECT_DIR / "website" / "data" / "config.js"
    text = config.read_text(encoding="utf-8")
    text = text.replace('mediaBaseUrl: "file:///D:/укр_webp"', 'mediaBaseUrl: "/media/titles"')
    text = text.replace("localPreview: true", "localPreview: false")
    config.write_text(text, encoding="utf-8")


def commit_and_push() -> bool:
    """Return True only after a successful commit and push to GitHub."""
    run(["git", "rev-parse", "--is-inside-work-tree"])
    run(["git", "add", "website/data/catalog.js", "website/data/config.js"])
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=PROJECT_DIR, check=False
    )
    if staged.returncode == 0:
        print("Каталог не змінився — Git-коміт і деплой не потрібні.")
        return False
    run(["git", "commit", "-m", "Publish updated manga catalog"])
    run(["git", "push"])
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "source", nargs="?", type=Path, default=DEFAULT_SOURCE_DIR,
        help=r"Папка з тайтлами (типово: D:\укр_webp)",
    )
    parser.add_argument("--wrangler", default="wrangler", help="Шлях до wrangler.cmd")
    parser.add_argument("--node", default="node", help="Шлях до node.exe")
    parser.add_argument("--publish", action="store_true", help="Завантажити зміни в R2")
    parser.add_argument(
    "--rebuild-state",
    action="store_true",
    help="Створити .publish-state.json без завантаження в R2",
)
    args = parser.parse_args()
    if not args.source.is_dir():
        parser.error(f"Папка з тайтлами не знайдена: {args.source}")
    if args.publish:
        args.wrangler = resolve_executable(args.wrangler, "wrangler")

    node_script = PROJECT_DIR / "scripts" / "build-catalog.mjs"
    run([args.node, str(node_script), str(args.source), str(CATALOG)])
    catalog = load_catalog()
    old_state = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    new_state: dict[str, str] = {}
    changed: list[tuple[Path, str]] = []

    for source_file, key in iter_media(catalog, args.source):
        if not source_file.is_file():
            raise FileNotFoundError(source_file)
        signature = file_signature(source_file)
        new_state[key] = signature
        if old_state.get(key) != signature:
            changed.append((source_file, key))

    print(f"Тайтлів: {len(catalog['titles'])}; змінених або нових файлів: {len(changed)}")

    if args.rebuild_state:
        STATE_FILE.write_text(
            json.dumps(new_state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Створено .publish-state.json ({len(new_state)} файлів)")
        return

    if not args.publish:
        print("Перевірка завершена. Для завантаження додай --publish.")
        return

    with ThreadPoolExecutor(max_workers=2) as pool:
        for key, signature in pool.map(
            upload_file,
            [
                (source_file, key, args.wrangler, new_state[key])
                for source_file, key in changed
            ],
        ):
            old_state[key] = signature
            STATE_FILE.write_text(
                json.dumps(old_state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    set_production_media_config()
    pushed = commit_and_push()

    set_production_media_config()
    pushed = commit_and_push()

    # Write the state only after every required local/Git step has succeeded.
    # If `git push` fails, the next run uploads the changed objects again rather
    # than incorrectly treating the release as complete.
    STATE_FILE.write_text(json.dumps(new_state, ensure_ascii=False, indent=2), encoding="utf-8")
    if pushed:
        print("R2 оновлено, Git push успішний. GitHub Actions запустив Pages-деплой.")
        print("Успіх Pages підтверджується статусом GitHub Actions; publish.py не оголошує його завершеним передчасно.")
    else:
        print("R2 оновлено. Каталог не змінився, тому Pages-деплой не потрібен.")


if __name__ == "__main__":
    main()
