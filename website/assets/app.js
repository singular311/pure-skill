const config = window.SITE_CONFIG;
const data = window.CATALOG_DATA;
const lastUpdated = window.LAST_UPDATED || {};
const catalog = document.querySelector("#catalog");
const empty = document.querySelector("#empty");
const search = document.querySelector("#search");
const template = document.querySelector("#card-template");
document.title = config.name;
document.querySelector(".brand").textContent = config.name;
document.querySelector("#summary").textContent = `${data.titles.length} тайтлів · ${data.titles.reduce((sum, item) => sum + item.totalChapters, 0)} глав`;

const orderedTitles = data.titles.slice().sort((a, b) => {
  const diff = (lastUpdated[b.id] || 0) - (lastUpdated[a.id] || 0);
  if (diff !== 0) return diff;
  return a.title.localeCompare(b.title, "uk");
});

function pathUrl(relativePath) {
  return `${config.mediaBaseUrl.replace(/\/$/, "")}/${relativePath.split("/").map(encodeURIComponent).join("/")}`;
}
function render(query = "") {
  const normalized = query.trim().toLocaleLowerCase("uk");
  const visible = orderedTitles.filter(item => item.title.toLocaleLowerCase("uk").includes(normalized));
  catalog.replaceChildren();
  for (const item of visible) {
    const card = template.content.cloneNode(true);
    const link = card.querySelector(".card");
    link.href = `chapters.html?title=${encodeURIComponent(item.id)}`;
    const cover = card.querySelector(".cover");
    cover.src = pathUrl(config.localPreview ? item.localCoverPath : item.coverPath);
    cover.alt = `Обкладинка: ${item.title}`;
    card.querySelector("h2").textContent = item.title;
    card.querySelector(".chapter").textContent = `Остання глава: ${item.latestChapter}`;
    catalog.append(card);
  }
  empty.hidden = visible.length !== 0;
}
search.addEventListener("input", () => render(search.value));
render();
