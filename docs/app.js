"use strict";
// Hamburg Student Jobs - everything runs in the browser over one JSON file.

const $ = (s) => document.querySelector(s);
const PAGE = 30;
const LEVELS = ["Werkstudent", "Internship", "Thesis", "Student side job", "Junior / Trainee"];
const SPEAK = ["en", "both", "de"];  // working language: only English / English and German / only German
const MODES = ["Remote", "Hybrid", "Onsite", "Not stated"];
const POSTED = ["", "1", "7", "30"];
const AREAS = ["hh", "around", "remote"];  // Hamburg itself / towns around it / remote jobs based elsewhere
// feedback form -> Azure Function (feedback/ in the repo; only accepts posts from the live domain).
// Local runs use `func start --port 7079` instead. Empty = form hidden.
const FEEDBACK_URL = location.hostname === "localhost" ? "http://localhost:7079/api/feedback"
  : "https://hsj-feedback-emir.azurewebsites.net/api/feedback";
const FB_KINDS = ["question", "idea", "criticism", "bug", "job", "employer", "other"];
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
const applied = new Set(store.get("hsj-applied", []));
const hidden = new Set(store.get("hsj-hidden", []));
// filters that "Reset all" clears (sort and skills stay)
const cleanFilters = () => ({ q: "", english: false, levels: new Set(), speak: new Set(), fields: new Set(), modes: new Set(),
  areas: new Set(), company: "", posted: "", hideMandatory: false, payOnly: false, savedOnly: false, appliedOnly: false, showHidden: false });
const state = { ...cleanFilters(), sort: "new", skills: store.get("hsj-skills", []) };

