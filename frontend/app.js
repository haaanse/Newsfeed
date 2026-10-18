// Newsfeed-PWA – Vanilla JS, kein Build-Schritt, keine Drittanbieter.
// Alle Einstellungen liegen ausschließlich in localStorage dieses Geräts.
"use strict";

const SETTINGS_KEY = "newsfeed.settings.v2";
const PAGE_SIZE = 30;
const MIX = "mix";
const REGIONAL = "regional";
const DEFAULT_SETTINGS = {
  images: false,
  overview: true,
  compact: false,
  sort: "top",
  hidden: [],
  mix: ["top", "politik", "wirtschaft", "tech", "ki", "wissenschaft"],
  land: null,
  kreis: null,
  onlyLocal: false,
  blocked: [],
};

const $ = (sel) => document.querySelector(sel);
const tabsEl = $("#tabs");
const listEl = $("#articles");
const statusEl = $("#status");
const moreBtn = $("#more");
const sentinelEl = $("#sentinel");
const tpl = $("#story-tpl");

const state = {
  topics: [],          // vom Server
  views: [],           // sichtbare Tabs (inkl. "Mein Feed")
  current: null,
  nextOffset: null,
  seen: new Set(),
  loading: false,
  requestId: 0,
  lastLoad: 0,
  pendingRetries: 0,
  regions: null,
  settings: loadSettings(),
};

// ---------------------------------------------------------------- Einstellungen
function loadSettings() {
  try {
    const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}");
    // Bilder-Einstellung aus dem MVP übernehmen
    const v1 = JSON.parse(localStorage.getItem("newsfeed.settings.v1") || "{}");
    return { ...DEFAULT_SETTINGS, ...(typeof v1.images === "boolean" ? { images: v1.images } : {}), ...saved };
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

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.className = v;
    else if (k === "dataset") Object.assign(node.dataset, v);
    else if (k in node) node[k] = v;
    else node.setAttribute(k, v);
  }
  node.append(...children.filter((c) => c != null));
  return node;
}

const topicColor = (id) => `var(--t-${id}, var(--accent))`;
const topicName = (id) => state.topics.find((t) => t.id === id)?.name || id;

function showStatus(content, kind = "") {
  statusEl.hidden = !content;
  statusEl.className = `status ${kind}`;
  statusEl.replaceChildren(...(content ? [].concat(content) : []));
}

function kreisName() {
  const land = state.regions?.laender.find((l) => l.id === state.settings.land);
  if (!land) return null;
  return land.kreise.find((k) => k.id === state.settings.kreis)?.name || land.name;
}

// ---------------------------------------------------------------- Ansichten / Tabs
function buildViews() {
  const hidden = new Set(state.settings.hidden);
  const topics = state.topics.filter((t) => !hidden.has(t.id));
  state.views = [{ id: MIX, name: "Mein Feed", count_48h: null }, ...topics];
}

