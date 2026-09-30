"""Daily job alerts by email: sign-up with double opt-in, unsubscribe, and the morning digest.

Table `alerts` (same storage account as the feedback), PartitionKey "sub", RowKey = hash of the email address:
  email, lang, filters     the board's query string ("type=Werkstudent&speak=en"), checked against KNOWN keys
  status                   "pending" until the link in the confirmation email is used, then "active"
  token                    secret in every digest's unsubscribe link (made at confirmation)
  confirm_token / confirm_expires / pending_filters / pending_lang
                           a sign-up waiting for confirmation (also used to change the filters of an active alert,
                           so nobody can change or start someone else's alert without access to their inbox)
  created, confirmed       timestamps; `confirmed` is the proof of consent (double opt-in)
  last_sent, sent_count    date of the last digest check, number of digests sent
  mails_day, mails_count   confirmation emails sent to this address today (max CONFIRMS_PER_DAY)

Unsubscribing deletes the row. Sign-ups that are never confirmed are deleted after PENDING_DAYS by Purge.
"""
import hashlib
import hmac
import html
import json
import logging
import os
import re
import secrets
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode

from . import store

SITE = os.environ.get("SITE_URL", "https://hamburgstudentjobs.de").rstrip("/")
PENDING_DAYS = 7
CONFIRMS_PER_DAY = 3        # confirmation emails to one address per day (stops using the form to flood an inbox)
MAX_LISTED = 20             # jobs written into one digest; the rest are one click away on the site
PK = "sub"

LEVELS = ["Werkstudent", "Internship", "Thesis", "Student side job", "Junior / Trainee"]
SPEAK = ["en", "both", "de"]
AREAS = ["hh", "around", "remote"]
MODES = ["Remote", "Hybrid", "Onsite", "Not stated"]
FIELDS = ["Data & Analytics", "Software & IT", "Engineering", "Marketing & Communications", "Sales & Business Development",
          "Finance & Controlling", "HR & Recruiting", "Operations & Logistics", "Consulting & Strategy", "Product & Design",
          "Research & Science", "Healthcare & Social", "Legal", "Media & Content", "Other"]


# ---------------------------------------------------------------- filters (mirror of passes() in docs/app.js)
def norm(s):
    return "".join(c for c in unicodedata.normalize("NFKD", (s or "").lower()) if not unicodedata.combining(c))


def parse_filters(qs):
    """Query string from the site -> clean dict. Unknown keys and values are dropped, never stored."""
    p = {k: v[0] for k, v in parse_qs(str(qs or "").lstrip("?"), keep_blank_values=False).items()}
    lst = lambda k, allowed: [x for x in dict.fromkeys((p.get(k) or "").split(",")) if x in allowed]
    f = {"q": norm(p.get("q", "").strip())[:80], "en": p.get("en") == "1",
         "type": lst("type", LEVELS), "speak": lst("speak", SPEAK), "field": lst("field", FIELDS),
         "area": lst("area", AREAS), "mode": lst("mode", MODES), "company": (p.get("company") or "").strip()[:120],
         "pay": p.get("pay") == "1", "nomandatory": p.get("nomandatory") == "1"}
    return f


def filters_qs(f):
    """Canonical query string (same keys the site's writeURL() produces)."""
    out = []
    if f["q"]: out.append(("q", f["q"]))
    if f["en"]: out.append(("en", "1"))
    for k in ("type", "speak", "field", "area", "mode"):
        if f[k]: out.append((k, ",".join(f[k])))
    if f["company"]: out.append(("company", f["company"]))
    if f["pay"]: out.append(("pay", "1"))
    if f["nomandatory"]: out.append(("nomandatory", "1"))
    return urlencode(out)


def german_need(j):
    if j.get("ai"):
        if j.get("german_level") in ("none", "not stated"):
            return 2 if j.get("lang") == "DE" else 0
        return 1 if j.get("german_level") == "basic" else 2
    return 2 if j.get("german") == "required" else 1 if j.get("german") == "a plus" else 0


def speak_of(j):
    need = german_need(j)
    if j.get("ai"):
        english = j.get("english_level") not in ("none", "not stated") or j.get("lang") == "EN"
    else:
        english = j.get("lang") == "EN" or bool(j.get("english") and j.get("english") != "not mentioned")
    return "en" if need == 0 else "both" if need == 1 else ("both" if english else "de")


def area_of(j):
    loc = j.get("location") or "Hamburg"
    if re.match(r"remote\b", loc, re.I):
        return "remote"
    inside = re.search(r"hamburg", loc, re.I) and not re.search(r"\bbei hamburg|\bbz\.? hamburg|^hamburg \((?!\d)", loc, re.I)
    return "hh" if inside else "around"


