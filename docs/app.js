"use strict";
// Hamburg Student Jobs - everything runs in the browser over one JSON file.

const $ = (s) => document.querySelector(s);
const PAGE = 30;
const LEVELS = ["Werkstudent", "Internship", "Thesis", "Student side job", "Junior / Trainee"];
const SPEAK = ["en", "both", "de"];  // working language: only English / English and German / only German
const MODES = ["Remote", "Hybrid", "Onsite", "Not stated"];
const POSTED = ["", "1", "7", "30"];
// display names (data values stay English)
const levelName = (l) => t(`level.${l}`);
const fieldName = (f) => t(`field.${f}`);
const modeName = (m) => t(`mode.${m}`);
const num = (n) => n.toLocaleString(I18N.locale());

const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode */ } },
};

let JOBS = [];
let shown = PAGE;
const saved = new Set(store.get("hsj-saved", []));
const state = {
  q: "", english: false, levels: new Set(), speak: new Set(), fields: new Set(), modes: new Set(),
  posted: "", hideMandatory: false, savedOnly: false, sort: "new",
  skills: store.get("hsj-skills", []),
};

// Anonymous usage counts (GoatCounter, no cookies). Only fixed paths/event names are sent - never the
// query string, search text or skills. Silently does nothing if the counter is blocked.
function track(path, event = false) {
  const go = () => { try { window.goatcounter && window.goatcounter.count && window.goatcounter.count({ path, event }); } catch (e) { /* ignore */ } };
  if (document.readyState === "complete") go(); else window.addEventListener("load", go, { once: true });
}

// ---------------------------------------------------------------- derived facts
function germanNeed(j) {
  if (j.ai) {
    if (["none", "not stated"].includes(j.german_level)) return j.lang === "DE" ? 2 : 0;
    return j.german_level === "basic" ? 1 : 2;
  }
  return j.german === "required" ? 2 : j.german === "a plus" ? 1 : 0;
}
// Which languages the job is done in, from the German need plus whether English is asked for.
function speakOf(j) {
  const need = germanNeed(j);
  const english = j.ai ? !["none", "not stated"].includes(j.english_level) || j.lang === "EN"
    : j.lang === "EN" || (j.english && j.english !== "not mentioned");
  if (need === 0) return "en";
  if (need === 1) return "both";
  return english ? "both" : "de";
}
const SPEAK_CLASS = { en: "l0", both: "l1", de: "l2" };
function germanText(j) {
  const n = germanNeed(j);
  if (j.ai) {
    return t(n === 0 ? "gtext.none" : n === 1 ? "gtext.basic" : j.german_level === "good" ? "gtext.good" : "gtext.fluent");
  }
  return t(n === 0 ? "gtext.notMentioned" : n === 1 ? "gtext.plus" : "gtext.required");
}
const modeOf = (j) => j.work_mode || "Not stated";
const daysAgo = (iso) => Math.max(0, Math.round((Date.now() - new Date(iso + "T00:00:00").getTime()) / 864e5));
function ago(iso) {
  const d = daysAgo(iso);
  if (d === 0) return t("ago.today");
  if (d === 1) return t("ago.yesterday");
  if (d < 30) return t("ago.days", { n: d });
  const m = Math.round(d / 30);
  return m === 1 ? t("ago.month") : m < 12 ? t("ago.months", { n: m }) : t("ago.year");
}
// job details come from the pipeline in English units ("20 h/week", "6 months", ISO dates): show them locally
function detail(s) {
  if (!s) return s;
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) {
    return new Date(s + "T00:00:00").toLocaleDateString(I18N.locale(), { day: "numeric", month: "short", year: "numeric" });
  }
  if (I18N.lang !== "de") return s === "part-time" ? "Part-time" : s;
  return s.replace(/h\/week/g, "Std./Woche").replace(/\bmonths\b/g, "Monate").replace(/^part-time$/, "Teilzeit")
    .replace(/EUR\/h\b/g, "€/Std.").replace(/EUR\/yr\b/g, "€/Jahr");
}
// initials tile per company: "Lufthansa Technik AG" -> "LT", same colour every time for the same company
const LEGAL = /^(gmbh|ag|se|kg|co|mbh|ug|e\.?v|kgaa|ohg|inc|ltd|gbr|&|und|and|the|der|die|das)$/i;
function initials(name) {
  const words = (name || "?").replace(/[()|,.:]/g, " ").split(/\s+/).filter((w) => w && !LEGAL.test(w));
  return ((words[0] || "?")[0] + (words[1] ? words[1][0] : (words[0] || "").slice(1, 2))).toUpperCase();
}
function hue(name) {
  let h = 0;
  for (const ch of name || "") h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}
