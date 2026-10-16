"use strict";
const state = {items: [], filter: "all", search: ""};
const $ = (id) => document.getElementById(id);
const make = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };
const assetURL = (record) => `${record.path}?v=${record.sha256.slice(0, 12)}`;
const groupAnchor = (i) => `${i.category}-${i.group_slug}`;
const familyName = (i) => i.group;

function openArt(item) {
  $("dialog-title").textContent = item.display_name;
  $("dialog-group").textContent = familyName(item);
  $("dialog-version").textContent = `${item.version} · ${item.preview.width} × ${item.preview.height} PNG`;
  $("dialog-image").src = assetURL(item.preview);
  $("dialog-image").alt = item.display_name;
  $("dialog-image").width = item.preview.width;
  $("dialog-image").height = item.preview.height;
  $("open-image").href = assetURL(item.preview);
  $("art-dialog").showModal();
}

function imageButton(item, hero = false) {
  const button = make("button", hero ? "" : "art-card");
  button.type = "button";
  button.setAttribute("aria-label", `View ${item.display_name}`);
  const image = make("img"); image.src = assetURL(item.preview); image.alt = item.display_name;
  image.width = item.preview.width; image.height = item.preview.height;
  image.loading = hero ? "eager" : "lazy"; image.decoding = "async";
  if (hero) button.append(image);
  else {
    const tile = make("span", "art-tile"); tile.append(image); button.append(tile);
    const label = make("span", "art-label", item.display_name);
    label.append(make("small", "", item.kind === "icon" && item.category === "resources" && item.item_order === 0 ? "PARENT RESOURCE" : item.category === "currencies" ? "CURRENCY & VALUABLES" : item.version));
    button.append(label);
  }
  button.addEventListener("click", () => openArt(item));
  return button;
}

function render() {
  const query = state.search.trim().toLocaleLowerCase();
  const items = state.items.filter(i => (state.filter === "all" || (state.filter === "artwork" ? i.kind !== "icon" : i.category === state.filter)) && (!query || `${i.name} ${i.display_name} ${i.group}`.toLocaleLowerCase().includes(query)));
  const groups = new Map();
  for (const i of items) { const key = groupAnchor(i); if (!groups.has(key)) groups.set(key, []); groups.get(key).push(i); }
  const gallery = document.createDocumentFragment();
  const nav = document.createDocumentFragment();
  for (const [key, members] of groups) {
    const first = members[0];
    const section = make("section", "family-section"); section.id = key;
    const heading = make("div", "family-heading");
    const title = make("h3"); title.append(make("span", "", first.category === "currencies" ? `C${first.group_order - 27}` : String(first.group_order).padStart(2, "0")), document.createTextNode(familyName(first)));
    heading.append(title, make("span", "", `${members.length} ${members.length === 1 ? "artwork" : "artworks"}`));
    const grid = make("div", "icon-grid");
    for (const i of members) grid.append(imageButton(i));
    section.append(heading, grid); gallery.append(section);
    const link = make("a"); link.href = `#${key}`; link.append(make("span", "number", String(first.group_order).padStart(2, "0")), document.createTextNode(familyName(first))); nav.append(link);
  }
  $("gallery").replaceChildren(gallery); $("family-nav").replaceChildren(nav);
  $("empty").hidden = items.length !== 0;
  $("result-count").textContent = `${items.length} of ${state.items.length} artworks · ${groups.size} collections`;
}

$("search").addEventListener("input", (event) => { state.search = event.target.value; render(); });
document.querySelectorAll("[data-filter]").forEach(button => button.addEventListener("click", () => {
  state.filter = button.dataset.filter;
  document.querySelectorAll("[data-filter]").forEach(b => { b.classList.toggle("active", b === button); b.setAttribute("aria-pressed", String(b === button)); });
  render();
}));
$("theme-toggle").addEventListener("click", () => {
  const light = document.documentElement.dataset.theme !== "light";
  document.documentElement.dataset.theme = light ? "light" : "dark";
  $("theme-toggle").textContent = light ? "Dark background" : "Light background";
  $("theme-toggle").setAttribute("aria-label", light ? "Switch to dark background" : "Switch to light background");
});
document.querySelectorAll("[data-background]").forEach(button => button.addEventListener("click", () => {
  $("preview-canvas").dataset.background = button.dataset.background;
  document.querySelectorAll("[data-background]").forEach(b => b.setAttribute("aria-pressed", String(b === button)));
}));
$("art-dialog").addEventListener("click", (event) => { if (event.target === $("art-dialog")) { const r = event.target.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) event.target.close(); } });

async function start() {
  try {
    const response = await fetch(document.body.dataset.catalog, {credentials: "omit"});
    if (!response.ok) throw new Error("Catalog unavailable");
    const catalog = await response.json();
    state.items = catalog.items;
    $("other-filter").hidden = !state.items.some(i => i.kind !== "icon");
    const resources = new Set(state.items.filter(i => i.category === "resources").map(groupAnchor));
    const currencies = new Set(state.items.filter(i => i.category === "currencies").map(groupAnchor));
    $("stats").replaceChildren();
    for (const [number, label] of [[state.items.length, "artworks"], [resources.size, "resource families"], [currencies.size, "currency groups"]]) {
      const span = make("span"); span.append(make("strong", "", String(number)), document.createTextNode(label)); $("stats").append(span);
    }
    $("stats").append(make("span", "stat-note", "Selected artwork · transparent previews"));
    const favorites = ["RES_WOOD", "RES_REMAINS", "RES_CUT_DIAMOND", "RES_RESIN", "RES_SHARDS", "RES_PROMISSORY_NOTE"];
    const hero = favorites.map(id => state.items.find(i => i.id === id)).filter(Boolean);
    for (const item of hero) $("hero-art").append(imageButton(item, true));
    render();
  } catch (error) {
    $("gallery").replaceChildren(make("p", "error", "The collection could not be loaded. Please try again or use the GitHub gallery."));
    $("result-count").textContent = "Collection unavailable";
  }
}
start();