// day of the previous visit (local date), so jobs the board found since then can be marked
const TODAY = new Date().toLocaleDateString("sv-SE");
const lastVisit = (() => {
  const v = store.get("hsj-visit", null);
  if (!v || !v.cur) { store.set("hsj-visit", { cur: TODAY, prev: null }); return null; }
  if (v.cur !== TODAY) { store.set("hsj-visit", { cur: TODAY, prev: v.cur }); return v.cur; }
  return v.prev || null;
})();
const newSinceVisit = (j) => Boolean(lastVisit && j.first_seen > lastVisit);

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
// "Remote, Germany (Berlin)" -> remote; "Braak bei Hamburg", "Hamburg (Stade)" -> around; "Hamburg (3 Locations)" -> hh
function areaOf(j) {
  const l = j.location || "Hamburg";
  if (/^remote\b/i.test(l)) return "remote";
  return /hamburg/i.test(l) && !/\bbei hamburg|\bbz\.? hamburg|^hamburg \((?!\d)/i.test(l) ? "hh" : "around";
}
// sources write places differently: "Hamburg, , Germany", "Ahrensburg, Stormarn (Kreis)", "Hamburg / Hamburg"
function placeOf(j) {
  return (j.location || "Hamburg").replace(/\s*[•·].*$/, "").replace(/(,\s*)+(Deutschland|Germany)$/i, "").replace(/,\s*HH$/, "")
    .replace(/,\s*(Kreis [^,]+|[^,]+ \(Kreis\))$/, "").replace(/^Hamburg \/ Hamburg$/, "Hamburg")
    .replace(/^Remote, Germany \((.+)\)$/, "Remote ($1)");
}
// "15-15 EUR/h" -> "15 €/h", "14-18 EUR/h" -> "14–18 €/h", "45000-55000 EUR" -> "45000–55000 €"
function payText(p) {
  if (!p) return "";
  const s = p.replace(/(\d[\d.,]*)\s*-\s*\1(?![\d.,])/, "$1").replace(/(\d)\s*-\s*(\d)/g, "$1–$2");
  if (I18N.lang === "de") return detail(s).replace(/ EUR$/, " €");
  return s.replace(/EUR\/h\b/, "€/h").replace(/EUR\/yr\b/, "€/year").replace(/ EUR$/, " €");
}
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
  if (!state.showHidden && hidden.has(j.id)) return false;
  if (state.english && germanNeed(j) === 2) return false;
  if (skip !== "levels" && state.levels.size && !state.levels.has(j.level)) return false;
  if (skip !== "speak" && state.speak.size && !state.speak.has(speakOf(j))) return false;
  if (skip !== "areas" && state.areas.size && !state.areas.has(areaOf(j))) return false;
  if (skip !== "fields" && state.fields.size && !state.fields.has(j.field)) return false;
  if (skip !== "modes" && state.modes.size && !state.modes.has(modeOf(j))) return false;
  if (skip !== "posted" && state.posted) {
    if (state.posted === "visit" ? !newSinceVisit(j) : daysAgo(j.posted) > Number(state.posted) - (state.posted === "1" ? 1 : 0)) return false;
  }
  if (state.company && j.company !== state.company) return false;
  if (skip !== "pay" && state.payOnly && !j.pay) return false;
  if (state.hideMandatory && j.mandatory) return false;
  if (state.savedOnly && !saved.has(j.id)) return false;
  if (state.appliedOnly && !applied.has(j.id)) return false;
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

  $("#f-area").replaceChildren(...AREAS.map((a) =>
    chip(t(`area.${a}`), state.areas.has(a), () => { toggle(state.areas, a); update(); }, countWhere("areas", (j) => areaOf(j) === a))));

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

  // "since your last visit" only exists for returning visitors
  const nVisit = lastVisit ? countWhere("posted", newSinceVisit) : 0;
  $("#f-posted").replaceChildren(...POSTED.map((p) =>
    chip(t(`posted.${p}`), state.posted === p, () => { state.posted = p; update(); })),
    nVisit || state.posted === "visit" ? chip(t("posted.visit"), state.posted === "visit", () => { state.posted = "visit"; update(); }, num(nVisit)) : "");

  $("#mySkills").replaceChildren(...state.skills.map((s) =>
    el("button", { type: "button", class: "chip", title: t("remove.skill", { s }), onclick: () => {
      state.skills = state.skills.filter((x) => x !== s); store.set("hsj-skills", state.skills); update();
    } }, s)));

  $("#payCount").textContent = `(${num(countWhere("pay", (j) => Boolean(j.pay)))})`;
  $("#savedCount").textContent = saved.size ? `(${saved.size})` : "";
  $("#appliedCount").textContent = applied.size ? `(${applied.size})` : "";
  $("#hiddenCount").textContent = hidden.size ? `(${hidden.size})` : "";
  $("#hiddenRow").hidden = !hidden.size && !state.showHidden;
}

function activeChips() {
  const out = [];
  const add = (label, off) => out.push(el("button", { type: "button", class: "chip", title: t("remove.filter"), onclick: () => { off(); update(); } }, label));
  if (state.q) add(t("chip.search", { q: state.q }), () => { state.q = ""; $("#q").value = ""; });
  if (state.english) add(t("english.switch"), () => { state.english = false; });
  state.levels.forEach((l) => add(levelName(l), () => state.levels.delete(l)));
  state.speak.forEach((g) => add(t(`speak.${g}`), () => state.speak.delete(g)));
  state.areas.forEach((a) => add(t(`area.${a}`), () => state.areas.delete(a)));
  state.fields.forEach((f) => add(fieldName(f), () => state.fields.delete(f)));
  state.modes.forEach((m) => add(modeName(m), () => state.modes.delete(m)));
  if (state.company) add(t("chip.company", { c: state.company }), () => { state.company = ""; });
  if (state.posted === "visit") add(t("chip.visit"), () => { state.posted = ""; });
  else if (state.posted) add(t("chip.posted", { l: t(`posted.${state.posted}`) }), () => { state.posted = ""; });
  if (state.payOnly) add(t("chip.pay"), () => { state.payOnly = false; $("#payOnly").checked = false; });
  if (state.hideMandatory) add(t("chip.noMandatory"), () => { state.hideMandatory = false; $("#hideMandatory").checked = false; });
  if (state.savedOnly) add(t("chip.saved"), () => { state.savedOnly = false; $("#savedOnly").checked = false; });
  if (state.appliedOnly) add(t("chip.applied"), () => { state.appliedOnly = false; $("#appliedOnly").checked = false; });
  if (state.showHidden) add(t("chip.hidden"), () => { state.showHidden = false; $("#showHidden").checked = false; });
  return out;
}

