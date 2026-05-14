"""結構化 logging（含可選 stage 欄位）。"""

from __future__ import annotations

import logging
from typing import Optional


class _StageDefaultFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "stage"):
            setattr(record, "stage", "-")
        return True


class StageAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        extra = kwargs.setdefault("extra", {})
        extra.setdefault("stage", self.extra.get("stage", "-"))
        return msg, kwargs


def setup_logging(*, level: str = "INFO", log_file: Optional[str] = None) -> None:
    lvl = getattr(logging, (level or "INFO").upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(lvl)
    if getattr(root, "_dual_agent_logging_configured", False):
        return
    fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(stage)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    sh = logging.StreamHandler()
    sh.setLevel(lvl)
    sh.addFilter(_StageDefaultFilter())
    sh.setFormatter(fmt)
    root.addHandler(sh)
    if log_file:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(lvl)
        fh.addFilter(_StageDefaultFilter())
        fh.setFormatter(fmt)
        root.addHandler(fh)
    setattr(root, "_dual_agent_logging_configured", True)


def get_logger(stage: str) -> StageAdapter:
    return StageAdapter(logging.getLogger("dual_agent"), {"stage": stage})
