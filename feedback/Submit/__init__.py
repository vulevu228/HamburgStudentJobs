"""POST /api/feedback - one message from the site's feedback form."""
import json
import logging
from datetime import datetime, timezone

import azure.functions as func

from ..shared_code import store


def reply(status, data):  # CORS headers come from the Function App's CORS setting (see SETUP.md)
    headers = {"Content-Type": "application/json", "Cache-Control": "no-store"}
    return func.HttpResponse(json.dumps(data), status_code=status, headers=headers)


def main(req: func.HttpRequest) -> func.HttpResponse:
    headers = {k.lower(): v for k, v in req.headers.items()}
    if len(req.get_body() or b"") > 8000:
        return reply(413, {"ok": False, "error": "too large"})
    try:
        body = req.get_json()
    except ValueError:
        return reply(400, {"ok": False, "error": "expected JSON"})
    try:
        entity = store.submit(body, headers)
    except store.Rejected as e:
        logging.info("feedback rejected: %s %s", e.status, e.reason)
        return reply(e.status, {"ok": False, "error": e.reason})
    if entity:
        logging.info("feedback saved: %s %s", entity["kind"], entity["RowKey"])
        try:
            store.notify(entity, datetime.now(timezone.utc))
        except Exception:  # the message is stored; a failed email must not turn into an error for the visitor
            logging.exception("feedback email failed for %s", entity["RowKey"])
    return reply(200, {"ok": True})
