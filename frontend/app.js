// Newsfeed-PWA – Vanilla JS, kein Build-Schritt, keine Drittanbieter.
// Einstellungen liegen ausschließlich in localStorage dieses Geräts.
"use strict";

const SETTINGS_KEY = "newsfeed.settings.v1";
const PAGE_SIZE = 30;
const DEFAULT_SETTINGS = { images: false };

const $ = (sel) => document.querySelector(sel);
const tabsEl = $("#tabs");
const listEl = $("#articles");
const statusEl = $("#status");
const moreBtn = $("#more");
const tpl = $("#article-tpl");

const state = {
  topics: [],
  current: null,
  next: null,
  loading: false,
  requestId: 0,
  lastLoad: 0,
  settings: loadSettings(),
};

// ---------------------------------------------------------------- Settings
function loadSettings() {
  try {
    return { ...DEFAULT_SETTINGS, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}") };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

function saveSettings() {
  try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(state.settings)); } catch { /* privater Modus */ }
}

// ---------------------------------------------------------------- Helfer
const rtf = new Intl.RelativeTimeFormat("de", { numeric: "auto" });
const dtf = new Intl.DateTimeFormat("de", { dateStyle: "medium", timeStyle: "short" });

function relativeTime(ts) {
  const diff = ts - Date.now() / 1000;
  const abs = Math.abs(diff);
  if (abs < 60) return "gerade eben";
  if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
  return rtf.format(Math.round(diff / 86400), "day");
}

function isHttpUrl(url) {
  try { return ["http:", "https:"].includes(new URL(url).protocol); } catch { return false; }
}

function topicColor(id) { return `var(--t-${id}, var(--accent))`; }

function iconTopic(article) {
  if (state.current !== "top" && article.topics.includes(state.current)) return state.current;
  return article.topics.find((t) => t !== "top") || article.topics[0] || "top";
}

function showStatus(text, isError = false) {
  statusEl.hidden = !text;
  statusEl.textContent = text || "";
  statusEl.classList.toggle("error", isError);
}

// ---------------------------------------------------------------- Tabs
function renderTabs() {
  tabsEl.replaceChildren(...state.topics.map((t, i) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "tab";
    b.id = `tab-${t.id}`;
    b.setAttribute("role", "tab");
    b.setAttribute("aria-controls", "feed");
    b.dataset.topic = t.id;
    b.style.setProperty("--tc", topicColor(t.id));
    b.title = i < 9 ? `${t.name} (Taste ${i + 1})` : t.name;
    const dot = document.createElement("span");
    dot.className = "dot";
    const name = document.createElement("span");
    name.textContent = t.name;
    const count = document.createElement("span");
    count.className = "count";
    count.textContent = t.count_48h || "";
    count.setAttribute("aria-label", `${t.count_48h} Artikel in 48 Stunden`);
    b.append(dot, name, count);
    b.addEventListener("click", () => selectTopic(t.id));
    return b;
  }));
  updateTabSelection();
}

function updateTabSelection() {
  for (const b of tabsEl.children) {
    const selected = b.dataset.topic === state.current;
    b.setAttribute("aria-selected", String(selected));
    b.tabIndex = selected ? 0 : -1;
    if (selected) b.scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" });
  }
}

function moveTopic(delta) {
  const i = state.topics.findIndex((t) => t.id === state.current);
  const next = state.topics[(i + delta + state.topics.length) % state.topics.length];
  selectTopic(next.id);
  return next.id;
}

tabsEl.addEventListener("keydown", (e) => {
  const keys = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
  if (e.key in keys) {
    e.preventDefault();
    const id = moveTopic(keys[e.key]);
    document.getElementById(`tab-${id}`)?.focus();
  } else if (e.key === "Home" || e.key === "End") {
    e.preventDefault();
    const t = e.key === "Home" ? state.topics[0] : state.topics.at(-1);
    selectTopic(t.id);
    document.getElementById(`tab-${t.id}`)?.focus();
  }
});

function selectTopic(id) {
  if (id === state.current) return;
  history.replaceState(null, "", `#/${id}`);
  state.current = id;
  updateTabSelection();
  loadArticles({ reset: true });
}

// ---------------------------------------------------------------- Artikel
function renderArticle(a) {
  const node = tpl.content.firstElementChild.cloneNode(true);
  const link = node.querySelector(".card-link");
  if (isHttpUrl(a.url)) link.href = a.url;
  node.querySelector(".title").textContent = a.title;
  node.querySelector(".summary").textContent = a.summary;
  node.querySelector(".publisher").textContent = a.publisher;
  const time = node.querySelector("time");
  const date = new Date(a.published_at * 1000);
  time.dateTime = date.toISOString();
  time.textContent = relativeTime(a.published_at);
  time.title = dtf.format(date);

  const thumb = node.querySelector(".thumb");
  const topic = iconTopic(a);
  if (state.settings.images && a.image_url && isHttpUrl(a.image_url)) {
    const img = document.createElement("img");
    img.className = "photo";
    img.alt = "";
    img.loading = "lazy";
    img.decoding = "async";
    img.referrerPolicy = "no-referrer";
    img.addEventListener("error", () => setFallback(thumb, topic), { once: true });
    img.src = a.image_url;
    thumb.append(img);
  } else {
    setFallback(thumb, topic);
  }
  return node;
}

function setFallback(thumb, topic) {
  const img = document.createElement("img");
  img.src = `/icons/topics/${topic}.svg`;
  img.alt = "";
  thumb.replaceChildren(img);
  thumb.classList.add("fallback");
  thumb.style.setProperty("--tc", topicColor(topic));
}