def matches(j, f):
    if f["q"]:
        hay = norm(" ".join([j.get("title", ""), j.get("company", ""), j.get("field", ""), j.get("location", ""),
                             *(j.get("skills") or []), j.get("summary", "")]))
        if not all(w in hay for w in f["q"].split()):
            return False
    if f["en"] and german_need(j) == 2: return False
    if f["type"] and j.get("level") not in f["type"]: return False
    if f["speak"] and speak_of(j) not in f["speak"]: return False
    if f["area"] and area_of(j) not in f["area"]: return False
    if f["field"] and j.get("field") not in f["field"]: return False
    if f["mode"] and (j.get("work_mode") or "Not stated") not in f["mode"]: return False
    if f["company"] and j.get("company") != f["company"]: return False
    if f["pay"] and not j.get("pay"): return False
    if f["nomandatory"] and j.get("mandatory"): return False
    return True


# ---------------------------------------------------------------- texts (EN / DE)
T = {
    "en": {
        "level": {"Werkstudent": "Werkstudent", "Internship": "Internship", "Thesis": "Thesis",
                  "Student side job": "Student side job", "Junior / Trainee": "Junior / Trainee"},
        "speak": {"en": "Only English", "both": "English and German", "de": "Only German"},
        "area": {"hh": "Hamburg", "around": "Around Hamburg", "remote": "Remote in Germany"},
        "mode": {"Remote": "Remote", "Hybrid": "Hybrid", "Onsite": "On-site", "Not stated": "Work mode not stated"},
        "field": {}, "en": "English is enough", "pay": "Pay stated", "nomandatory": "No mandatory-only internships",
        "search": "Search: “{q}”", "company": "Company: {c}", "all": "all new jobs (no filters)",
        "c_subject": "Please confirm your job alert – Hamburg Student Jobs",
        "c_intro": "Someone (hopefully you) asked for a daily email with new student jobs in Hamburg on hamburgstudentjobs.de.",
        "c_filters": "Your filters:",
        "c_button": "Yes, send me the daily alert",
        "c_after": "The link works for 7 days. If you didn't ask for this, just ignore this email: nothing will be sent and your address is deleted after 7 days.",
        "d_subject_one": "1 new student job for you – Hamburg Student Jobs",
        "d_subject": "{n} new student jobs for you – Hamburg Student Jobs",
        "d_intro_one": "1 new job matches your filters today.",
        "d_intro": "{n} new jobs match your filters today.",
        "d_more": "…and {n} more. See all of today's matches",
        "d_all": "See them on the site",
        "d_why": "You get this email because you signed up for a daily job alert on hamburgstudentjobs.de. Your filters: {f}.",
        "d_change": "To change your filters, set new ones on the site and sign up again with the same address.",
        "unsub": "Unsubscribe",
        "no_company": "Company not named",
        "view": "View ad",
    },
    "de": {
        "level": {"Werkstudent": "Werkstudent", "Internship": "Praktikum", "Thesis": "Abschlussarbeit",
                  "Student side job": "Studentenjob", "Junior / Trainee": "Einstieg / Trainee"},
        "speak": {"en": "Nur Englisch", "both": "Englisch und Deutsch", "de": "Nur Deutsch"},
        "area": {"hh": "Hamburg", "around": "Hamburger Umland", "remote": "Remote in Deutschland"},
        "mode": {"Remote": "Remote", "Hybrid": "Hybrid", "Onsite": "Vor Ort", "Not stated": "Arbeitsort ohne Angabe"},
        "field": {"Data & Analytics": "Daten & Analyse", "Software & IT": "Software & IT", "Engineering": "Ingenieurwesen & Technik",
                  "Marketing & Communications": "Marketing & Kommunikation", "Sales & Business Development": "Vertrieb & Business Development",
                  "Finance & Controlling": "Finanzen & Controlling", "HR & Recruiting": "Personal & Recruiting",
                  "Operations & Logistics": "Operations & Logistik", "Consulting & Strategy": "Beratung & Strategie",
                  "Product & Design": "Produkt & Design", "Research & Science": "Forschung & Wissenschaft",
                  "Healthcare & Social": "Gesundheit & Soziales", "Legal": "Recht", "Media & Content": "Medien & Content",
                  "Other": "Sonstiges"},
        "en": "Englisch reicht", "pay": "Mit Gehaltsangabe", "nomandatory": "Ohne reine Pflichtpraktika",
        "search": "Suche: „{q}“", "company": "Firma: {c}", "all": "alle neuen Jobs (keine Filter)",
        "c_subject": "Bitte bestätige deinen Job-Alarm – Hamburg Student Jobs",
        "c_intro": "Jemand (hoffentlich du) möchte auf hamburgstudentjobs.de jeden Morgen eine E-Mail mit neuen Studentenjobs in Hamburg bekommen.",
        "c_filters": "Deine Filter:",
        "c_button": "Ja, schick mir den täglichen Job-Alarm",
        "c_after": "Der Link gilt 7 Tage. Wenn du das nicht warst, ignoriere diese E-Mail einfach: Es wird nichts verschickt und deine Adresse nach 7 Tagen gelöscht.",
        "d_subject_one": "1 neuer Studentenjob für dich – Hamburg Student Jobs",
        "d_subject": "{n} neue Studentenjobs für dich – Hamburg Student Jobs",
        "d_intro_one": "Heute passt 1 neuer Job zu deinen Filtern.",
        "d_intro": "Heute passen {n} neue Jobs zu deinen Filtern.",
        "d_more": "…und {n} weitere. Alle heutigen Treffer ansehen",
        "d_all": "Auf der Seite ansehen",
        "d_why": "Du bekommst diese E-Mail, weil du auf hamburgstudentjobs.de einen täglichen Job-Alarm bestellt hast. Deine Filter: {f}.",
        "d_change": "Um die Filter zu ändern, stell auf der Seite neue ein und melde dich mit derselben Adresse noch einmal an.",
        "unsub": "Abmelden",
        "no_company": "Firma nicht genannt",
        "view": "Zur Anzeige",
    },
}