const norm = (s) => s.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "");
function matchOf(j) {
  if (!state.skills.length) return [];
  const mine = new Set(state.skills.map(norm));
  return j.skills.filter((s) => mine.has(norm(s)));
}

// ---------------------------------------------------------------- filtering
function passes(j, skip) {
  if (state.q) {
    const hay = j._hay;
    if (!state.q.split(/\s+/).every((w) => hay.includes(w))) return false;
  }
  if (state.english && germanNeed(j) === 2) return false;
  if (skip !== "levels" && state.levels.size && !state.levels.has(j.level)) return false;
  if (skip !== "speak" && state.speak.size && !state.speak.has(speakOf(j))) return false;
  if (skip !== "fields" && state.fields.size && !state.fields.has(j.field)) return false;
  if (skip !== "modes" && state.modes.size && !state.modes.has(modeOf(j))) return false;
  if (skip !== "posted" && state.posted && daysAgo(j.posted) > Number(state.posted) - (state.posted === "1" ? 1 : 0)) return false;
  if (state.hideMandatory && j.mandatory) return false;
  if (state.savedOnly && !saved.has(j.id)) return false;
  return true;
}
function results() {
  const list = JOBS.filter((j) => passes(j));
  const byNew = (a, b) => (b.posted > a.posted ? 1 : b.posted < a.posted ? -1 : 0);
  if (state.sort === "company") list.sort((a, b) => a.company.localeCompare(b.company, "de") || byNew(a, b));
  else if (state.sort === "match") list.sort((a, b) => matchOf(b).length - matchOf(a).length || byNew(a, b));
  else list.sort(byNew);
  return list;
}
const countWhere = (skip, pred) => JOBS.reduce((n, j) => n + (passes(j, skip) && pred(j) ? 1 : 0), 0);

// ---------------------------------------------------------------- rendering helpers
function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === false || v == null) continue;
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) e.append(kid.nodeType ? kid : String(kid));
  return e;
}
function chip(label, pressed, onclick, n) {
  return el("button", { type: "button", class: "chip", "aria-pressed": String(pressed), onclick },
    label, n != null ? el("span", { class: "n" }, n) : null);
}
function toggle(set, v) { set.has(v) ? set.delete(v) : set.add(v); }

function renderFilters() {
  const lv = $("#f-level"); lv.replaceChildren(...LEVELS.map((l) =>
    chip(levelName(l), state.levels.has(l), () => { toggle(state.levels, l); update(); }, countWhere("levels", (j) => j.level === l))));

  const sp = $("#f-speak"); sp.replaceChildren(...SPEAK.map((g) => {
    const n = countWhere("speak", (j) => speakOf(j) === g);
    return el("label", { class: "opt" + (n ? "" : " zero") },
      el("input", { type: "checkbox", checked: state.speak.has(g), onchange: () => { toggle(state.speak, g); update(); } }),
      el("span", { class: `lang-pill ${SPEAK_CLASS[g]}` }, t(`speak.${g}`)), el("span", { class: "n" }, num(n)));
  }));

  const fields = [...new Set(JOBS.map((j) => j.field))]
    .sort((a, b) => (a === "Other") - (b === "Other") || fieldName(a).localeCompare(fieldName(b), I18N.locale()));
  $("#f-field").replaceChildren(...fields.map((f) => {
    const n = countWhere("fields", (j) => j.field === f);
    return el("label", { class: "opt" + (n ? "" : " zero") },
      el("input", { type: "checkbox", checked: state.fields.has(f), onchange: () => { toggle(state.fields, f); update(); } }),
      el("span", {}, fieldName(f)), el("span", { class: "n" }, num(n)));
  }));

  $("#f-mode").replaceChildren(...MODES.map((m) =>
    chip(modeName(m), state.modes.has(m), () => { toggle(state.modes, m); update(); }, countWhere("modes", (j) => modeOf(j) === m))));

  $("#f-posted").replaceChildren(...POSTED.map((p) =>
    chip(t(`posted.${p}`), state.posted === p, () => { state.posted = p; update(); })));

  $("#mySkills").replaceChildren(...state.skills.map((s) =>
    el("button", { type: "button", class: "chip", title: t("remove.skill", { s }), onclick: () => {
      state.skills = state.skills.filter((x) => x !== s); store.set("hsj-skills", state.skills); update();
    } }, s)));

  $("#savedCount").textContent = saved.size ? `(${saved.size})` : "";
}