const tpl = $("#cardTpl");
function card(j) {
  const c = tpl.content.firstElementChild.cloneNode(true);
  const a = c.querySelector(".title a"); a.href = j.url; a.textContent = j.title;
  const co = c.querySelector(".company");
  if (j.company) {
    co.replaceWith(el("button", { type: "button", class: "company", title: t("company.filter", { c: j.company }), onclick: () => {
      state.company = j.company; update(); $("#stage").scrollIntoView({ behavior: "auto" });
    } }, j.company));
  } else co.textContent = t("company.none");
  const av = c.querySelector(".avatar"); av.textContent = initials(j.company); av.style.setProperty("--h", hue(j.company));
  c.querySelector(".loc").textContent = placeOf(j);

  const save = c.querySelector(".save");
  const setSave = () => { const on = saved.has(j.id); save.setAttribute("aria-pressed", String(on)); save.title = on ? t("save.remove") : t("save.add"); };
  setSave();
  save.addEventListener("click", () => { if (!saved.has(j.id)) track("save-job", true); toggle(saved, j.id); store.set("hsj-saved", [...saved]); setSave(); renderFilters(); if (state.savedOnly) update(); });

  const fresh = lastVisit ? newSinceVisit(j) : daysAgo(j.first_seen) <= 1 && daysAgo(j.posted) <= 3;
  const badges = [
    fresh ? el("span", { class: "badge new", title: lastVisit ? t("badge.visit") : null }, t("badge.new")) : null,
    el("span", { class: "badge level" }, levelName(j.level)),
    j.pay ? el("span", { class: "badge pay" }, payText(j.pay)) : null,
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
    detail(j.hours), detail(j.duration), j.start && t("fact.start", { d: detail(j.start) })].filter(Boolean);
  if (hits.size) facts.unshift(hits.size === 1 ? t("fact.matches.one") : t("fact.matches.many", { n: hits.size }));
  c.querySelector(".facts").textContent = facts.join(" · ");
  const view = c.querySelector(".view"); view.href = j.url;
  const opened = () => track("open-ad", true);
  view.addEventListener("click", opened); a.addEventListener("click", opened);
  view.setAttribute("aria-label", t("view.aria", { t: j.title }));
  // JSearch ads open on whichever site Google found them (LinkedIn, StepStone, the employer...)
  const site = j.source === "JSearch" ? j.via || "Google Jobs" : j.source;
  view.firstChild.textContent = (j.source === "Company Site" ? t("view.company") : t("view.source", { s: site })) + " ";
  if (j.source === "Adzuna") c.querySelector(".card-foot").insertBefore(adzunaLabel(), view);

  // personal tracking, kept on this device only
  const ap = c.querySelector(".act.applied");
  const setApplied = () => {
    const on = applied.has(j.id);
    ap.setAttribute("aria-pressed", String(on)); ap.querySelector("span").textContent = on ? t("act.applied") : t("act.markApplied");
    c.classList.toggle("is-applied", on);
  };
  setApplied();
  ap.addEventListener("click", () => {
    toggle(applied, j.id); store.set("hsj-applied", [...applied]); setApplied(); renderFilters();
    if (state.appliedOnly) update(true);
  });

  const sh = c.querySelector(".act.share");
  sh.querySelector("span").textContent = t("act.share");
  sh.addEventListener("click", () => shareJob(j));

  if (FEEDBACK_URL) {
    const rp = c.querySelector(".act.report");
    rp.hidden = false; rp.querySelector("span").textContent = t("act.report"); rp.title = t("act.reportTitle");
    rp.addEventListener("click", () => openFeedback("job", j));
  }

  const hd = c.querySelector(".act.hide");
  const isHidden = hidden.has(j.id);
  hd.querySelector("span").textContent = isHidden ? t("act.unhide") : t("act.hide");
  hd.title = isHidden ? "" : t("act.hideTitle");
  c.classList.toggle("is-hidden", isHidden);
  hd.addEventListener("click", () => {
    const setHidden = (on) => { on ? hidden.add(j.id) : hidden.delete(j.id); store.set("hsj-hidden", [...hidden]); update(true); };
    if (hidden.has(j.id)) { setHidden(false); return; }
    setHidden(true);
    toast(t("toast.hidden"), t("toast.undo"), () => setHidden(false));
  });
  return c;
}

