"use strict";
// Hamburg Student Jobs - everything runs in the browser over one JSON file.

const $ = (s) => document.querySelector(s);
const PAGE = 30;
const LEVELS = ["Werkstudent", "Internship", "Thesis", "Student side job", "Junior / Trainee"];
const GERMAN = [
  { id: 0, label: "Not needed" },
  { id: 1, label: "Basic / a plus" },
  { id: 2, label: "Required" },
];
const MODES = ["Remote", "Hybrid", "Onsite", "Not stated"];
const POSTED = [{ id: "", label: "Any time" }, { id: "1", label: "Today" }, { id: "7", label: "7 days" }, { id: "30", label: "30 days" }];

const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode */ } },
};

let JOBS = [];
let shown = PAGE;
const saved = new Set(store.get("hsj-saved", []));
const state = {
  q: "", english: false, levels: new Set(), german: new Set(), fields: new Set(), modes: new Set(),
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
function germanText(j) {
  const n = germanNeed(j);
  if (j.ai) {
    return n === 0 ? "No German needed" : n === 1 ? "Basic German"
      : j.german_level === "good" ? "Good German (B1–B2)" : "Fluent German";
  }
  return n === 0 ? "German not mentioned" : n === 1 ? "German a plus" : "German required";
}
const modeOf = (j) => j.work_mode || "Not stated";
const daysAgo = (iso) => Math.max(0, Math.round((Date.now() - new Date(iso + "T00:00:00").getTime()) / 864e5));
function ago(iso) {
  const d = daysAgo(iso);
  if (d === 0) return "today";
  if (d === 1) return "yesterday";
  if (d < 30) return `${d} days ago`;
  const m = Math.round(d / 30);
  return m < 12 ? `${m} month${m > 1 ? "s" : ""} ago` : "over a year ago";
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
  if (skip !== "german" && state.german.size && !state.german.has(germanNeed(j))) return false;
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
    chip(l, state.levels.has(l), () => { toggle(state.levels, l); update(); }, countWhere("levels", (j) => j.level === l))));

  const gm = $("#f-german"); gm.replaceChildren(...GERMAN.map((g) => {
    const n = countWhere("german", (j) => germanNeed(j) === g.id);
    return el("label", { class: "opt" + (n ? "" : " zero") },
      el("input", { type: "checkbox", checked: state.german.has(g.id), onchange: () => { toggle(state.german, g.id); update(); } }),
      el("span", { class: `lang-pill l${g.id}` }, g.label), el("span", { class: "n" }, n));
  }));

  const fields = [...new Set(JOBS.map((j) => j.field))].sort((a, b) => (a === "Other") - (b === "Other") || a.localeCompare(b));
  $("#f-field").replaceChildren(...fields.map((f) => {
    const n = countWhere("fields", (j) => j.field === f);
    return el("label", { class: "opt" + (n ? "" : " zero") },
      el("input", { type: "checkbox", checked: state.fields.has(f), onchange: () => { toggle(state.fields, f); update(); } }),
      el("span", {}, f), el("span", { class: "n" }, n));
  }));

  $("#f-mode").replaceChildren(...MODES.map((m) =>
    chip(m, state.modes.has(m), () => { toggle(state.modes, m); update(); }, countWhere("modes", (j) => modeOf(j) === m))));

  $("#f-posted").replaceChildren(...POSTED.map((p) =>
    chip(p.label, state.posted === p.id, () => { state.posted = p.id; update(); })));

  $("#mySkills").replaceChildren(...state.skills.map((s) =>
    el("button", { type: "button", class: "chip", title: `Remove ${s}`, onclick: () => {
      state.skills = state.skills.filter((x) => x !== s); store.set("hsj-skills", state.skills); update();
    } }, s)));

  $("#savedCount").textContent = saved.size ? `(${saved.size})` : "";
}

function activeChips() {
  const out = [];
  const add = (label, off) => out.push(el("button", { type: "button", class: "chip", title: "Remove filter", onclick: () => { off(); update(); } }, label));
  if (state.q) add(`"${state.q}"`, () => { state.q = ""; $("#q").value = ""; });
  if (state.english) add("English is enough", () => { state.english = false; });
  state.levels.forEach((l) => add(l, () => state.levels.delete(l)));
  state.german.forEach((g) => add(`German: ${GERMAN[g].label}`, () => state.german.delete(g)));
  state.fields.forEach((f) => add(f, () => state.fields.delete(f)));
  state.modes.forEach((m) => add(m, () => state.modes.delete(m)));
  if (state.posted) add(`Posted: ${POSTED.find((p) => p.id === state.posted).label}`, () => { state.posted = ""; });
  if (state.hideMandatory) add("No mandatory-only internships", () => { state.hideMandatory = false; });
  if (state.savedOnly) add("Saved only", () => { state.savedOnly = false; });
  return out;
}

