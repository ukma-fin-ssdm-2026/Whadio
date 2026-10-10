import logging
from typing import Literal

type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


def configure_logging(level: LogLevel) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(processName)s %(name)s: %(message)s",
    )
    # httpx2 logs every request URL at INFO, and a presigned URL carries its signature.
    logging.getLogger("httpx2").setLevel(logging.WARNING)
