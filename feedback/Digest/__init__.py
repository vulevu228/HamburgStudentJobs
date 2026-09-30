"""Every 20 minutes 05:00-09:40 UTC: once today's jobs are published, email each active alert its new matches."""
import logging

import azure.functions as func

from ..shared_code import alerts


def main(timer: func.TimerRequest) -> None:
    result = alerts.digest()
    logging.info("digest: %s", result)