const tpl = $("#cardTpl");
function card(j) {
  const c = tpl.content.firstElementChild.cloneNode(true);
  const a = c.querySelector(".title a"); a.href = j.url; a.textContent = j.title;
  c.querySelector(".company").textContent = j.company || "Company not named";
  const av = c.querySelector(".avatar"); av.textContent = initials(j.company); av.style.setProperty("--h", hue(j.company));
  c.querySelector(".loc").textContent = j.location || "Hamburg";

  const save = c.querySelector(".save");
  const setSave = () => { const on = saved.has(j.id); save.setAttribute("aria-pressed", String(on)); save.title = on ? "Remove from saved" : "Save this job"; };
  setSave();
  save.addEventListener("click", () => { if (!saved.has(j.id)) track("save-job", true); toggle(saved, j.id); store.set("hsj-saved", [...saved]); setSave(); renderFilters(); if (state.savedOnly) update(); });

  const need = germanNeed(j);
  const badges = [
    daysAgo(j.first_seen) <= 1 && daysAgo(j.posted) <= 3 ? el("span", { class: "badge new" }, "New") : null,
    el("span", { class: "badge level" }, j.level),
    el("span", { class: `lang-pill l${need}` }, germanText(j)),
    el("span", { class: "badge" }, j.field),
    j.work_mode ? el("span", { class: "badge" }, j.work_mode) : null,
    j.mandatory ? el("span", { class: "badge warn", title: "Only for students whose degree requires this internship" }, "Mandatory internship only") : null,
  ];
  c.querySelector(".badges").replaceChildren(...badges.filter(Boolean));

  c.querySelector(".summary").textContent = j.summary || "";
  c.querySelector(".reqs").replaceChildren(...(j.requirements || []).map((r) => el("li", {}, r)));

  const hits = new Set(matchOf(j));
  const skills = [...j.skills].sort((x, y) => hits.has(y) - hits.has(x));
  c.querySelector(".skills").replaceChildren(...skills.slice(0, 10).map((s) => el("span", { class: "skill" + (hits.has(s) ? " hit" : "") }, s)));

  const facts = [`Posted ${ago(j.posted)}`, j.copies > 1 && `Open at ${j.copies} locations`, j.hours, j.pay, j.duration,
    j.start && `Start ${j.start}`].filter(Boolean);
  if (hits.size) facts.unshift(`Matches ${hits.size} of your skill${hits.size > 1 ? "s" : ""}`);
  c.querySelector(".facts").textContent = facts.join(" · ");
  const view = c.querySelector(".view"); view.href = j.url;
  const opened = () => track("open-ad", true);
  view.addEventListener("click", opened); a.addEventListener("click", opened);
  view.setAttribute("aria-label", `View the original ad for ${j.title} (opens in a new tab)`);
  view.firstChild.textContent = j.source === "Company Site" ? "View on company site " : `View on ${j.source} `;
  if (j.source === "Adzuna") c.querySelector(".card-foot").insertBefore(adzunaLabel(), view);
  return c;
}

// Adzuna's terms: each Adzuna ad carries "Jobs by <Adzuna logo>", both linking to the local Adzuna site
function adzunaLabel() {
  const logo = el("img", { src: "adzuna-logo.png", alt: "Adzuna", height: "23" });
  logo.addEventListener("error", () => logo.replaceWith(el("strong", { class: "adzuna-word" }, "Adzuna")), { once: true });
  return el("span", { class: "attrib" },
    el("a", { href: "https://www.adzuna.de", target: "_blank", rel: "noopener" }, "Jobs"), " by ",
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
  $("#resultCount").textContent = `${list.length.toLocaleString("en")} job${list.length === 1 ? "" : "s"}`;
  $("#cards").replaceChildren(...list.slice(0, shown).map(card));
  $("#moreBtn").hidden = list.length <= shown;
  $("#moreBtn").textContent = `Show more (${(list.length - shown).toLocaleString("en")} left)`;
  $("#empty").hidden = list.length > 0;
  writeURL();
}

function writeURL() {
  const p = new URLSearchParams();
  if (state.q) p.set("q", state.q);
  if (state.english) p.set("en", "1");
  if (state.levels.size) p.set("type", [...state.levels].join(","));
  if (state.german.size) p.set("de", [...state.german].join(","));
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
  state.german = new Set(list("de").map(Number).filter((n) => [0, 1, 2].includes(n)));
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
    Object.assign(state, { q: "", english: false, levels: new Set(), german: new Set(), fields: new Set(), modes: new Set(),
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
  $("#themeBtn").addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("hsj-theme", document.documentElement.dataset.theme); } catch (e) { /* ignore */ }
  });
}

function renderStats(data) {
  const english = JOBS.filter((j) => germanNeed(j) < 2).length;
  const newToday = JOBS.filter((j) => daysAgo(j.first_seen) === 0).length;
  const updated = new Date(data.updated);
  $("#stats").replaceChildren(...[
    el("span", {}, el("b", {}, JOBS.length.toLocaleString("en")), " open jobs"),
    el("span", {}, el("b", {}, english.toLocaleString("en")), " without a German requirement"),
    newToday && newToday < JOBS.length ? el("span", {}, el("b", {}, newToday), " new today") : null,
    el("span", {}, "Updated ", updated.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })),
  ].filter(Boolean));
}

async function main() {
  readURL();
  wire();
  $("#resultCount").textContent = "Loading jobs…";
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
    $("#resultCount").textContent = "Could not load the job list. Please try again in a moment.";
  }
}
track("/");
main();