// phones get the system share sheet, desktops a copied link
async function shareJob(j) {
  if (navigator.share && matchMedia("(pointer: coarse)").matches) {
    try { await navigator.share({ title: j.company ? `${j.title} – ${j.company}` : j.title, url: j.url }); return; } catch (e) { if (e.name === "AbortError") return; }
  }
  try { await navigator.clipboard.writeText(j.url); toast(t("act.copied")); } catch (e) { window.prompt(t("act.share"), j.url); }
}

// ---------------------------------------------------------------- feedback form
const fb = { kind: "question", job: null, openedAt: 0 };
function renderKinds() {
  $("#fbKinds").replaceChildren(...FB_KINDS.map((k) =>
    chip(t(`kind.${k}`), fb.kind === k, () => { fb.kind = k; renderKinds(); })));
}
function openFeedback(kind = "question", job = null) {
  Object.assign(fb, { kind, job, openedAt: Date.now() });
  renderKinds();
  const about = $("#fbAbout");
  about.hidden = !job;
  if (job) about.textContent = t("fb.aboutJob", { t: job.company ? `${job.title} – ${job.company}` : job.title });
  $("#fbStatus").textContent = ""; $("#fbStatus").className = "fb-status";
  $("#fbForm").hidden = false; $("#fbSend").disabled = false;
  countChars();
  $("#feedback").showModal();
  $("#fbMessage").focus();
}
function countChars() { $("#fbCount").textContent = t("fb.count", { n: num($("#fbMessage").value.length) }); }
function fbStatus(key, ok) {
  $("#fbStatus").textContent = t(key);
  $("#fbStatus").className = "fb-status " + (ok ? "ok" : "bad");
}
async function sendFeedback(e) {
  e.preventDefault();
  const message = $("#fbMessage").value.trim(), email = $("#fbEmail").value.trim();
  if (message.length < 5) return fbStatus("fb.short");
  if (email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return fbStatus("fb.badEmail");
  $("#fbSend").disabled = true;
  $("#fbStatus").textContent = t("fb.sending"); $("#fbStatus").className = "fb-status";
  const body = { kind: fb.kind, message, email, lang: I18N.lang, website: $("#fbWebsite").value,
    elapsed_ms: Date.now() - fb.openedAt, page: location.pathname + location.search,
    job_id: fb.job ? fb.job.id : "", job_title: fb.job ? `${fb.job.title} – ${fb.job.company || ""}` : "" };
  try {
    const res = await fetch(FEEDBACK_URL, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (res.status === 429) { fbStatus("fb.tooMany"); return; }
    if (!res.ok) throw new Error(res.status);
    $("#fbMessage").value = ""; $("#fbEmail").value = ""; countChars();
    fbStatus(email ? "fb.thanksReply" : "fb.thanks", true);
    track("feedback-sent", true);
  } catch (err) {
    fbStatus("fb.error");
    $("#fbSend").disabled = false;
  }
}
function wireFeedback() {
  if (!FEEDBACK_URL) return;
  $("#feedbackBtn").hidden = false;
  $("#footerFeedback").hidden = false;
  $("#feedbackBtn").addEventListener("click", () => openFeedback("question"));
  document.querySelectorAll("[data-feedback]").forEach((b) => b.addEventListener("click", () => openFeedback(b.dataset.feedback)));
  $("#fbMessage").addEventListener("input", () => {
    countChars();
    if ($("#fbStatus").classList.contains("bad")) { $("#fbStatus").textContent = ""; $("#fbStatus").className = "fb-status"; }
  });
  $("#fbForm").addEventListener("submit", sendFeedback);
}

// ---------------------------------------------------------------- daily job alert by email
// Same Azure Function as the feedback (feedback/Alerts): sign-up -> confirmation email (double opt-in) ->
// one email each morning with the day's new jobs that match the filters saved at sign-up.
const ALERTS_URL = FEEDBACK_URL ? FEEDBACK_URL.replace(/\/feedback$/, "/alerts") : "";
// links in the alert emails: ?alert=confirm|unsubscribe&id=..&t=.. (read once, before the URL is rewritten)
const ALERT_LINK = (() => {
  const p = new URLSearchParams(location.search);
  const action = p.get("alert");
  return ["confirm", "unsubscribe"].includes(action) && p.get("id") && p.get("t") ? { action, id: p.get("id"), t: p.get("t") } : null;
})();
const alertUI = { openedAt: 0 };
// the board's filters that an alert can keep (not sorting, "posted", or personal lists like saved/hidden)
function alertQuery() {
  const p = new URLSearchParams();
  if (state.q) p.set("q", state.q);
  if (state.english) p.set("en", "1");
  if (state.levels.size) p.set("type", [...state.levels].join(","));
  if (state.speak.size) p.set("speak", [...state.speak].join(","));
  if (state.fields.size) p.set("field", [...state.fields].join(","));
  if (state.areas.size) p.set("area", [...state.areas].join(","));
  if (state.modes.size) p.set("mode", [...state.modes].join(","));
  if (state.company) p.set("company", state.company);
  if (state.payOnly) p.set("pay", "1");
  if (state.hideMandatory) p.set("nomandatory", "1");
  return p.toString();
}
function alertSummary() {
  const parts = [];
  if (state.q) parts.push(t("chip.search", { q: state.q }));
  if (state.english) parts.push(t("english.switch"));
  state.levels.forEach((l) => parts.push(levelName(l)));
  state.speak.forEach((g) => parts.push(t(`speak.${g}`)));
  state.areas.forEach((a) => parts.push(t(`area.${a}`)));
  state.fields.forEach((f) => parts.push(fieldName(f)));
  state.modes.forEach((m) => parts.push(modeName(m)));
  if (state.company) parts.push(t("chip.company", { c: state.company }));
  if (state.payOnly) parts.push(t("chip.pay"));
  if (state.hideMandatory) parts.push(t("chip.noMandatory"));
  return parts.join(" · ") || t("alert.all");
}
function alertStatus(id, key, ok, vars) {
  $(id).textContent = key ? t(key, vars) : "";
  $(id).className = "fb-status" + (ok === true ? " ok" : ok === false ? " bad" : "");
}
function openAlert() {
  alertUI.openedAt = Date.now();
  $("#alertTitle").textContent = t("alert.title");
  $("#alertForm").hidden = false; $("#alertAction").hidden = true;
  $("#alertSummary").textContent = alertSummary();
  $("#alertSend").disabled = false;
  alertStatus("#alertStatus", "");
  $("#alertDlg").showModal();
  $("#alertEmail").focus();
}
async function sendAlert(e) {
  e.preventDefault();
  const email = $("#alertEmail").value.trim();
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return alertStatus("#alertStatus", "alert.badEmail", false);
  $("#alertSend").disabled = true;
  alertStatus("#alertStatus", "alert.sending");
  const body = { email, filters: alertQuery(), lang: I18N.lang, website: $("#alertWebsite").value, elapsed_ms: Date.now() - alertUI.openedAt };
  try {
    const res = await fetch(`${ALERTS_URL}/subscribe`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (res.status === 429) { alertStatus("#alertStatus", "alert.tooMany", false); return; }
    if (!res.ok) throw new Error(res.status);
    alertStatus("#alertStatus", "alert.sent", true, { e: email });
    track("alert-signup", true);
  } catch (err) {
    alertStatus("#alertStatus", "alert.error", false);
    $("#alertSend").disabled = false;
  }
}
// the page opened from a link in an alert email: ask before acting, so mail scanners that open links can't confirm or unsubscribe
function openAlertLink(link) {
  const confirm = link.action === "confirm";
  $("#alertTitle").textContent = t(confirm ? "alert.confirmTitle" : "alert.unsubTitle");
  $("#alertForm").hidden = true; $("#alertAction").hidden = false;
  $("#alertActionText").textContent = t(confirm ? "alert.confirmText" : "alert.unsubText");
  $("#alertActionBtn").textContent = t(confirm ? "alert.confirmBtn" : "alert.unsubBtn");
  $("#alertActionBtn").hidden = false; $("#alertActionBtn").disabled = false;
  alertStatus("#alertActionStatus", "");
  $("#alertActionBtn").onclick = async () => {
    $("#alertActionBtn").disabled = true;
    try {
      const res = await fetch(`${ALERTS_URL}/${link.action}`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: link.id, t: link.t }) });
      if ([400, 404, 410].includes(res.status)) { alertStatus("#alertActionStatus", "alert.badLink", false); return; }
      if (!res.ok) throw new Error(res.status);
      const data = await res.json();
      $("#alertActionBtn").hidden = true;
      $("#alertActionText").textContent = "";
      if (confirm) {
        // show the confirmed filters on the board, so the visitor sees what they will get
        history.replaceState(null, "", `?${data.filters || ""}`);
        readURL(); $("#q").value = state.q; syncChecks(); update();
        alertStatus("#alertActionStatus", "alert.confirmed", true, { f: alertSummary() });
      } else alertStatus("#alertActionStatus", "alert.unsubbed", true);
    } catch (err) {
      alertStatus("#alertActionStatus", "alert.error", false);
      $("#alertActionBtn").disabled = false;
    }
  };
  $("#alertDlg").showModal();
}
function wireAlerts() {
  if (!ALERTS_URL) return;
  $("#alertBar").hidden = false;
  $("#alertBtn").addEventListener("click", openAlert);
  $("#alertForm").addEventListener("submit", sendAlert);
  $("#alertEmail").addEventListener("input", () => { if ($("#alertStatus").classList.contains("bad")) alertStatus("#alertStatus", ""); });
}

