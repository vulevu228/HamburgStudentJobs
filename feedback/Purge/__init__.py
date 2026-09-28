"""Daily clean-up: rate-limit hashes older than today, feedback older than a year."""
import logging

import azure.functions as func

from ..shared_code import store


def main(timer: func.TimerRequest) -> None:
    hashes, old = store.purge()
    logging.info("purge: %d rate-limit rows, %d old messages deleted", hashes, old)