def summary(f, lang):
    t = T[lang]
    parts = []
    if f["q"]: parts.append(t["search"].format(q=f["q"]))
    if f["en"]: parts.append(t["en"])
    parts += [t["level"][x] for x in f["type"]] + [t["speak"][x] for x in f["speak"]] + [t["area"][x] for x in f["area"]]
    parts += [t["field"].get(x, x) for x in f["field"]] + [t["mode"][x] for x in f["mode"]]
    if f["company"]: parts.append(t["company"].format(c=f["company"]))
    if f["pay"]: parts.append(t["pay"])
    if f["nomandatory"]: parts.append(t["nomandatory"])
    return " · ".join(parts) or t["all"]


# ---------------------------------------------------------------- email sending
def sender():
    """Alerts use their own ACS resource + sender (custom domain); falls back to the feedback's ACS for tests."""
    conn = os.environ.get("ALERT_ACS_CONNECTION_STRING") or os.environ.get("ACS_CONNECTION_STRING")
    addr = os.environ.get("ALERT_SENDER") or os.environ.get("ACS_SENDER")
    return conn, addr


OUTBOX = []  # FEEDBACK_STORE=memory: emails are collected here instead of sent (tests)


def send(to, subject, text, html_body, headers=None):
    msg = {"recipients": {"to": [{"address": to}]},
           "content": {"subject": subject, "plainText": text, "html": html_body}}
    if headers:
        msg["headers"] = headers
    if os.environ.get("FEEDBACK_STORE") == "memory":
        OUTBOX.append(msg)
        logging.info("[memory mode, not sent] to %s: %s | %s", to, subject, " ".join(text.split()))
        return
    conn, addr = sender()
    if not (conn and addr):
        raise RuntimeError("ALERT_ACS_CONNECTION_STRING / ALERT_SENDER are not set")
    msg["senderAddress"] = addr
    from azure.communication.email import EmailClient
    EmailClient.from_connection_string(conn).begin_send(msg)


def page(inner, lang):
    """Minimal, inline-styled HTML that survives Gmail/Outlook/Proton."""
    return (f'<!doctype html><html lang="{lang}"><body style="margin:0;padding:0;background:#f4f6f8">'
            '<div style="max-width:600px;margin:0 auto;padding:24px 16px;font-family:Segoe UI,Helvetica,Arial,sans-serif;'
            'font-size:15px;line-height:1.5;color:#1d2433">'
            '<p style="margin:0 0 18px;font-weight:700;font-size:17px;color:#0f766e">Hamburg Student Jobs</p>'
            f'{inner}</div></body></html>')


def links(row_id, token, lang):
    q = urlencode({"alert": "unsubscribe", "id": row_id, "t": token, "lang": lang})
    api = os.environ.get("ALERT_API_URL", "").rstrip("/")
    one_click = f"{api}/unsubscribe?{urlencode({'id': row_id, 't': token})}" if api else ""
    return f"{SITE}/?{q}", one_click


