"""Offline tests for the feedback function (no Azure needed): python feedback/test_local.py"""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ["FEEDBACK_STORE"] = "memory"
os.environ["ALLOWED_ORIGINS"] = "https://hamburgstudentjobs.de"
os.environ["RATE_SALT"] = "test-salt"
sys.path.insert(0, str(Path(__file__).parent))
from shared_code import store  # noqa: E402

store.time.sleep = lambda s: None
H = {"origin": "https://hamburgstudentjobs.de", "x-forwarded-for": "203.0.113.7:51234, 10.0.0.1"}
GOOD = {"kind": "idea", "message": "Please add a filter for hours per week.", "elapsed_ms": 9000, "lang": "de"}
NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


def expect(status, body, headers=H):
    try:
        store.submit(body, headers, NOW)
    except store.Rejected as e:
        assert e.status == status, (e.status, e.reason)
        return
    raise AssertionError(f"expected {status}")


t = store.tables()
e = store.submit(GOOD, H, NOW)
assert e["kind"] == "idea" and e["lang"] == "de" and e["status"] == "new" and e["PartitionKey"] == "2026-09"
assert len(t.rows["feedback"]) == 1
assert not any("203.0.113.7" in str(v) for v in list(t.rows["ratelimit"].values()) + list(t.rows["feedback"].values())), "IP stored!"

# bots: honeypot filled or posted too fast -> quietly ignored, nothing saved
assert store.submit({**GOOD, "website": "http://spam"}, H, NOW) is None
assert store.submit({**GOOD, "elapsed_ms": 800}, H, NOW) is None
assert len(t.rows["feedback"]) == 1

# bad input
expect(403, GOOD, {**H, "origin": "https://evil.example"})
expect(403, GOOD, {"x-forwarded-for": "1.1.1.1"})
expect(400, {**GOOD, "kind": "hack"})
expect(400, {**GOOD, "message": "hi"})
expect(400, {**GOOD, "message": "x" * 2001})
expect(400, {**GOOD, "email": "not-an-email"})
expect(400, ["not", "a", "dict"])
e = store.submit({**GOOD, "kind": "job", "email": "a@b.de", "job_id": "ba:123", "job_title": "Werkstudent\x00 IT"}, H, NOW)
assert e["job_title"] == "Werkstudent IT" and e["email"] == "a@b.de"

# rate limit: 5 per IP per day (2 used above), other IPs unaffected, next day resets
store.submit(GOOD, H, NOW); store.submit(GOOD, H, NOW); store.submit(GOOD, H, NOW)
expect(429, GOOD)
assert store.submit(GOOD, {**H, "x-forwarded-for": "198.51.100.2"}, NOW)
assert store.submit(GOOD, H, NOW + timedelta(days=1))

# newest first by RowKey
keys = sorted(k[1] for k in t.rows["feedback"])
assert t.rows["feedback"][next(k for k in t.rows["feedback"] if k[1] == keys[0])]["received"].startswith("2026-09-29")

# purge: yesterday's hashes go, feedback older than a year goes
t.upsert("feedback", {"PartitionKey": "2025-08", "RowKey": "old", "message": "old"})
hashes, old = store.purge(NOW + timedelta(days=1))
assert hashes == 2 and old == 1, (hashes, old)
assert all(k[0] == "2026-09-29" for k in t.rows["ratelimit"])

assert store.client_ip({"x-forwarded-for": "[2001:db8::1]:443"}) == "2001:db8::1"
assert store.client_ip({"x-forwarded-for": "2001:db8::1"}) == "2001:db8::1"
# notification email (Azure email client mocked): off without settings, reply-to, daily cap
import types  # noqa: E402
sent = []
fake = types.ModuleType("azure.communication.email")
fake.EmailClient = types.SimpleNamespace(from_connection_string=lambda c: types.SimpleNamespace(begin_send=sent.append))
sys.modules["azure.communication.email"] = fake
e = store.submit({**GOOD, "kind": "job", "email": "stu@uni.de", "job_id": "ba:9", "job_title": "Werkstudent IT – ACME"},
                 {**H, "x-forwarded-for": "192.0.2.50"}, NOW)
assert store.notify(e, NOW) is False and not sent              # not configured -> skipped
os.environ.update(ACS_CONNECTION_STRING="endpoint=x;accesskey=y", ACS_SENDER="DoNotReply@x.azurecomm.net", NOTIFY_TO="me@proton.me")
assert store.notify(e, NOW) is True
m = sent[-1]
assert m["recipients"]["to"] == [{"address": "me@proton.me"}] and m["replyTo"] == [{"address": "stu@uni.de"}]
assert m["content"]["subject"].startswith("[Hamburg Student Jobs] Problem with a job ad: Please add")
assert "Werkstudent IT – ACME  [ba:9]" in m["content"]["plainText"] and e["RowKey"] in m["content"]["plainText"]
e2 = store.submit({**GOOD}, {**H, "x-forwarded-for": "192.0.2.51"}, NOW)
store.notify(e2, NOW)
assert "replyTo" not in sent[-1]                                # no email given -> no reply-to
for _ in range(store.EMAILS_PER_DAY):
    store.notify(e2, NOW)
assert len(sent) == store.EMAILS_PER_DAY                        # capped per day
assert store.notify(e2, NOW + timedelta(days=1)) is True        # next day again
print("all feedback tests passed")
