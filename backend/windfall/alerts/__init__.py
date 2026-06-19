"""Alert rule engine (v1: logs only — external Telegram/email delivery deferred per owner)."""
from .rules import build_alerts, dispatch  # noqa: F401