let toastTimer;
function toast(msg, action, onAction) {
  const box = $("#toast");
  box.replaceChildren(el("span", {}, msg),
    action ? el("button", { type: "button", onclick: () => { box.hidden = true; onAction(); } }, action) : "");
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.hidden = true; }, 6000);
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
  if (state.areas.size) p.set("area", [...state.areas].join(","));
  if (state.modes.size) p.set("mode", [...state.modes].join(","));
  if (state.company) p.set("company", state.company);
  if (state.posted && state.posted !== "visit") p.set("days", state.posted);  // "since last visit" is personal
  if (state.payOnly) p.set("pay", "1");
  if (state.hideMandatory) p.set("nomandatory", "1");
  if (state.sort !== "new") p.set("sort", state.sort);
  const qs = p.toString();
  history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
}
function readURL() {
  const p = new URLSearchParams(location.search);
  const list = (k) => (p.get(k) || "").split(",").filter(Boolean);
  state.q = norm((p.get("q") || "").trim());
  state.english = p.get("en") === "1";
  state.levels = new Set(list("type").filter((l) => LEVELS.includes(l)));
  state.speak = new Set(list("speak").filter((s) => SPEAK.includes(s)));
  state.fields = new Set(list("field"));
  state.areas = new Set(list("area").filter((a) => AREAS.includes(a)));
  state.modes = new Set(list("mode").filter((m) => MODES.includes(m)));
  state.company = p.get("company") || "";
  state.posted = ["1", "7", "30"].includes(p.get("days")) ? p.get("days") : "";
  state.payOnly = p.get("pay") === "1";
  state.hideMandatory = p.get("nomandatory") === "1";
  state.sort = ["new", "match", "company"].includes(p.get("sort")) ? p.get("sort") : "new";
}