def confirm_email(row, lang):
    t, f = T[lang], parse_filters(row["pending_filters"])
    url = f"{SITE}/?{urlencode({'alert': 'confirm', 'id': row['RowKey'], 't': row['confirm_token'], 'lang': lang})}"
    s = html.escape(summary(f, lang))
    inner = (f"<p>{html.escape(t['c_intro'])}</p><p><b>{html.escape(t['c_filters'])}</b> {s}</p>"
             f'<p style="margin:24px 0"><a href="{html.escape(url)}" style="background:#0f766e;color:#fff;text-decoration:none;'
             f'padding:12px 20px;border-radius:8px;font-weight:700;display:inline-block">{html.escape(t["c_button"])}</a></p>'
             f'<p style="color:#5b6475;font-size:13px">{html.escape(t["c_after"])}</p>')
    text = f"{t['c_intro']}\n\n{t['c_filters']} {summary(f, lang)}\n\n{t['c_button']}:\n{url}\n\n{t['c_after']}\n"
    send(row["email"], t["c_subject"], text, page(inner, lang))


def digest_email(row, jobs, lang):
    t, f = T[lang], parse_filters(row["filters"])
    n = len(jobs)
    unsub, one_click = links(row["RowKey"], row["token"], lang)
    board = f"{SITE}/?{filters_qs(f)}{'&' if filters_qs(f) else ''}days=1&lang={lang}"
    items_h, items_t = [], []
    for j in jobs[:MAX_LISTED]:
        co = j.get("company") or t["no_company"]
        bits = [t["level"].get(j.get("level"), j.get("level", "")), t["speak"][speak_of(j)], j.get("location") or "Hamburg"]
        if j.get("pay"):
            bits.append(j["pay"])
        meta = " · ".join(b for b in bits if b)
        items_h.append(f'<li style="margin:0 0 14px"><a href="{html.escape(j["url"])}" style="color:#0f766e;font-weight:700;'
                       f'text-decoration:none">{html.escape(j["title"])}</a><br><span>{html.escape(co)}</span><br>'
                       f'<span style="color:#5b6475;font-size:13px">{html.escape(meta)}</span></li>')
        items_t.append(f"- {j['title']}\n  {co} · {meta}\n  {j['url']}")
    more = t["d_more"].format(n=n - MAX_LISTED) if n > MAX_LISTED else t["d_all"]
    intro = t["d_intro_one"] if n == 1 else t["d_intro"].format(n=n)
    why = t["d_why"].format(f=summary(f, lang))
    inner = (f"<p>{html.escape(intro)}</p><ul style=\"padding-left:18px\">{''.join(items_h)}</ul>"
             f'<p><a href="{html.escape(board)}" style="color:#0f766e">{html.escape(more)} →</a></p>'
             f'<hr style="border:0;border-top:1px solid #dde2ea;margin:24px 0">'
             f'<p style="color:#5b6475;font-size:13px">{html.escape(why)} {html.escape(t["d_change"])}<br>'
             f'<a href="{html.escape(unsub)}" style="color:#5b6475">{html.escape(t["unsub"])}</a></p>')
    text = (f"{intro}\n\n" + "\n\n".join(items_t) + f"\n\n{more}: {board}\n\n-- \n{why} {t['d_change']}\n{t['unsub']}: {unsub}\n")
    headers = {"List-Unsubscribe": f"<{one_click}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"} if one_click else None
    subject = t["d_subject_one"] if n == 1 else t["d_subject"].format(n=n)
    send(row["email"], subject, text, page(inner, lang), headers)


# ---------------------------------------------------------------- sign-up, confirm, unsubscribe
def row_id(email):
    salt = os.environ.get("RATE_SALT", "")
    return hashlib.sha256(f"{salt}|alert|{email}".encode()).hexdigest()[:40]