function renderSkeleton() {
  listEl.replaceChildren(...Array.from({ length: 6 }, () => {
    const li = document.createElement("li");
    li.className = "card skeleton";
    li.innerHTML = '<div class="thumb fallback"></div><div class="card-body"><h3 class="title">&nbsp;</h3><p class="summary">&nbsp;<br>&nbsp;</p></div>';
    li.setAttribute("aria-hidden", "true");
    return li;
  }));
}

async function loadArticles({ reset = false } = {}) {
  if (!state.current) return;
  if (!reset && (state.loading || !state.next)) return;
  const requestId = ++state.requestId;
  state.loading = true;
  if (reset) {
    state.next = null;
    renderSkeleton();
    window.scrollTo({ top: 0 });
  }
  const params = new URLSearchParams({ topics: state.current, limit: PAGE_SIZE });
  if (!reset && state.next) params.set("before", state.next);

  try {
    const res = await fetch(`/api/articles?${params}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (requestId !== state.requestId) return; // Thema inzwischen gewechselt
    const nodes = data.items.map(renderArticle);
    if (reset) listEl.replaceChildren(...nodes); else listEl.append(...nodes);
    state.next = data.next;
    state.lastLoad = Date.now();
    if (res.headers.get("x-from-cache")) {
      showStatus("Offline – du siehst den zuletzt gespeicherten Stand.");
    } else if (reset && !data.items.length) {
      showStatus("Noch keine Artikel für dieses Thema. Der erste Abruf kann ein paar Minuten dauern.");
    } else {
      showStatus("");
    }
  } catch (err) {
    if (requestId !== state.requestId) return;
    if (reset) listEl.replaceChildren();
    showStatus(`Artikel konnten nicht geladen werden (${err.message}).`, true);
  } finally {
    if (requestId === state.requestId) {
      state.loading = false;
      moreBtn.hidden = !state.next;
    }
  }
}

// Endlos-Scrollen; der Button bleibt als Tastatur-/Fallback-Variante.
new IntersectionObserver((entries) => {
  if (entries.some((e) => e.isIntersecting)) loadArticles();
}, { rootMargin: "600px" }).observe($("#sentinel"));
moreBtn.addEventListener("click", () => loadArticles());

// ---------------------------------------------------------------- Laden/Refresh
async function loadTopics() {
  const res = await fetch("/api/topics");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  state.topics = await res.json();
}

async function refresh() {
  const btn = $("#refresh");
  btn.classList.add("spinning");
  try {
    await loadTopics();
    renderTabs();
  } catch { /* offline: Tabs bleiben */ }
  await loadArticles({ reset: true });
  btn.classList.remove("spinning");
}

$("#refresh").addEventListener("click", refresh);

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && Date.now() - state.lastLoad > 10 * 60 * 1000) refresh();
});

// ---------------------------------------------------------------- Wischen (Handy)
let touchStart = null;
const feedEl = $("#feed");
feedEl.addEventListener("touchstart", (e) => {
  if (e.touches.length === 1) touchStart = { x: e.touches[0].clientX, y: e.touches[0].clientY, t: Date.now() };
}, { passive: true });
feedEl.addEventListener("touchend", (e) => {
  if (!touchStart) return;
  const t = e.changedTouches[0];
  const dx = t.clientX - touchStart.x;
  const dy = t.clientY - touchStart.y;
  const fast = Date.now() - touchStart.t < 600;
  touchStart = null;
  if (fast && Math.abs(dx) > 70 && Math.abs(dx) > Math.abs(dy) * 1.8) moveTopic(dx < 0 ? 1 : -1);
}, { passive: true });

// ---------------------------------------------------------------- Tastatur
document.addEventListener("keydown", (e) => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if ($("#settings").open || e.target.closest("input, textarea, select, [role=tablist]")) return;
  if (/^[1-9]$/.test(e.key)) {
    const t = state.topics[Number(e.key) - 1];
    if (t) selectTopic(t.id);
  } else if (e.key === "j" || e.key === "k") {
    const cards = [...listEl.querySelectorAll(".card-link")];
    const i = cards.indexOf(document.activeElement);
    const next = cards[e.key === "j" ? Math.min(i + 1, cards.length - 1) : Math.max(i - 1, 0)];
    next?.focus();
    next?.scrollIntoView({ block: "center", behavior: "smooth" });
  } else if (e.key === "r") {
    refresh();
  } else if (e.key === "[" || e.key === "]") {
    moveTopic(e.key === "]" ? 1 : -1);
  }
});

// ---------------------------------------------------------------- Einstellungen
const settingsDlg = $("#settings");
const optImages = $("#opt-images");
$("#open-settings").addEventListener("click", () => {
  optImages.checked = state.settings.images;
  settingsDlg.showModal();
});
optImages.addEventListener("change", () => {
  state.settings.images = optImages.checked;
  saveSettings();
});
settingsDlg.addEventListener("close", () => loadArticles({ reset: true }));

// ---------------------------------------------------------------- Start
async function init() {
  try {
    await loadTopics();
  } catch (err) {
    showStatus(`Server nicht erreichbar (${err.message}).`, true);
    return;
  }
  renderTabs();
  const fromHash = location.hash.replace(/^#\//, "");
  const start = state.topics.find((t) => t.id === fromHash) || state.topics[0];
  state.current = null;
  selectTopic(start.id);
}

window.addEventListener("hashchange", () => {
  const id = location.hash.replace(/^#\//, "");
  if (state.topics.some((t) => t.id === id)) selectTopic(id);
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => { /* ohne SW weiterhin nutzbar */ });
}

init();
