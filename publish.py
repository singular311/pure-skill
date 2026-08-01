"""Prepare and publish WebP pages to R2 through the Wrangler CLI.

The script is safe by default: it only reports pending changes. Add --publish
to upload changed images. It never deletes files from R2.
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
CATALOG = PROJECT_DIR / "website" / "data" / "catalog.js"
STATE_FILE = PROJECT_DIR / ".publish-state.json"
BUCKET = "manhwa-images"
DEFAULT_SOURCE_DIR = Path(r"D:\укр_webp")

PUBLIC_SITE = "https://pure-skill.pages.dev"
GITHUB_REPO = "singular311/pure-skill"
GITHUB_BRANCH = "main"
CUBARI_DIR = PROJECT_DIR / "website" / "cubari"
CUBARI_LINKS_FILE = PROJECT_DIR / "website" / "data" / "cubari-links.js"


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


def cubari_link(repo_path: str) -> str:
    """Build a cubari.moe /read/gist/ link for a file hosted in this GitHub repo."""
    raw = f"raw/{GITHUB_REPO}/{GITHUB_BRANCH}/{repo_path}"
    encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    encoded = encoded.replace("+", "-").replace("/", "_").rstrip("=")
    return f"https://cubari.moe/read/gist/{encoded}/"


def build_title_cubari_manifest(title: dict, source_dir: Path, confirmed_state: dict):
    """Write (or remove) the cubari manifest for a SINGLE title, based only on
    chapters whose every page is confirmed present in R2 (confirmed_state).
    Returns the cubari-links.js entry for this title, or None if not ready."""
    local_title = source_dir / title["localCoverPath"].split("/")[0]
    chapters_payload: dict[str, dict] = {}
    ready_chapters: list[str] = []

    for chapter in title["chapters"]:
        folder = local_title / chapter["number"]
        pages = sorted(folder.glob("*.webp"))
        keys = [
            f"titles/{title['id']}/chapters/{chapter['number']}/{p.name}"
            for p in pages
        ]
        if not pages or any(key not in confirmed_state for key in keys):
            continue  # глава ще не повністю в R2

        chapters_payload[str(chapter["number"])] = {
            "title": "",
            "volume": "",
            "groups": {"Sub": [f"{PUBLIC_SITE}/media/{key}" for key in keys]},
            "last_updated": str(int(time.time())),
        }
        ready_chapters.append(str(chapter["number"]))

    CUBARI_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = CUBARI_DIR / f"{title['id']}.json"

    if not chapters_payload:
        if manifest_path.exists():
            manifest_path.unlink()
        return None

    manifest = {
        "title": title["title"],
        "description": "",
        "artist": "",
        "author": "",
        "cover": f"{PUBLIC_SITE}/media/titles/{title['id']}/cover.webp",
        "chapters": chapters_payload,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "link": cubari_link(f"website/cubari/{title['id']}.json"),
        "chapters": ready_chapters,
    }


def load_cubari_links() -> dict:
    if not CUBARI_LINKS_FILE.exists():
        return {}
    prefix = "window.CUBARI_LINKS = "
    text = CUBARI_LINKS_FILE.read_text(encoding="utf-8").strip()
    if not text.startswith(prefix) or not text.endswith(";"):
        return {}
    return json.loads(text[len(prefix):-1])


def save_cubari_links(links: dict) -> None:
    CUBARI_LINKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CUBARI_LINKS_FILE.write_text(
        "window.CUBARI_LINKS = " + json.dumps(links, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )


def refresh_title_cubari_link(title: dict, source_dir: Path, confirmed_state: dict) -> None:
    """Update just this title's entry in cubari-links.js, leaving the rest untouched."""
    links = load_cubari_links()
    entry = build_title_cubari_manifest(title, source_dir, confirmed_state)
    if entry:
        links[title["id"]] = entry
    else:
        links.pop(title["id"], None)
    save_cubari_links(links)


def commit_and_push() -> bool:
    """Return True only after a successful commit and push to GitHub."""
    run(["git", "rev-parse", "--is-inside-work-tree"])
    run([
        "git", "add",
        "website/data/catalog.js",
        "website/data/config.js",
        "website/data/cubari-links.js",
        "website/cubari",
    ])
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=PROJECT_DIR, check=False
    )
    if staged.returncode == 0:
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
    changed_by_title: dict[str, list[tuple[Path, str]]] = {}
    total_changed = 0

    for source_file, key in iter_media(catalog, args.source):
        if not source_file.is_file():
            raise FileNotFoundError(source_file)
        signature = file_signature(source_file)
        new_state[key] = signature
        if old_state.get(key) != signature:
            title_id = key.split("/", 2)[1]
            changed_by_title.setdefault(title_id, []).append((source_file, key))
            total_changed += 1

    print(f"Тайтлів: {len(catalog['titles'])}; змінених або нових файлів: {total_changed}")

    if args.rebuild_state:
        STATE_FILE.write_text(
            json.dumps(new_state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Створено .publish-state.json ({len(new_state)} файлів)")
        return

    if not args.publish:
        print("Перевірка завершена. Для завантаження додай --publish.")
        return

    set_production_media_config()
    run(["git", "add", "website/data/config.js"])

    any_pushed = False
    for title in catalog["titles"]:
        title_changed = changed_by_title.get(title["id"], [])

        if title_changed:
            print(f"→ {title['id']}: завантажую {len(title_changed)} файл(ів)...")
            with ThreadPoolExecutor(max_workers=2) as pool:
                for key, signature in pool.map(
                    upload_file,
                    [
                        (source_file, key, args.wrangler, new_state[key])
                        for source_file, key in title_changed
                    ],
                ):
                    old_state[key] = signature
                    STATE_FILE.write_text(
                        json.dumps(old_state, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )

        # Оновлюємо cubari-посилання для ЦЬОГО тайтулу одразу — навіть якщо
        # для нього зараз не було нових файлів (могла довантажитись
        # остання сторінка останньої глави на попередньому кроці).
        refresh_title_cubari_link(title, args.source, old_state)
        if commit_and_push():
            any_pushed = True
            print(f"  ✓ {title['id']}: запушено, деплой запущено")

    STATE_FILE.write_text(json.dumps(new_state, ensure_ascii=False, indent=2), encoding="utf-8")
    if any_pushed:
        print("Готово. R2 оновлено, зміни пушились по кожному тайтулу окремо.")
        print("Перевіряйте статус деплоїв у GitHub Actions.")
    else:
        print("R2 оновлено. Жодних нових git-змін не було.")


if __name__ == "__main__":
    main()