function activeChips() {
  const out = [];
  const add = (label, off) => out.push(el("button", { type: "button", class: "chip", title: t("remove.filter"), onclick: () => { off(); update(); } }, label));
  if (state.q) add(t("chip.search", { q: state.q }), () => { state.q = ""; $("#q").value = ""; });
  if (state.english) add(t("english.switch"), () => { state.english = false; });
  state.levels.forEach((l) => add(levelName(l), () => state.levels.delete(l)));
  state.speak.forEach((g) => add(t(`speak.${g}`), () => state.speak.delete(g)));
  state.fields.forEach((f) => add(fieldName(f), () => state.fields.delete(f)));
  state.modes.forEach((m) => add(modeName(m), () => state.modes.delete(m)));
  if (state.posted) add(t("chip.posted", { l: t(`posted.${state.posted}`) }), () => { state.posted = ""; });
  if (state.hideMandatory) add(t("chip.noMandatory"), () => { state.hideMandatory = false; });
  if (state.savedOnly) add(t("chip.saved"), () => { state.savedOnly = false; });
  return out;
}

const tpl = $("#cardTpl");
function card(j) {
  const c = tpl.content.firstElementChild.cloneNode(true);
  const a = c.querySelector(".title a"); a.href = j.url; a.textContent = j.title;
  c.querySelector(".company").textContent = j.company || t("company.none");
  const av = c.querySelector(".avatar"); av.textContent = initials(j.company); av.style.setProperty("--h", hue(j.company));
  c.querySelector(".loc").textContent = j.location || "Hamburg";

  const save = c.querySelector(".save");
  const setSave = () => { const on = saved.has(j.id); save.setAttribute("aria-pressed", String(on)); save.title = on ? t("save.remove") : t("save.add"); };
  setSave();
  save.addEventListener("click", () => { if (!saved.has(j.id)) track("save-job", true); toggle(saved, j.id); store.set("hsj-saved", [...saved]); setSave(); renderFilters(); if (state.savedOnly) update(); });

  const need = germanNeed(j);
  const badges = [
    daysAgo(j.first_seen) <= 1 && daysAgo(j.posted) <= 3 ? el("span", { class: "badge new" }, t("badge.new")) : null,
    el("span", { class: "badge level" }, levelName(j.level)),
    el("span", { class: `lang-pill ${SPEAK_CLASS[speakOf(j)]}`, title: germanText(j) }, t(`speak.${speakOf(j)}`)),
    el("span", { class: "badge" }, fieldName(j.field)),
    j.work_mode ? el("span", { class: "badge" }, modeName(j.work_mode)) : null,
    j.mandatory ? el("span", { class: "badge warn", title: t("badge.mandatoryTitle") }, t("badge.mandatory")) : null,
  ];
  c.querySelector(".badges").replaceChildren(...badges.filter(Boolean));

  c.querySelector(".summary").textContent = j.summary || "";
  c.querySelector(".reqs").replaceChildren(...(j.requirements || []).map((r) => el("li", {}, r)));

  const hits = new Set(matchOf(j));
  const skills = [...j.skills].sort((x, y) => hits.has(y) - hits.has(x));
  c.querySelector(".skills").replaceChildren(...skills.slice(0, 10).map((s) => el("span", { class: "skill" + (hits.has(s) ? " hit" : "") }, s)));

  const facts = [t("fact.posted", { ago: ago(j.posted) }), j.copies > 1 && t("fact.copies", { n: j.copies }),
    detail(j.hours), detail(j.pay), detail(j.duration), j.start && t("fact.start", { d: detail(j.start) })].filter(Boolean);
  if (hits.size) facts.unshift(hits.size === 1 ? t("fact.matches.one") : t("fact.matches.many", { n: hits.size }));
  c.querySelector(".facts").textContent = facts.join(" · ");
  const view = c.querySelector(".view"); view.href = j.url;
  const opened = () => track("open-ad", true);
  view.addEventListener("click", opened); a.addEventListener("click", opened);
  view.setAttribute("aria-label", t("view.aria", { t: j.title }));
  view.firstChild.textContent = (j.source === "Company Site" ? t("view.company") : t("view.source", { s: j.source })) + " ";
  if (j.source === "Adzuna") c.querySelector(".card-foot").insertBefore(adzunaLabel(), view);
  return c;
}

