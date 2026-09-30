"""POST /api/alerts/{subscribe|confirm|unsubscribe} - daily job alert by email (see shared_code/alerts.py)."""
import json
import logging

import azure.functions as func

from ..shared_code import alerts, store


def reply(status, data):
    return func.HttpResponse(json.dumps(data), status_code=status,
                             headers={"Content-Type": "application/json", "Cache-Control": "no-store"})


def main(req: func.HttpRequest) -> func.HttpResponse:
    action = req.route_params.get("action")
    headers = {k.lower(): v for k, v in req.headers.items()}
    if len(req.get_body() or b"") > 4000:
        return reply(413, {"ok": False, "error": "too large"})
    try:
        body = req.get_json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    try:
        if action == "subscribe":
            row = alerts.subscribe(body, headers)
            logging.info("alert sign-up: %s", "ignored (bot)" if row is None else row["RowKey"][:8])
            return reply(200, {"ok": True})
        if action == "confirm":
            return reply(200, {"ok": True, **alerts.confirm(body)})
        if action == "unsubscribe":
            # mail programs' one-click unsubscribe (RFC 8058) posts a form with the link's ?id=&t=
            alerts.unsubscribe({"id": body.get("id") or req.params.get("id"), "t": body.get("t") or req.params.get("t")})
            return reply(200, {"ok": True})
        return reply(404, {"ok": False, "error": "unknown action"})
    except store.Rejected as e:
        logging.info("alerts %s rejected: %s %s", action, e.status, e.reason)
        return reply(e.status, {"ok": False, "error": e.reason})