function renderTabs() {
  buildViews();
  tabsEl.replaceChildren(...state.views.map((v, i) => {
    const label = v.id === REGIONAL && state.settings.land ? el("span", { class: "sub" }, kreisName() || "") : null;
    const b = el("button", {
      type: "button", class: "tab", id: `tab-${v.id}`, role: "tab", title: i < 9 ? `${v.name} (Taste ${i + 1})` : v.name,
      dataset: { topic: v.id },
    },
    el("span", { class: v.id === MIX ? "dot mix" : "dot" }),
    el("span", { class: "label" }, el("span", {}, v.name), label),
    v.count_48h ? el("span", { class: "count", "aria-label": `${v.count_48h} Artikel in 48 Stunden` }, String(v.count_48h)) : null);
    b.setAttribute("aria-controls", "feed");
    b.style.setProperty("--tc", v.id === MIX ? "var(--accent)" : topicColor(v.id));
    b.addEventListener("click", () => selectView(v.id));
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
  for (const b of document.querySelectorAll(".sort-btn")) {
    b.setAttribute("aria-pressed", String(b.dataset.sort === state.settings.sort));
  }
}

function moveView(delta) {
  const i = state.views.findIndex((v) => v.id === state.current);
  const next = state.views[(i + delta + state.views.length) % state.views.length];
  selectView(next.id);
  return next.id;
}

tabsEl.addEventListener("keydown", (e) => {
  const keys = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
  let id = null;
  if (e.key in keys) id = moveView(keys[e.key]);
  else if (e.key === "Home") { id = state.views[0].id; selectView(id); }
  else if (e.key === "End") { id = state.views.at(-1).id; selectView(id); }
  if (id) {
    e.preventDefault();
    document.getElementById(`tab-${id}`)?.focus();
  }
});

function selectView(id, { force = false } = {}) {
  if (id === state.current && !force) return;
  if (!state.views.some((v) => v.id === id)) id = state.views[0].id;
  history.replaceState(null, "", `#/${id}`);
  state.current = id;
  document.body.classList.toggle("compact", state.settings.compact);
  updateTabSelection();
  loadStories({ reset: true });
}

// ---------------------------------------------------------------- Filter (nur lokal)
function mixTopics() {
  const hidden = new Set(state.settings.hidden);
  return state.settings.mix.filter((t) => !hidden.has(t) && state.topics.some((x) => x.id === t)
    && (t !== REGIONAL || state.settings.land));
}

function blockedMatcher() {
  const words = state.settings.blocked.map((w) => w.trim()).filter(Boolean);
  if (!words.length) return null;
  const escaped = words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  return new RegExp(escaped.join("|"), "i");
}

function keepStory(story, blocked) {
  if (blocked) {
    const text = [story.title, story.summary, ...story.sources.map((s) => s.title)].join(" ");
    if (blocked.test(text)) return false;
  }
  if (state.current === MIX) {
    // Ausgeblendete Themen auch im gemeinsamen Feed herausfiltern – außer die Story gehört
    // zusätzlich zu einem gewählten Fachthema.
    const hidden = new Set(state.settings.hidden);
    const chosen = new Set(mixTopics().filter((t) => t !== "top"));
    if (story.topics.some((t) => hidden.has(t)) && !story.topics.some((t) => chosen.has(t))) return false;
  }
  return true;
}

// ---------------------------------------------------------------- Story-Karten
function iconTopic(story) {
  if (![MIX, "top"].includes(state.current) && story.topics.includes(state.current)) return state.current;
  return story.topics.find((t) => t !== "top") || story.topics[0] || "top";
}

function setFallback(thumb, topic) {
  thumb.replaceChildren(el("img", { src: `/icons/topics/${topic}.svg`, alt: "" }));
  thumb.classList.add("fallback");
  thumb.style.setProperty("--tc", topicColor(topic));
}

function timeEl(ts) {
  const date = new Date(ts * 1000);
  return el("time", { dateTime: date.toISOString(), title: dtf.format(date) }, relativeTime(ts));
}

function renderStory(s, { hero = false } = {}) {
  const node = tpl.content.firstElementChild.cloneNode(true);
  if (hero) node.classList.add("hero");
  const topic = iconTopic(s);
  node.style.setProperty("--tc", topicColor(topic));

  const link = node.querySelector(".story-link");
  if (isHttpUrl(s.url)) link.href = s.url;
  link.textContent = s.title;

  const kicker = node.querySelector(".kicker");
  if (state.current === MIX || state.current === "top") kicker.append(el("span", { class: "chip topic" }, topicName(topic)));
  if (s.local) kicker.append(el("span", { class: "chip local" }, "Aus deinem Landkreis"));
  if (s.source_count > 1) kicker.append(el("span", { class: "chip sources" }, `${s.source_count} Quellen`));
  if (!kicker.children.length) kicker.remove();

  const overview = node.querySelector(".overview");
  if (s.overview && state.settings.overview) {
    overview.hidden = false;
    overview.append(el("span", { class: "ai-label", title: "Automatisch erzeugt aus den Anrisstexten" }, "KI-Überblick"), " ", s.overview);
  }
  node.querySelector(".summary").textContent = s.summary;
  node.querySelector(".publisher").textContent = s.publisher;
  node.querySelector("time").replaceWith(timeEl(s.published_at));

  if (s.sources.length) {
    const details = node.querySelector(".more-sources");
    details.hidden = false;
    details.querySelector("summary").textContent =
      `${s.sources.length} weitere ${s.sources.length === 1 ? "Quelle" : "Quellen"}`;
    details.querySelector("ul").append(...s.sources.map((src) => el("li", {},
      el("a", { href: isHttpUrl(src.url) ? src.url : "#", target: "_blank", rel: "noopener noreferrer", referrerPolicy: "no-referrer" },
        el("strong", {}, src.publisher), " ", src.title),
      " ", timeEl(src.published_at))));
  }

  const thumb = node.querySelector(".thumb");
  if (state.settings.compact) {
    thumb.remove();
  } else if (state.settings.images && s.image_url && isHttpUrl(s.image_url)) {
    const img = el("img", { class: "photo", alt: "", loading: "lazy", decoding: "async", referrerPolicy: "no-referrer" });
    img.addEventListener("error", () => setFallback(thumb, topic), { once: true });
    img.src = s.image_url;
    thumb.append(img);
  } else {
    setFallback(thumb, topic);
  }
  return node;
}

function renderSkeleton() {
  listEl.replaceChildren(...Array.from({ length: 6 }, () => {
    const node = el("div", { class: "story skeleton", "aria-hidden": "true" },
      el("div", { class: "thumb fallback" }),
      el("div", { class: "story-body" }, el("div", { class: "title" }, " "), el("div", { class: "summary" }, " ")));
    return node;
  }));
}

// ---------------------------------------------------------------- Laden
function feedParams(offset) {
  const p = new URLSearchParams({ sort: state.settings.sort, limit: PAGE_SIZE, offset });
  const topics = state.current === MIX ? mixTopics() : [state.current];
  if (!topics.length) return null;
  p.set("topics", topics.join(","));
  if (topics.includes(REGIONAL) && state.settings.land) {
    p.set("land", state.settings.land);
    if (state.settings.kreis) {
      p.set("kreis", state.settings.kreis);
      if (state.settings.onlyLocal) p.set("only_local", "true");
    }
  }
  return p;
}

function emptyState() {
  if (state.current === REGIONAL && !state.settings.land) {
    return ["Wähle zuerst deine Region aus. ",
      el("button", { type: "button", class: "link-btn", onclick: () => openSettings("#opt-land") }, "Region wählen")];
  }
  if (state.current === MIX && !mixTopics().length) {
    return ["Für „Mein Feed“ sind keine Themen gewählt. ",
      el("button", { type: "button", class: "link-btn", onclick: () => openSettings("#topic-rows") }, "Themen wählen")];
  }
  return null;
}

async function loadStories({ reset = false, retry = false } = {}) {
  if (!state.current) return;
  if (!reset && (state.loading || state.nextOffset == null)) return;
  const requestId = ++state.requestId;
  if (reset) {
    state.nextOffset = 0;
    state.seen.clear();
    if (!retry) state.pendingRetries = 0;
    window.scrollTo({ top: 0 });
  }
  const params = feedParams(state.nextOffset);
  if (!params) {
    listEl.replaceChildren();
    showStatus(emptyState());
    state.nextOffset = null;
    moreBtn.hidden = true;
    return;
  }
  if (reset) renderSkeleton();
  state.loading = true;
  listEl.setAttribute("aria-busy", "true");

  try {
    const res = await fetch(`/api/feed?${params}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (requestId !== state.requestId) return; // Ansicht inzwischen gewechselt
    const blocked = blockedMatcher();
    const fresh = data.items.filter((s) => !state.seen.has(s.id) && keepStory(s, blocked));
    fresh.forEach((s) => state.seen.add(s.id));
    const heroFirst = reset && state.settings.sort === "top" && !state.settings.compact;
    const nodes = fresh.map((s, i) => renderStory(s, { hero: heroFirst && i === 0 }));
    if (reset) listEl.replaceChildren(...nodes); else listEl.append(...nodes);
    state.nextOffset = data.next_offset;
    state.lastLoad = Date.now();

    if (data.pending) {
      showStatus("Die Meldungen für deine Region werden gerade zum ersten Mal geladen …", "info");
      if (state.pendingRetries++ < 8) setTimeout(() => requestId === state.requestId && loadStories({ reset: true, retry: true }), 4000);
    } else if (res.headers.get("x-from-cache")) {
      showStatus("Offline – du siehst den zuletzt gespeicherten Stand.", "info");
    } else if (reset && !listEl.children.length) {
      showStatus(emptyState() || (state.settings.onlyLocal && state.current === REGIONAL
        ? "Gerade keine Meldungen aus deinem Landkreis."
        : "Noch keine Meldungen. Der erste Abruf kann ein paar Minuten dauern."));
    } else {
      showStatus("");
    }
  } catch (err) {
    if (requestId !== state.requestId) return;
    if (reset) listEl.replaceChildren();
    showStatus(`Meldungen konnten nicht geladen werden (${err.message}).`, "error");
    state.nextOffset = null;
  } finally {
    if (requestId === state.requestId) {
      state.loading = false;
      listEl.setAttribute("aria-busy", "false");
      moreBtn.hidden = state.nextOffset == null;
      // Falls der Filter viel weggenommen hat: direkt nachladen
      if (state.nextOffset != null && sentinelEl.getBoundingClientRect().top < innerHeight + 600) {
        requestAnimationFrame(() => loadStories());
      }
    }
  }
}

new IntersectionObserver((entries) => {
  if (entries.some((e) => e.isIntersecting)) loadStories();
}, { rootMargin: "600px" }).observe(sentinelEl);
moreBtn.addEventListener("click", () => loadStories());

async function loadTopics() {
  const res = await fetch("/api/topics");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  state.topics = await res.json();
}

async function loadRegions() {
  if (state.regions) return state.regions;
  const res = await fetch("/api/regions");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  state.regions = await res.json();
  return state.regions;
}

async function refresh() {
  const btn = $("#refresh");
  btn.classList.add("spinning");
  try {
    await loadTopics();
    renderTabs();
  } catch { /* offline: Tabs bleiben */ }
  await loadStories({ reset: true });
  btn.classList.remove("spinning");
}

function setSort(sort) {
  if (state.settings.sort === sort) return;
  state.settings.sort = sort;
  saveSettings();
  updateTabSelection();
  loadStories({ reset: true });
}

$("#refresh").addEventListener("click", refresh);
for (const b of document.querySelectorAll(".sort-btn")) b.addEventListener("click", () => setSort(b.dataset.sort));

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && Date.now() - state.lastLoad > 10 * 60 * 1000) refresh();
});

// ---------------------------------------------------------------- Wischen (Handy)
let touchStart = null;
const feedEl = $("#feed");
feedEl.addEventListener("touchstart", (e) => {
  touchStart = e.touches.length === 1 && !e.target.closest("details")
    ? { x: e.touches[0].clientX, y: e.touches[0].clientY, t: Date.now() } : null;
}, { passive: true });
feedEl.addEventListener("touchend", (e) => {
  if (!touchStart) return;
  const t = e.changedTouches[0];
  const dx = t.clientX - touchStart.x;
  const dy = t.clientY - touchStart.y;
  const fast = Date.now() - touchStart.t < 600;
  touchStart = null;
  if (fast && Math.abs(dx) > 70 && Math.abs(dx) > Math.abs(dy) * 1.8) moveView(dx < 0 ? 1 : -1);
}, { passive: true });

// ---------------------------------------------------------------- Tastatur
document.addEventListener("keydown", (e) => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if ($("#settings").open || e.target.closest("input, textarea, select, [role=tablist]")) return;
  if (/^[1-9]$/.test(e.key)) {
    const v = state.views[Number(e.key) - 1];
    if (v) selectView(v.id);
  } else if (e.key === "j" || e.key === "k") {
    const links = [...listEl.querySelectorAll(".story-link")];
    const i = links.indexOf(document.activeElement);
    const next = links[e.key === "j" ? Math.min(i + 1, links.length - 1) : Math.max(i - 1, 0)];
    next?.focus();
    next?.closest(".story")?.scrollIntoView({ block: "center", behavior: "smooth" });
  } else if (e.key === "o") {
    const details = document.activeElement?.closest(".story")?.querySelector(".more-sources:not([hidden])");
    if (details) details.open = !details.open;
  } else if (e.key === "r") {
    refresh();
  } else if (e.key === "s") {
    setSort(state.settings.sort === "top" ? "latest" : "top");
  } else if (e.key === "[" || e.key === "]") {
    moveView(e.key === "]" ? 1 : -1);
  } else if (e.key === ",") {
    openSettings();
  }
});

// ---------------------------------------------------------------- Einstellungen
const settingsDlg = $("#settings");
let settingsDirty = false;

function renderTopicRows() {
  const s = state.settings;
  $("#topic-rows").replaceChildren(...state.topics.map((t) => {
    const visible = el("input", { type: "checkbox", checked: !s.hidden.includes(t.id), "aria-label": `${t.name} anzeigen` });
    const inMix = el("input", { type: "checkbox", checked: s.mix.includes(t.id), "aria-label": `${t.name} in Mein Feed` });
    visible.addEventListener("change", () => {
      s.hidden = visible.checked ? s.hidden.filter((x) => x !== t.id) : [...s.hidden, t.id];
      changed();
    });
    inMix.addEventListener("change", () => {
      s.mix = inMix.checked ? [...s.mix, t.id] : s.mix.filter((x) => x !== t.id);
      changed();
    });
    const dot = el("span", { class: "dot" });
    dot.style.setProperty("--tc", topicColor(t.id));
    return el("tr", {}, el("th", { scope: "row" }, dot, t.name), el("td", {}, visible), el("td", {}, inMix));
  }));
}

async function renderRegionFields() {
  const landSel = $("#opt-land");
  const kreisSel = $("#opt-kreis");
  try {
    const regions = await loadRegions();
    $("#region-attribution").textContent = `Ortsdaten: ${regions.attribution}`;
    landSel.replaceChildren(el("option", { value: "" }, "– keine Region –"),
      ...regions.laender.map((l) => el("option", { value: l.id }, l.name)));
    landSel.value = state.settings.land || "";
    const land = regions.laender.find((l) => l.id === state.settings.land);
    kreisSel.replaceChildren(el("option", { value: "" }, "– ganzes Bundesland –"),
      ...(land ? land.kreise.map((k) => el("option", { value: k.id }, k.name)) : []));
    kreisSel.disabled = !land;
    kreisSel.value = state.settings.kreis || "";
  } catch {
    $("#region-attribution").textContent = "Regionen konnten nicht geladen werden (offline?).";
  }
  $("#opt-only-local").checked = state.settings.onlyLocal;
  $("#opt-only-local").disabled = !state.settings.kreis;
}

function changed() {
  settingsDirty = true;
  saveSettings();
}

async function openSettings(focusSel) {
  const s = state.settings;
  $("#opt-images").checked = s.images;
  $("#opt-overview").checked = s.overview;
  $("#opt-compact").checked = s.compact;
  $("#opt-blocked").value = s.blocked.join(", ");
  renderTopicRows();
  settingsDirty = false;
  settingsDlg.showModal();
  await renderRegionFields();
  if (focusSel) $(focusSel)?.scrollIntoView({ block: "center" });
  if (focusSel === "#opt-land") $("#opt-land").focus();
}

$("#open-settings").addEventListener("click", () => openSettings());
for (const [id, key] of [["#opt-images", "images"], ["#opt-overview", "overview"], ["#opt-compact", "compact"], ["#opt-only-local", "onlyLocal"]]) {
  $(id).addEventListener("change", (e) => { state.settings[key] = e.target.checked; changed(); });
}
$("#opt-land").addEventListener("change", async (e) => {
  state.settings.land = e.target.value || null;
  state.settings.kreis = null;
  state.settings.onlyLocal = false;
  if (state.settings.land && !state.settings.mix.includes(REGIONAL)) state.settings.mix.push(REGIONAL);
  changed();
  await renderRegionFields();
});
$("#opt-kreis").addEventListener("change", (e) => {
  state.settings.kreis = e.target.value || null;
  if (!state.settings.kreis) state.settings.onlyLocal = false;
  $("#opt-only-local").disabled = !state.settings.kreis;
  $("#opt-only-local").checked = state.settings.onlyLocal;
  changed();
});
$("#opt-blocked").addEventListener("change", (e) => {
  state.settings.blocked = e.target.value.split(",").map((w) => w.trim()).filter(Boolean);
  changed();
});
$("#reset-settings").addEventListener("click", () => {
  if (!confirm("Alle Einstellungen auf diesem Gerät zurücksetzen?")) return;
  state.settings = structuredClone(DEFAULT_SETTINGS);
  try { localStorage.removeItem(SETTINGS_KEY); localStorage.removeItem("newsfeed.settings.v1"); } catch { /* egal */ }
  settingsDirty = true;
  settingsDlg.close();
});
settingsDlg.addEventListener("close", () => {
  if (!settingsDirty) return;
  renderTabs();
  selectView(state.views.some((v) => v.id === state.current) ? state.current : state.views[0].id, { force: true });
});

// ---------------------------------------------------------------- Start
async function init() {
  updateTabSelection();
  try {
    await loadTopics();
  } catch (err) {
    showStatus(`Server nicht erreichbar (${err.message}).`, "error");
    return;
  }
  if (state.settings.land) loadRegions().then(renderTabs).catch(() => {});
  renderTabs();
  const fromHash = location.hash.replace(/^#\//, "");
  selectView(state.views.some((v) => v.id === fromHash) ? fromHash : state.views[0].id, { force: true });
}

window.addEventListener("hashchange", () => {
  const id = location.hash.replace(/^#\//, "");
  if (state.views.some((v) => v.id === id)) selectView(id);
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => { /* ohne SW weiterhin nutzbar */ });
}

init();
