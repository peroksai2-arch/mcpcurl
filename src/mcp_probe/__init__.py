"""Inspect, call, smoke-test and document any Model Context Protocol server."""

from .connect import Connection, Target, connect
from .inventory import Inventory, gather
from .render import to_markdown
from .suite import CaseResult, Suite, run_suite, smoke_checks

__all__ = [
    "CaseResult",
    "Connection",
    "Inventory",
    "Suite",
    "Target",
    "connect",
    "gather",
    "run_suite",
    "smoke_checks",
    "to_markdown",
]

__version__ = "0.1.0"
