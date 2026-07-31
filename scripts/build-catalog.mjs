import fs from "node:fs/promises";
import path from "node:path";

const source = process.argv[2];
const output = process.argv[3] ?? path.resolve("website/data/catalog.js");

if (!source) {
  console.error("Використання: node scripts/build-catalog.mjs <папка_з_тайтлами> [вихідний_файл]");
  process.exit(1);
}

const ua = {
  а: "a", б: "b", в: "v", г: "h", ґ: "g", д: "d", е: "e", є: "ye", ж: "zh", з: "z", и: "y", і: "i", ї: "yi", й: "i", к: "k", л: "l", м: "m", н: "n", о: "o", п: "p", р: "r", с: "s", т: "t", у: "u", ф: "f", х: "kh", ц: "ts", ч: "ch", ш: "sh", щ: "shch", ь: "", ю: "yu", я: "ya"
};

function slugify(value) {
  return [...value.toLowerCase()].map(char => ua[char] ?? char).join("")
    .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "title";
}

function numericName(a, b) {
  return a.name.localeCompare(b.name, "uk", { numeric: true, sensitivity: "base" });
}

const entries = await fs.readdir(source, { withFileTypes: true });
const usedIds = new Set();
const titles = [];

for (const entry of entries.filter(item => item.isDirectory()).sort(numericName)) {
  const titlePath = path.join(source, entry.name);
  const coverPath = path.join(titlePath, "cover.webp");
  try { await fs.access(coverPath); } catch { console.warn(`Без cover.webp: ${entry.name}`); continue; }

  let id = slugify(entry.name);
  let index = 2;
  while (usedIds.has(id)) id = `${slugify(entry.name)}-${index++}`;
  usedIds.add(id);

  const chapters = (await fs.readdir(titlePath, { withFileTypes: true }))
    .filter(item => item.isDirectory())
    .sort(numericName);
  const chapterData = [];
  for (const chapter of chapters) {
    const chapterPath = path.join(titlePath, chapter.name);
    const pages = (await fs.readdir(chapterPath, { withFileTypes: true }))
      .filter(item => item.isFile() && item.name.toLowerCase().endsWith(".webp")).length;
    if (pages) chapterData.push({ number: chapter.name, pages });
  }
  if (!chapterData.length) continue;

  titles.push({
    id,
    title: entry.name,
    coverPath: `${id}/cover.webp`,
    localCoverPath: `${entry.name}/cover.webp`,
    chapters: chapterData,
    latestChapter: chapterData.at(-1).number,
    totalChapters: chapterData.length
  });
}

const payload = {
  generatedAt: new Date().toISOString(),
  titles
};
await fs.mkdir(path.dirname(output), { recursive: true });
await fs.writeFile(output, `window.CATALOG_DATA = ${JSON.stringify(payload, null, 2)};\n`, "utf8");
console.log(`Готово: ${titles.length} тайтлів → ${output}`);