def subscribe(body, headers, now=None):
    """POST /api/alerts/subscribe. Always answers the same way whether the address is new or known."""
    now = now or datetime.now(timezone.utc)
    origin = (headers.get("origin") or "").rstrip("/")
    if origin not in store.allowed_origins():
        raise store.Rejected(403, "origin not allowed")
    if not isinstance(body, dict):
        raise store.Rejected(400, "expected a JSON object")
    if str(body.get("website") or "").strip():
        return None
    try:
        if int(body.get("elapsed_ms") or 0) < 1500:
            return None
    except (TypeError, ValueError):
        raise store.Rejected(400, "bad elapsed_ms")
    email = str(body.get("email") or "").strip().lower()
    if len(email) > 200 or not store.EMAIL.match(email):
        raise store.Rejected(400, "email looks wrong")
    lang = "de" if body.get("lang") == "de" else "en"
    filters = filters_qs(parse_filters(body.get("filters")))
    store.check_rate(store.client_ip(headers), now, scope="alert")

    t, rid, day = store.tables(), row_id(email), now.strftime("%Y-%m-%d")
    row = t.get("alerts", PK, rid) or {"PartitionKey": PK, "RowKey": rid, "email": email, "status": "pending",
                                       "created": now.isoformat(timespec="seconds"), "sent_count": 0}
    if row.get("mails_day") != day:
        row["mails_day"], row["mails_count"] = day, 0
    if row["mails_count"] >= CONFIRMS_PER_DAY:
        return row  # quietly: same answer, no email
    row.update(pending_filters=filters, pending_lang=lang, confirm_token=secrets.token_urlsafe(24),
               confirm_expires=(now + timedelta(days=PENDING_DAYS)).isoformat(timespec="seconds"),
               mails_count=row["mails_count"] + 1)
    t.upsert("alerts", row)
    confirm_email(row, lang)
    return row


def _row_for(rid, token, field):
    if not (isinstance(rid, str) and isinstance(token, str) and re.fullmatch(r"[0-9a-f]{40}", rid) and 10 < len(token) < 80):
        raise store.Rejected(400, "bad link")
    row = store.tables().get("alerts", PK, rid)
    if not row or not row.get(field) or not hmac.compare_digest(row[field], token):
        raise store.Rejected(404, "link not valid")
    return row


def confirm(body, now=None):
    """POST /api/alerts/confirm {id, t}: activates the alert (or applies changed filters)."""
    now = now or datetime.now(timezone.utc)
    row = _row_for(body.get("id"), body.get("t"), "confirm_token")
    if row["confirm_expires"] < now.isoformat(timespec="seconds"):
        raise store.Rejected(410, "link expired")
    row.update(filters=row["pending_filters"], lang=row["pending_lang"], status="active",
               confirmed=now.isoformat(timespec="seconds"), token=row.get("token") or secrets.token_urlsafe(24),
               confirm_token="", pending_filters="", pending_lang="", confirm_expires="")
    store.tables().upsert("alerts", row)
    return {"filters": row["filters"], "lang": row["lang"]}


def unsubscribe(body):
    """POST /api/alerts/unsubscribe {id, t} (site button) or ?id=&t= (one-click from the mail program).
    The token of a digest or of a pending confirmation both work. Deletes the row."""
    rid, token = body.get("id"), body.get("t")
    try:
        row = _row_for(rid, token, "token")
    except store.Rejected:
        row = _row_for(rid, token, "confirm_token")
    store.tables().delete("alerts", PK, row["RowKey"])
    return True


# ---------------------------------------------------------------- the morning digest
def load_jobs():
    url = f"{SITE}/data/jobs.json?t={secrets.token_hex(4)}"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "hsj-alerts"}), timeout=60) as r:
        return json.load(r)


def digest(now=None, data=None, limit=None):
    """Timer, several times each morning. Waits until today's data is published, then checks every active
    alert once per day; sends at most `limit` emails per run (email-service rate limits), the rest next run."""
    now = now or datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    limit = limit or int(os.environ.get("DIGEST_MAX_PER_RUN", "25"))
    data = data or load_jobs()
    if not str(data.get("updated", "")).startswith(day):
        return {"waiting": True, "sent": 0, "checked": 0}
    fresh = [j for j in data["jobs"] if j.get("first_seen") == day]
    fresh.sort(key=lambda j: j.get("posted") or "", reverse=True)
    t, sent, checked = store.tables(), 0, 0
    for row in t.query("alerts", PK):
        if row.get("status") != "active" or row.get("last_sent") == day:
            continue
        if sent >= limit:
            break
        f = parse_filters(row.get("filters"))
        hits = [j for j in fresh if matches(j, f)]
        checked += 1
        if hits:
            digest_email(row, hits, row.get("lang") or "en")
            row["sent_count"] = int(row.get("sent_count") or 0) + 1
            sent += 1
        row["last_sent"] = day  # checked today, with or without an email: no second email today
        t.upsert("alerts", row)
    return {"waiting": False, "sent": sent, "checked": checked, "new_jobs": len(fresh)}


def purge_pending(now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=PENDING_DAYS)).isoformat(timespec="seconds")
    t, n = store.tables(), 0
    for row in list(t.query("alerts", PK)):
        if row.get("status") == "pending" and row.get("created", "") < cutoff:
            t.delete("alerts", PK, row["RowKey"])
            n += 1
    return n