// ---------------------------------------------------------------- wiring
// checkbox id -> state key
const CHECKS = [["englishOnly", "english"], ["payOnly", "payOnly"], ["hideMandatory", "hideMandatory"],
  ["savedOnly", "savedOnly"], ["appliedOnly", "appliedOnly"], ["showHidden", "showHidden"]];
function syncChecks() { for (const [id, key] of CHECKS) $(`#${id}`).checked = state[key]; }

function wire() {
  let t;
  $("#q").value = state.q;
  $("#q").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { state.q = norm(e.target.value.trim()); update(); }, 150); });
  syncChecks();
  for (const [id, key] of CHECKS) $(`#${id}`).addEventListener("change", (e) => { state[key] = e.target.checked; update(); });
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

  const reset = () => { Object.assign(state, cleanFilters()); $("#q").value = ""; syncChecks(); update(); };
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
    if (FEEDBACK_URL) { renderKinds(); countChars(); }
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
  const english = JOBS.filter((j) => germanNeed(j) === 0).length;  // same count as the "Only English" filter
  const newToday = JOBS.filter((j) => daysAgo(j.first_seen) === 0).length;
  const nVisit = JOBS.filter((j) => newSinceVisit(j) && !hidden.has(j.id)).length;
  const updated = new Date(data.updated);
  const when = daysAgo(data.updated.slice(0, 10)) === 0
    ? t("hero.updatedToday", { time: updated.toLocaleTimeString(I18N.locale(), { hour: "2-digit", minute: "2-digit" }) })
    : t("stats.updated", { d: updated.toLocaleString(I18N.locale(), { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) });
  $("#heroUpdated").textContent = when;
  $("#heroCta").textContent = t("hero.ctaN", { n: num(JOBS.length) });
  $("#stats").replaceChildren(...[
    el("span", { class: "chip-live" }, el("b", {}, num(JOBS.length)), t("stats.open")),
    el("span", { class: "chip-live" }, el("b", {}, num(english)), t("stats.english")),
    newToday && newToday < JOBS.length ? el("span", { class: "chip-live" }, el("b", {}, num(newToday)), t("stats.new")) : null,
    nVisit ? el("span", { class: "chip-live" }, el("b", {}, num(nVisit)), t("stats.visit")) : null,
  ].filter(Boolean));
  renderQuick();
  renderRail();
}

