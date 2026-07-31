"""A channel for hardware problems that the user has to know about.

Camera work happens on worker threads, so it cannot raise a dialog directly.
Problems are queued here and drained by the GUI on its own thread, following the
same pattern the camera overview already uses for its results.

Two rules shape this:

*Say it early.*  Anything checkable before the eclipse — a camera that did not
appear, a setting that will spoil the frames — should be reported the moment the
camera is connected, while there is still time to walk over and fix it.

*Say it quietly once the run has started.*  While a script is executing, a modal
dialog is worse than the problem it describes: it stalls the application at the
exact moment frames are being taken.  Repeats are therefore folded together with
a count, and the GUI shows them as an indicator during a run and only opens a
dialog when the schedule is not running.
"""

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Distinct problems worth remembering.  Repeats of the same problem increment a
# count rather than taking a new slot, so a failure in a tight loop cannot push
# everything else out.
_MAX_PROBLEMS = 50

# How often the same problem may be logged.  The count keeps rising regardless;
# this only stops the log filling with one repeated line.
_LOG_INTERVAL_S = 5.0

_problems: OrderedDict = OrderedDict()
_lock = threading.Lock()


@dataclass
class Problem:
    """Something the user needs to see, not just something that got logged."""

    source: str                 # "Fuji SDK", "X-T4", ...
    message: str                # one line, plain language
    detail: str = ""            # optional specifics
    severity: str = "error"     # "error" | "warning"
    count: int = 1
    first_seen: float = 0.0
    last_seen: float = 0.0
    context: dict = field(default_factory=dict)

    @property
    def key(self) -> tuple:
        return (self.source, self.message)

    def __str__(self) -> str:
        text = f"{self.source}: {self.message}"
        if self.detail:
            text += f" ({self.detail})"
        if self.count > 1:
            text += f" [x{self.count}]"
        return text


def report(source: str, message: str, detail: str = "", severity: str = "error",
           **context) -> None:
    """Queue a problem for the GUI, and log it at a level that matches.

    Safe to call from any thread.  Never raises: reporting a problem must not
    itself become one.  Repeats of the same (source, message) are folded into a
    count instead of queuing again.
    """
    try:
        now = time.time()
        key = (source, message)
        should_log = True

        with _lock:
            existing = _problems.get(key)
            if existing is not None:
                existing.count += 1
                existing.last_seen = now
                if existing.detail != detail and detail:
                    existing.detail = detail
                should_log = (now - existing.context.get("_logged_at", 0.0)) >= _LOG_INTERVAL_S
                if should_log:
                    existing.context["_logged_at"] = now
                problem = existing
            else:
                problem = Problem(source=source, message=message, detail=detail,
                                  severity=severity, first_seen=now, last_seen=now,
                                  context=dict(context, _logged_at=now))
                _problems[key] = problem
                if len(_problems) > _MAX_PROBLEMS:
                    _problems.popitem(last=False)

        if should_log:
            log = logger.error if severity == "error" else logger.warning
            log("%s", problem)
    except Exception:
        logger.debug("Failed to report a hardware problem", exc_info=True)


def drain() -> list:
    """Take every queued problem, leaving the queue empty."""
    with _lock:
        taken = list(_problems.values())
        _problems.clear()
    return taken


def peek() -> list:
    """Look at queued problems without consuming them."""
    with _lock:
        return list(_problems.values())


def count() -> int:
    """How many distinct problems are waiting."""
    with _lock:
        return len(_problems)


def clear() -> None:
    with _lock:
        _problems.clear()


def summarise(problems: Optional[list] = None) -> str:
    """Fold a list of problems into one block of text for a dialog or banner."""
    problems = peek() if problems is None else problems
    if not problems:
        return ""
    lines = []
    for problem in problems:
        suffix = f"  (x{problem.count})" if problem.count > 1 else ""
        lines.append(f"• {problem.message}{suffix}")
        if problem.detail:
            lines.append(f"    {problem.detail}")
    return "\n".join(lines)