// Adzuna's terms: each Adzuna ad carries "Jobs by <Adzuna logo>", both linking to the local Adzuna site
function adzunaLabel() {
  const logo = el("img", { src: "adzuna-logo.png", alt: "Adzuna", height: "40" });
  logo.addEventListener("error", () => logo.replaceWith(el("strong", { class: "adzuna-word" }, "Adzuna")), { once: true });
  return el("span", { class: "attrib" },
    el("a", { href: "https://www.adzuna.de", target: "_blank", rel: "noopener" }, t("jobsBy")), t("by"),
    el("a", { href: "https://www.adzuna.de", target: "_blank", rel: "noopener" }, logo));
}

// ---------------------------------------------------------------- update cycle + URL state
function update(keepPage) {
  if (!keepPage) shown = PAGE;
  const list = results();
  renderFilters();
  $("#activeFilters").replaceChildren(...activeChips());
  const nActive = activeChips().length;
  $("#activeCount").textContent = nActive || "";
  $("#resultCount").textContent = list.length === 1 ? t("count.one") : t("count.many", { n: num(list.length) });
  $("#cards").replaceChildren(...list.slice(0, shown).map(card));
  $("#moreBtn").hidden = list.length <= shown;
  $("#moreBtn").textContent = t("more", { n: num(list.length - shown) });
  $("#empty").hidden = list.length > 0;
  writeURL();
}

function writeURL() {
  const p = new URLSearchParams();
  if (state.q) p.set("q", state.q);
  if (state.english) p.set("en", "1");
  if (state.levels.size) p.set("type", [...state.levels].join(","));
  if (state.speak.size) p.set("speak", [...state.speak].join(","));
  if (state.fields.size) p.set("field", [...state.fields].join(","));
  if (state.modes.size) p.set("mode", [...state.modes].join(","));
  if (state.posted) p.set("days", state.posted);
  if (state.hideMandatory) p.set("nomandatory", "1");
  if (state.sort !== "new") p.set("sort", state.sort);
  const qs = p.toString();
  history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
}
function readURL() {
  const p = new URLSearchParams(location.search);
  const list = (k) => (p.get(k) || "").split(",").filter(Boolean);
  state.q = p.get("q") || "";
  state.english = p.get("en") === "1";
  state.levels = new Set(list("type").filter((l) => LEVELS.includes(l)));
  state.speak = new Set(list("speak").filter((s) => SPEAK.includes(s)));
  state.fields = new Set(list("field"));
  state.modes = new Set(list("mode").filter((m) => MODES.includes(m)));
  state.posted = ["1", "7", "30"].includes(p.get("days")) ? p.get("days") : "";
  state.hideMandatory = p.get("nomandatory") === "1";
  state.sort = ["new", "match", "company"].includes(p.get("sort")) ? p.get("sort") : "new";
}

