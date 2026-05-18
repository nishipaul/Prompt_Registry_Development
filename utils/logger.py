from __future__ import annotations

import logging
import sys

_FMT = (
    "%(asctime)s | %(levelname)-8s | %(name)-28s | "
    "op=%(op)-10s user=%(user)-32s handle=%(handle)s env=%(env)s | %(message)s"
)


class _DefaultsFilter(logging.Filter):
    _DEFAULTS = {"op": "-", "user": "-", "handle": "-", "env": "-"}

    def filter(self, record: logging.LogRecord) -> bool:
        for k, v in self._DEFAULTS.items():
            if not hasattr(record, k):
                setattr(record, k, v)
        return True


def configure_logging(debug: bool = False) -> None:
    """Wire up the 'pm' logger hierarchy. Call once at application startup."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FMT, datefmt="%Y-%m-%dT%H:%M:%SZ"))
    handler.addFilter(_DefaultsFilter())
    root = logging.getLogger("pm")
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    if not root.handlers:
        root.addHandler(handler)
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the 'pm' hierarchy."""
    return logging.getLogger(f"pm.{name}")


def log_op(
    logger: logging.Logger,
    level: int,
    msg: str,
    *,
    op: str = "-",
    user: str = "-",
    handle: str = "-",
    env: str = "-",
) -> None:
    """Emit a single structured log line with operation context."""
    logger.log(level, msg, extra={"op": op, "user": user, "handle": handle, "env": env}, stacklevel=2)
