"""Prepare and publish WebP pages to R2 through the Wrangler CLI.

The script is safe by default: it only reports pending changes. Add --publish
to upload changed images. It never deletes files from R2.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
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
LAST_UPDATED_FILE = PROJECT_DIR / "website" / "data" / "last-updated.js"


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

    CUBARI_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = CUBARI_DIR / f"{title['id']}.json"

    # Завантажуємо попередню версію маніфесту, щоб не змінювати last_updated
    # для розділів, які й так уже були готові й не змінювались — інакше
    # git бачив би "зміну" (лише через таймстамп) і комітив би тайтул
    # щоразу, навіть коли реально нічого нового не завантажилось.
    previous_chapters: dict = {}
    if manifest_path.exists():
        try:
            previous_chapters = json.loads(manifest_path.read_text(encoding="utf-8")).get("chapters", {})
        except (json.JSONDecodeError, OSError):
            previous_chapters = {}

    for chapter in title["chapters"]:
        folder = local_title / chapter["number"]
        pages = sorted(folder.glob("*.webp"))
        keys = [
            f"titles/{title['id']}/chapters/{chapter['number']}/{p.name}"
            for p in pages
        ]
        if not pages or any(key not in confirmed_state for key in keys):
            continue  # глава ще не повністю в R2

        urls = [f"{PUBLIC_SITE}/media/{key}" for key in keys]
        prev = previous_chapters.get(str(chapter["number"]))
        unchanged = prev is not None and prev.get("groups", {}).get("Sub") == urls
        last_updated = prev["last_updated"] if unchanged else str(int(time.time()))

        chapters_payload[str(chapter["number"])] = {
            "title": "",
            "volume": "",
            "groups": {"Sub": urls},
            "last_updated": last_updated,
        }
        ready_chapters.append(str(chapter["number"]))

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


def load_json_module(path: Path, var_name: str) -> dict:
    if not path.exists():
        return {}
    prefix = f"window.{var_name} = "
    text = path.read_text(encoding="utf-8").strip()
    if not text.startswith(prefix) or not text.endswith(";"):
        return {}
    return json.loads(text[len(prefix):-1])


def save_json_module(path: Path, var_name: str, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"window.{var_name} = " + json.dumps(data, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )


def refresh_title_cubari_link(title: dict, source_dir: Path, confirmed_state: dict) -> None:
    """Update just this title's entry in cubari-links.js, leaving the rest untouched."""
    links = load_json_module(CUBARI_LINKS_FILE, "CUBARI_LINKS")
    entry = build_title_cubari_manifest(title, source_dir, confirmed_state)
    if entry:
        links[title["id"]] = entry
    else:
        links.pop(title["id"], None)
    save_json_module(CUBARI_LINKS_FILE, "CUBARI_LINKS", links)


def mark_title_updated_now(title_id: str) -> None:
    """Record 'now' as the last-updated timestamp for a title, so the
    homepage can sort titles by most recently updated first."""
    updates = load_json_module(LAST_UPDATED_FILE, "LAST_UPDATED")
    updates[title_id] = int(time.time())
    save_json_module(LAST_UPDATED_FILE, "LAST_UPDATED", updates)


def get_r2_client():
    """R2 has no 'list objects' command in wrangler, so we talk to it via its
    S3-compatible API instead. Requires an R2 API token (separate from the
    normal `wrangler login`) — see README notes / chat instructions."""
    try:
        import boto3
    except ImportError:
        raise SystemExit(
            "Потрібна бібліотека boto3: встанови командою `pip install boto3`.\n"
            "Також мають бути задані змінні середовища R2_ACCOUNT_ID, "
            "R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY (Cloudflare Dashboard → R2 → "
            "Manage R2 API Tokens)."
        )

    account_id = os.environ.get("R2_ACCOUNT_ID")
    access_key = os.environ.get("R2_ACCESS_KEY_ID")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    if not all([account_id, access_key, secret_key]):
        raise SystemExit(
            "Не задані змінні середовища R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / "
            "R2_SECRET_ACCESS_KEY. Задай їх (наприклад через `setx` у Windows) "
            "і відкрий нове вікно терміналу."
        )

    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )


def list_all_r2_keys(client) -> dict[str, int]:
    """Return {key: size_in_bytes} for every object currently in the bucket."""
    keys: dict[str, int] = {}
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET):
        for obj in page.get("Contents", []):
            keys[obj["Key"]] = obj["Size"]
    return keys


def find_and_optionally_delete_orphans(expected_keys: set[str], delete: bool) -> None:
    """Report (and optionally delete) files that exist in R2 but are no
    longer expected locally — i.e. not present in the current new_state."""
    client = get_r2_client()
    print("Отримую список файлів у R2 (може зайняти хвилину для великого бакета)...")
    remote = list_all_r2_keys(client)
    orphan_keys = [key for key in remote if key not in expected_keys]

    if not orphan_keys:
        print(f"У R2 зараз {len(remote)} файл(ів). Зайвих не знайдено — усе синхронізовано.")
        return

    total_mb = sum(remote[key] for key in orphan_keys) / (1024 * 1024)
    print(f"У R2 зараз {len(remote)} файл(ів), локально очікується {len(expected_keys)}.")
    print(f"Зайвих файлів: {len(orphan_keys)}")
    print(f"Вони займають: {total_mb:.1f} МБ")

    if not delete:
        print("Запусти з --delete-orphans, щоб видалити їх (буде запитано підтвердження).")
        return

    confirm = input(
        f"Видалити {len(orphan_keys)} файл(ів) з R2 НАЗАВЖДИ? (так/ні): "
    ).strip().lower()
    if confirm not in ("так", "yes", "y"):
        print("Скасовано.")
        return

    for i in range(0, len(orphan_keys), 1000):  # S3 batch delete: max 1000/запит
        batch = orphan_keys[i:i + 1000]
        client.delete_objects(
            Bucket=BUCKET, Delete={"Objects": [{"Key": key} for key in batch]}
        )
        print(f"Видалено {min(i + 1000, len(orphan_keys))}/{len(orphan_keys)}...")

    print("Готово. Зайві файли видалено з R2.")


def commit_and_push() -> bool:
    """Return True only after a successful commit and push to GitHub.

    Stages the whole website/ directory (not a hand-picked file list) so any
    frontend edit — HTML, CSS, JS, data — is always included automatically.
    """
    run(["git", "rev-parse", "--is-inside-work-tree"])
    run(["git", "add", "website"])
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
    parser.add_argument(
        "--find-orphans",
        action="store_true",
        help="Показати файли, які є в R2, але вже не потрібні локально",
    )
    parser.add_argument(
        "--delete-orphans",
        action="store_true",
        help="Те саме, що --find-orphans, але з видаленням (після підтвердження)",
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

    any_pushed = False
    for title in catalog["titles"]:
        title_changed = changed_by_title.get(title["id"], [])

        if title_changed:
            print(f"→ {title['id']}: завантажую {len(title_changed)} файл(ів)...")
            with ThreadPoolExecutor(max_workers=8) as pool:
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
            mark_title_updated_now(title["id"])

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