// ---------------------------------------------------------------- wiring
function wire() {
  let t;
  $("#q").value = state.q;
  $("#q").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { state.q = norm(e.target.value.trim()); update(); }, 150); });
  $("#englishOnly").checked = state.english;
  $("#englishOnly").addEventListener("change", (e) => { state.english = e.target.checked; update(); });
  $("#hideMandatory").checked = state.hideMandatory;
  $("#hideMandatory").addEventListener("change", (e) => { state.hideMandatory = e.target.checked; update(); });
  $("#savedOnly").addEventListener("change", (e) => { state.savedOnly = e.target.checked; update(); });
  $("#sort").value = state.sort;
  $("#sort").addEventListener("change", (e) => { state.sort = e.target.value; update(); });
  $("#moreBtn").addEventListener("click", () => { shown += PAGE; update(true); });

  const addSkill = () => {
    const v = $("#skillInput").value.trim();
    if (v && !state.skills.some((s) => norm(s) === norm(v))) {
      state.skills.push(v); store.set("hsj-skills", state.skills);
      if (state.sort === "new") { state.sort = "match"; $("#sort").value = "match"; }
      update();
    }
    $("#skillInput").value = "";
  };
  $("#skillAdd").addEventListener("click", addSkill);
  $("#skillInput").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addSkill(); } });

  const reset = () => {
    Object.assign(state, { q: "", english: false, levels: new Set(), speak: new Set(), fields: new Set(), modes: new Set(),
      posted: "", hideMandatory: false, savedOnly: false });
    $("#q").value = ""; $("#englishOnly").checked = false; $("#hideMandatory").checked = false; $("#savedOnly").checked = false;
    update();
  };
  $("#resetBtn").addEventListener("click", reset);
  $("#emptyReset").addEventListener("click", reset);

  const drawer = (open) => {
    $("#filters").classList.toggle("open", open); document.body.classList.toggle("drawer-open", open);
    if (open) $("#closeFilters").focus();
  };
  $("#openFilters").addEventListener("click", () => drawer(true));
  $("#closeFilters").addEventListener("click", () => drawer(false));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") drawer(false); });
  document.addEventListener("click", (e) => {
    if (document.body.classList.contains("drawer-open") && !$("#filters").contains(e.target) && !$("#openFilters").contains(e.target)) drawer(false);
  });

  $("#aboutBtn").addEventListener("click", () => $("#about").showModal());
  $("#langBtn").addEventListener("click", () => {
    I18N.set(I18N.lang === "de" ? "en" : "de");
    if (lastData) renderStats(lastData);
    if (JOBS.length) update(true);
  });
  $("#themeBtn").addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("hsj-theme", document.documentElement.dataset.theme); } catch (e) { /* ignore */ }
  });
}

let lastData = null;
function renderStats(data) {
  lastData = data;
  const english = JOBS.filter((j) => germanNeed(j) < 2).length;
  const newToday = JOBS.filter((j) => daysAgo(j.first_seen) === 0).length;
  const updated = new Date(data.updated);
  $("#stats").replaceChildren(...[
    el("span", {}, el("b", {}, num(JOBS.length)), t("stats.open")),
    el("span", {}, el("b", {}, num(english)), t("stats.english")),
    newToday && newToday < JOBS.length ? el("span", {}, el("b", {}, num(newToday)), t("stats.new")) : null,
    el("span", {}, t("stats.updated", { d: updated.toLocaleString(I18N.locale(), { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) })),
  ].filter(Boolean));
}

async function main() {
  I18N.init();
  readURL();
  wire();
  $("#resultCount").textContent = t("loading");
  try {
    const res = await fetch("data/jobs.json", { cache: "no-cache" });
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();
    JOBS = data.jobs.map((j) => ({ ...j, _hay: norm([j.title, j.company, j.field, j.location, ...(j.skills || []), j.summary || ""].join(" ")) }));
    const vocab = [...new Set(JOBS.flatMap((j) => j.skills))].sort();
    $("#skillList").replaceChildren(...vocab.map((s) => el("option", { value: s })));
    renderStats(data);
    update();
  } catch (e) {
    // opened by double-click (file://): browsers block loading data/jobs.json that way
    $("#resultCount").textContent = location.protocol === "file:" ? t("loadErrorFile") : t("loadError");
  }
}
track("/");
main();
