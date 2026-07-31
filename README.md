# Каталог манхви

## Оновлення локальних даних

Після додавання нових глав або обкладинок виконай у PowerShell з цієї папки:

```powershell
node .\scripts\build-catalog.mjs 'D:\укр_webp' .\website\data\catalog.js
```

Обкладинка кожного тайтлу має називатися `cover.webp` і лежати поруч із папками глав.

## Що вже готово

- адаптивний каталог із пошуком;
- 25 тайтлів автоматично беруться з локальної структури;
- сторінка списку глав;
- дані не прив'язані до майбутнього R2.

Поки `localPreview` у `website/data/config.js` має значення `true`, обкладинки беруться просто з `D:\укр_webp`. Після перенесення медіа у R2 він буде вимкнений.

## Наступний етап

Cloudflare Pages (`pure-skill`) і R2 налаштовані у `wrangler.jsonc`. Папка `functions/media/` — це Pages Function, а не окремий Worker: вона безпечно віддає картинки з приватного bucket `manhwa-images` через `/media/...`.

## Публікація в R2

`publish.py` спершу тільки покаже зміни:

```powershell
python .\publish.py 'D:\укр_webp' --node 'C:\Users\slavu\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' --wrangler 'C:\Users\slavu\AppData\Roaming\npm\wrangler.cmd'
```

Для фактичного завантаження додай `--publish`. Скрипт завантажує лише нові або змінені WebP, оновлює каталог і не видаляє файли з R2. Потім він сам створює Git-коміт та робить `git push`; цей push запускає Pages-деплой у GitHub Actions. Якщо каталог не змінився, коміт і деплой не виконуються. Якщо `git push` завершується помилкою, стан локальної публікації не зберігається, тому наступний запуск безпечно повторить синхронізацію.

`publish.py` може підтвердити успіх R2 і Git push, але не може передчасно підтвердити результат асинхронного GitHub Actions. Якщо Pages-деплой зламається, workflow завершиться помилкою, а скрипт не надрукує повідомлення про успішну публікацію сайту.

## Автодеплой

У `.github/workflows/deploy-pages.yml` є GitHub Actions workflow. Після додавання проєкту у потрібний GitHub-репозиторій треба створити його secrets `CLOUDFLARE_API_TOKEN` і `CLOUDFLARE_ACCOUNT_ID`; кожен push у `main` запустить Wrangler і опублікує Pages. Після початкового налаштування публікація нової глави потребує однієї команди `publish.py --publish`.
