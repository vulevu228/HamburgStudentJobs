"""Offline tests for the job alerts (no Azure, no emails sent): python feedback/test_alerts.py"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

os.environ["FEEDBACK_STORE"] = "memory"
os.environ["ALLOWED_ORIGINS"] = "https://hamburgstudentjobs.de"
os.environ["RATE_SALT"] = "test-salt"
os.environ["ALERT_API_URL"] = "https://example.azurewebsites.net/api/alerts"
sys.path.insert(0, str(Path(__file__).parent))
from shared_code import alerts, store  # noqa: E402

H = {"origin": "https://hamburgstudentjobs.de", "x-forwarded-for": "203.0.113.9:4444"}
NOW = datetime(2026, 9, 30, 6, 0, tzinfo=timezone.utc)
SIGNUP = {"email": " Student@Example.org ", "filters": "type=Werkstudent&speak=en,both&sort=match&days=7&evil=1",
          "lang": "de", "elapsed_ms": 4000}
t, out = store.tables(), alerts.OUTBOX


def rejected(status, fn, *a):
    try:
        fn(*a)
    except store.Rejected as e:
        assert e.status == status, (e.status, e.reason)
        return
    raise AssertionError(f"expected {status}")


def link(msg):
    """The confirm / unsubscribe link in an email's plain text -> its query parameters."""
    url = next(w for w in msg["content"]["plainText"].split() if w.startswith("https://hamburgstudentjobs.de/?alert="))
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


# ---- filters: unknown keys/values dropped, sort/days not stored
f = alerts.parse_filters(SIGNUP["filters"])
assert alerts.filters_qs(f) == "type=Werkstudent&speak=en%2Cboth", alerts.filters_qs(f)
assert alerts.parse_filters("type=Boss&speak=xx&q=  Daten  ")["type"] == [] and alerts.parse_filters("q=Daten")["q"] == "daten"
assert alerts.summary(f, "de") == "Werkstudent · Nur Englisch · Englisch und Deutsch"
assert alerts.summary(alerts.parse_filters(""), "en") == "all new jobs (no filters)"

# ---- sign-up -> pending + one confirmation email, no digest yet
row = alerts.subscribe(SIGNUP, H, NOW)
assert row["status"] == "pending" and row["email"] == "student@example.org" and len(out) == 1
assert out[0]["recipients"]["to"][0]["address"] == "student@example.org"
assert "bestätige" in out[0]["content"]["subject"] and "Nur Englisch" in out[0]["content"]["html"]
assert "203.0.113.9" not in str(t.rows)

# bots and bad input
assert alerts.subscribe({**SIGNUP, "website": "x"}, H, NOW) is None and alerts.subscribe({**SIGNUP, "elapsed_ms": 200}, H, NOW) is None
rejected(403, alerts.subscribe, SIGNUP, {**H, "origin": "https://evil.example"}, NOW)
rejected(400, alerts.subscribe, {**SIGNUP, "email": "not-an-email"}, H, NOW)
assert len(out) == 1

# ---- confirm: wrong token / expired rejected; right token activates
p = link(out[0])
assert p["alert"] == "confirm" and p["lang"] == "de"
rejected(404, alerts.confirm, {"id": p["id"], "t": "x" * 32}, NOW)
rejected(400, alerts.confirm, {"id": "../etc", "t": p["t"]}, NOW)
rejected(410, alerts.confirm, {"id": p["id"], "t": p["t"]}, NOW + timedelta(days=8))
res = alerts.confirm({"id": p["id"], "t": p["t"]}, NOW)
assert res["filters"] == "type=Werkstudent&speak=en%2Cboth"
row = t.get("alerts", "sub", p["id"])
assert row["status"] == "active" and row["confirmed"] and row["token"] and not row["confirm_token"]
rejected(404, alerts.confirm, {"id": p["id"], "t": p["t"]}, NOW)   # a confirm link works once

# ---- at most 3 confirmation emails a day to one address, same answer either way
out.clear()
for _ in range(5):
    alerts.subscribe({**SIGNUP, "filters": "type=Internship"}, {**H, "x-forwarded-for": f"198.51.100.{_}"}, NOW)