// ---------------------------------------------------------------- intro shortcuts
// each one starts from a clean board with a single filter, then scrolls down to the results
function jumpTo(apply) {
  Object.assign(state, cleanFilters());
  $("#q").value = "";
  apply();
  syncChecks();
  update();
  $("#stage").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
}
function renderQuick() {
  const n = (pred) => num(JOBS.filter(pred).length);
  const q = (label, count, apply) => el("button", { type: "button", onclick: () => jumpTo(apply) }, label, el("span", { class: "n" }, count));
  $("#heroQuick").replaceChildren(
    q(t("speak.en"), n((j) => speakOf(j) === "en"), () => state.speak.add("en")),
    q(levelName("Werkstudent"), n((j) => j.level === "Werkstudent"), () => state.levels.add("Werkstudent")),
    q(levelName("Internship"), n((j) => j.level === "Internship"), () => state.levels.add("Internship")),
    q(levelName("Thesis"), n((j) => j.level === "Thesis"), () => state.levels.add("Thesis")),
    q(t("hero.quickWeek"), n((j) => daysAgo(j.posted) <= 7), () => { state.posted = "7"; }),
  );
}

// ---------------------------------------------------------------- knowledge rail
const ICON = {
  pulse: '<path d="M3 12h4l2-6 4 12 2-6h6"/>',
  types: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 13h18"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.7 3.8 5.7 3.8 9s-1.3 6.3-3.8 9c-2.5-2.7-3.8-5.7-3.8-9S9.5 5.7 12 3z"/>',
  tips: '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z"/>',
};
function infoCard(icon, title, ...body) {
  const h = el("h3", {}); h.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[icon]}</svg>`; h.append(title);
  return el("section", { class: "info-card" }, h, ...body);
}
// trusted markup from i18n.js only
const html = (key) => { const d = el("div"); d.innerHTML = t(key); return [...d.childNodes]; };
function topList(entries, onpick, label) {
  const max = entries[0] ? entries[0][1] : 1;
  return el("ul", { class: "bars" }, entries.map(([k, n]) => {
    const bar = el("span", { class: "bar" }, el("i", { style: `width:${Math.max(4, (n / max) * 100)}%` }));
    return el("li", {}, el("button", { type: "button", onclick: () => jumpTo(() => onpick(k)) },
      el("span", { class: "name" }, label(k)), el("span", { class: "n" }, num(n)), bar));
  }));
}
function renderRail() {
  const count = (key) => { const m = new Map(); JOBS.forEach((j) => { const k = key(j); if (k) m.set(k, (m.get(k) || 0) + 1); }); return [...m].sort((a, b) => b[1] - a[1]); };
  const week = JOBS.filter((j) => daysAgo(j.posted) <= 7).length;  // posting date: first_seen is the board's own history
  const flexible = JOBS.filter((j) => j.work_mode === "Remote" || j.work_mode === "Hybrid").length;
  const english = JOBS.filter((j) => speakOf(j) === "en").length;
  const companies = count((j) => j.company).slice(0, 6);
  const fields = count((j) => j.field !== "Other" && j.field).slice(0, 6);
  const fact = (v, k) => el("div", {}, el("div", { class: "v" }, v), el("div", { class: "k" }, k));
  const pct = JOBS.length ? Math.round((english / JOBS.length) * 100) : 0;

  $("#rail").replaceChildren(
    el("div", { class: "rail-title" }, t("rail.title")),
    infoCard("pulse", t("rail.nowTitle"),
      el("div", { class: "kfacts" },
        fact(num(week), t("rail.newWeek")), fact(`${pct} %`, t("rail.onlyEnglish")),
        fact(num(flexible), t("rail.flexible")), fact(num(count((j) => j.company).length), t("rail.employers"))),
      el("p", {}, el("b", {}, t("rail.topCompanies"))),
      topList(companies, (c) => { state.company = c; }, (c) => c),
      el("p", { style: "margin-top:12px" }, el("b", {}, t("rail.topFields"))),
      topList(fields, (f) => state.fields.add(f), fieldName)),
    infoCard("types", t("rail.typesTitle"), el("dl", { class: "types" }, ...html("rail.types")),
      el("p", { class: "small-print" }, t("rail.legal"))),
    infoCard("globe", t("rail.intlTitle"), ...html("rail.intl")),
    infoCard("tips", t("rail.tipsTitle"), ...html("rail.tips")),
  );
}

async function main() {
  I18N.init();
  readURL();
  wire();
  wireFeedback();
  wireAlerts();
  if (ALERT_LINK && ALERTS_URL) openAlertLink(ALERT_LINK);
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
    // a shared link with filters goes straight to the results instead of the intro
    if (!ALERT_LINK && [...new URLSearchParams(location.search).keys()].some((k) => k !== "lang")) {
      $("#stage").scrollIntoView({ behavior: "auto" });
    }
  } catch (e) {
    // opened by double-click (file://): browsers block loading data/jobs.json that way
    $("#resultCount").textContent = location.protocol === "file:" ? t("loadErrorFile") : t("loadError");
  }
}
track("/");
main();
