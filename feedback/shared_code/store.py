"""Feedback from the site: validation, abuse limits and storage in Azure Table Storage.

Tables (in the Function App's own storage account, AzureWebJobsStorage):
  feedback   PartitionKey = "YYYY-MM", RowKey = newest-first time key; one row per message
  ratelimit  PartitionKey = "YYYY-MM-DD", RowKey = salted hash of the sender's IP; message count that day

No IP address is stored: only a one-way hash with a secret salt, and the Purge function deletes those
rows after a day. FEEDBACK_STORE=memory keeps everything in memory (local tests, no Azure needed)."""
import hashlib
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

KINDS = {"question", "idea", "criticism", "bug", "job", "employer", "other"}
MAX_PER_DAY = 5
MIN_FILL_MS = 3000          # humans need more than 3 s to write a message; bots post instantly
KEEP_DAYS = 365             # feedback older than a year is deleted
LIMITS = {"message": 2000, "email": 200, "job_id": 120, "job_title": 200, "page": 120}
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Rejected(Exception):
    """A request we answer with an error status (bad input, wrong origin, too many messages)."""
    def __init__(self, status, reason):
        super().__init__(reason)
        self.status, self.reason = status, reason


class Ignored(Exception):
    """Looks like a bot: answered with a normal 'thanks' so it doesn't learn anything, but nothing is saved."""


# ---------------------------------------------------------------- storage backends
class MemoryTables:
    def __init__(self):
        self.rows = {"feedback": {}, "ratelimit": {}}

    def get(self, table, pk, rk):
        return self.rows[table].get((pk, rk))

    def upsert(self, table, entity):
        self.rows[table][(entity["PartitionKey"], entity["RowKey"])] = dict(entity)

    def delete_where(self, table, older_than_pk):
        old = [k for k in self.rows[table] if k[0] < older_than_pk]
        for k in old:
            del self.rows[table][k]
        return len(old)


class AzureTables:
    def __init__(self, conn):
        from azure.data.tables import TableServiceClient
        self.svc = TableServiceClient.from_connection_string(conn)
        self.clients = {}

    def _t(self, table):
        if table not in self.clients:
            self.clients[table] = self.svc.create_table_if_not_exists(table)
        return self.clients[table]

    def get(self, table, pk, rk):
        from azure.core.exceptions import ResourceNotFoundError
        try:
            return dict(self._t(table).get_entity(pk, rk))
        except ResourceNotFoundError:
            return None

    def upsert(self, table, entity):
        self._t(table).upsert_entity(entity)

    def delete_where(self, table, older_than_pk):
        t, n = self._t(table), 0
        for e in t.query_entities("PartitionKey lt @pk", parameters={"pk": older_than_pk}, select=["PartitionKey", "RowKey"]):
            t.delete_entity(e["PartitionKey"], e["RowKey"])
            n += 1
        return n


_tables = None


def tables():
    global _tables
    if _tables is None:
        _tables = MemoryTables() if os.environ.get("FEEDBACK_STORE") == "memory" else AzureTables(os.environ["AzureWebJobsStorage"])
    return _tables


# ---------------------------------------------------------------- request handling
def allowed_origins():
    return {o.strip().rstrip("/") for o in os.environ.get("ALLOWED_ORIGINS", "https://hamburgstudentjobs.de").split(",") if o.strip()}


def client_ip(headers):
    """Azure puts the caller in X-Forwarded-For ("1.2.3.4:5678, proxy"); the port is dropped."""
    first = (headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if first.startswith("[") and "]" in first:   # [IPv6]:port
        first = first[1:first.index("]")]
    elif first.count(":") == 1:                  # IPv4:port
        first = first.split(":")[0]
    return first or "unknown"


def clean(body):
    """Validate the posted JSON and return the row to store (raises Rejected / Ignored)."""
    if not isinstance(body, dict):
        raise Rejected(400, "expected a JSON object")
    if str(body.get("website") or "").strip():          # hidden field only bots fill in
        raise Ignored()
    try:
        if int(body.get("elapsed_ms") or 0) < MIN_FILL_MS:
            raise Ignored()
    except (TypeError, ValueError):
        raise Rejected(400, "bad elapsed_ms")
    kind = str(body.get("kind") or "")
    if kind not in KINDS:
        raise Rejected(400, "unknown kind")
    row = {"kind": kind, "lang": "de" if body.get("lang") == "de" else "en"}
    for field, limit in LIMITS.items():
        value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(body.get(field) or "")).strip()
        if len(value) > limit:
            raise Rejected(400, f"{field} too long")
        row[field] = value
    if len(row["message"]) < 5:
        raise Rejected(400, "message too short")
    if row["email"] and not EMAIL.match(row["email"]):
        raise Rejected(400, "email looks wrong")
    return row