assert len(out) == 2, len(out)  # the first sign-up above already used 1 of the 3
# a new sign-up for an active address does not change its filters until confirmed
assert t.get("alerts", "sub", p["id"])["filters"] == "type=Werkstudent&speak=en%2Cboth"

# ---- per-IP limit (separate from the feedback form's)
out.clear()
ip = {**H, "x-forwarded-for": "192.0.2.50"}
for i in range(5):
    alerts.subscribe({**SIGNUP, "email": f"a{i}@example.org"}, ip, NOW)
rejected(429, alerts.subscribe, {**SIGNUP, "email": "a9@example.org"}, ip, NOW)

# ---- digest
day = NOW.strftime("%Y-%m-%d")
J = lambda **k: {"id": k.get("id", "x"), "title": "Werkstudent Data", "company": "ACME", "location": "Hamburg", "url": "https://ex.org/1",
                 "level": "Werkstudent", "field": "Data & Analytics", "german": "not mentioned", "lang": "EN",
                 "english": "required", "skills": [], "first_seen": day, "posted": day, **k}
data = {"updated": day + "T05:06+00:00", "jobs": [
    J(id="a"), J(id="b", title="Werkstudent Vertrieb", german="required", lang="DE", english="not mentioned"),
    J(id="c", level="Internship"), J(id="d", first_seen="2026-09-29"), J(id="e", german="a plus", pay="15 EUR/h")]}
out.clear()
assert alerts.digest(NOW, {"updated": "2026-09-29T05:00+00:00", "jobs": []})["waiting"] is True
r = alerts.digest(NOW, data)
assert r["sent"] == 1 and r["checked"] == 1, r        # the pending a0..a4 sign-ups get nothing
msg = out[-1]
assert msg["recipients"]["to"][0]["address"] == "student@example.org"
assert msg["content"]["subject"].startswith("2 neue Studentenjobs"), msg["content"]["subject"]  # a + e (b is only German, c internship, d old)
assert "15 EUR/h" in msg["content"]["html"] and "Vertrieb" not in msg["content"]["html"]
assert msg["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
assert "example.azurewebsites.net/api/alerts/unsubscribe?id=" in msg["headers"]["List-Unsubscribe"]
assert alerts.digest(NOW, data)["sent"] == 0              # never twice a day
# no matches -> no email, but marked as checked
alerts.digest(NOW + timedelta(days=1), {"updated": "2026-10-01T05:00+00:00", "jobs": [J(id="z", level="Thesis", first_seen="2026-10-01")]})
assert len(out) == 1 and t.get("alerts", "sub", p["id"])["last_sent"] == "2026-10-01"

# HTML escaping of job data
out.clear()
t.upsert("alerts", {**t.get("alerts", "sub", p["id"]), "last_sent": ""})
alerts.digest(NOW, {"updated": day, "jobs": [J(id="x", title="<script>alert(1)</script>", url='https://ex.org/"><b>')]})
assert "<script>" not in out[-1]["content"]["html"] and "&lt;script&gt;" in out[-1]["content"]["html"]

# send limit per run
for i in range(30):
    t.upsert("alerts", {"PartitionKey": "sub", "RowKey": f"{i:040x}", "email": f"u{i}@ex.org", "status": "active", "token": "tok" * 5,
                        "filters": "", "lang": "en", "sent_count": 0})
out.clear()
assert alerts.digest(NOW, data, limit=10)["sent"] == 10 and alerts.digest(NOW, data, limit=10)["sent"] == 10 and len(out) == 20

# ---- unsubscribe: digest link deletes the row; bad token rejected
u = link(out[0])
assert u["alert"] == "unsubscribe"
rejected(404, alerts.unsubscribe, {"id": u["id"], "t": "y" * 20})
assert alerts.unsubscribe({"id": u["id"], "t": u["t"]}) and t.get("alerts", "sub", u["id"]) is None
rejected(404, alerts.unsubscribe, {"id": u["id"], "t": u["t"]})

# ---- purge: unconfirmed sign-ups older than 7 days go, active ones stay
n_before = len(t.rows["alerts"])
assert alerts.purge_pending(NOW + timedelta(days=8)) == 5          # a0..a4
assert len(t.rows["alerts"]) == n_before - 5 and t.get("alerts", "sub", p["id"])["status"] == "active"

print("all alert tests passed")
