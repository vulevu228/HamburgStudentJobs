"""Daily clean-up: rate-limit hashes older than today, feedback older than a year, unconfirmed alert sign-ups."""
import logging

import azure.functions as func

from ..shared_code import alerts, store


def main(timer: func.TimerRequest) -> None:
    hashes, old = store.purge()
    pending = alerts.purge_pending()
    logging.info("purge: %d rate-limit rows, %d old messages, %d unconfirmed alert sign-ups deleted", hashes, old, pending)