def check_rate(ip, now):
    day = now.strftime("%Y-%m-%d")
    salt = os.environ.get("RATE_SALT", "")
    if not salt and os.environ.get("FEEDBACK_STORE") != "memory":
        raise RuntimeError("RATE_SALT app setting is missing")
    key = hashlib.sha256(f"{salt}|{day}|{ip}".encode()).hexdigest()[:40]
    t = tables()
    row = t.get("ratelimit", day, key) or {"PartitionKey": day, "RowKey": key, "count": 0}
    if row["count"] >= MAX_PER_DAY:
        raise Rejected(429, "too many messages today")
    row["count"] += 1
    t.upsert("ratelimit", row)


def save(row, now):
    ms = int(now.timestamp() * 1000)
    entity = {
        "PartitionKey": now.strftime("%Y-%m"),
        # newest first when listed: inverted milliseconds, plus randomness so two messages never collide
        "RowKey": f"{10**13 - ms:013d}-{secrets.token_hex(3)}",
        "received": now.isoformat(timespec="seconds"),
        "status": "new",
        **row,
    }
    tables().upsert("feedback", entity)
    return entity


EMAILS_PER_DAY = 40         # cap on notification emails, whatever happens (many senders, abuse)
KIND_NAMES = {"question": "Question", "idea": "Idea", "criticism": "Criticism", "bug": "Something is broken",
              "job": "Problem with a job ad", "employer": "Employer suggestion", "other": "Other"}


def notify(entity, now):
    """Email the operator a copy of the message via Azure Communication Services (the same service
    AI News Watch uses). Optional: skipped unless ACS_CONNECTION_STRING, ACS_SENDER and NOTIFY_TO are set.
    Never blocks or breaks saving: the message is already stored when this runs."""
    conn, sender, to = (os.environ.get(k) for k in ("ACS_CONNECTION_STRING", "ACS_SENDER", "NOTIFY_TO"))
    if not (conn and sender and to):
        return False
    day, t = now.strftime("%Y-%m-%d"), tables()
    counter = t.get("ratelimit", day, "_emails") or {"PartitionKey": day, "RowKey": "_emails", "count": 0}
    if counter["count"] >= EMAILS_PER_DAY:
        return False
    counter["count"] += 1
    t.upsert("ratelimit", counter)

    first_line = re.sub(r"\s+", " ", entity["message"])[:70]
    lines = [f"Type:     {KIND_NAMES.get(entity['kind'], entity['kind'])}",
             f"Received: {entity['received']} (UTC)",
             f"Language: {entity['lang']}"]
    if entity["email"]:
        lines.append(f"Email:    {entity['email']}  (just reply to this email to answer)")
    if entity["job_title"]:
        lines.append(f"Job:      {entity['job_title']}  [{entity['job_id']}]")
    if entity["page"]:
        lines.append(f"Page:     https://hamburgstudentjobs.de{entity['page']}")
    text = "\n".join(lines) + "\n\n" + entity["message"] + "\n\n-- \nStored in Azure Table Storage: hsjfeedbackemir / feedback / " + entity["RowKey"]

    msg = {"senderAddress": sender,
           "recipients": {"to": [{"address": a.strip()} for a in to.split(",") if a.strip()]},
           "content": {"subject": f"[Hamburg Student Jobs] {KIND_NAMES.get(entity['kind'])}: {first_line}", "plainText": text}}
    if entity["email"]:
        msg["replyTo"] = [{"address": entity["email"]}]
    from azure.communication.email import EmailClient
    # begin_send hands the email to Azure; not waiting for delivery keeps the form's answer fast
    EmailClient.from_connection_string(conn).begin_send(msg)
    return True


def submit(body, headers, now=None):
    """Whole flow for one POST. Returns the stored entity, or None when a bot was quietly ignored."""
    now = now or datetime.now(timezone.utc)
    origin = (headers.get("origin") or "").rstrip("/")
    if origin not in allowed_origins():
        raise Rejected(403, "origin not allowed")
    try:
        row = clean(body)
    except Ignored:
        time.sleep(0.5)
        return None
    check_rate(client_ip(headers), now)
    return save(row, now)


def purge(now=None):
    """Daily: forget yesterday's rate-limit hashes, delete feedback older than KEEP_DAYS."""
    now = now or datetime.now(timezone.utc)
    t = tables()
    hashes = t.delete_where("ratelimit", now.strftime("%Y-%m-%d"))
    old = t.delete_where("feedback", (now - timedelta(days=KEEP_DAYS)).strftime("%Y-%m"))
    return hashes, old
