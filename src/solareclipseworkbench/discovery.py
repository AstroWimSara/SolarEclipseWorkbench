"""Shared shape for "here is where a piece of hardware might be".

Hardware on a USB serial port is found by walking the ports and asking each
driver whether anything there looks like one of its devices.  Every driver
reports its findings through this one type, so the GUI and the bench console
can list them together.
"""

from dataclasses import dataclass, field


@dataclass
class Candidate:
    """A place a driver thinks one of its devices might be.

    Being listed is a hint, never a promise: a USB serial adapter is a reason to
    probe, not evidence that the device behind it is the one claimed.
    """

    #: What sort of device this is, e.g. "relay".
    kind: str
    #: The driver or backend that produced this candidate.
    driver: str
    #: Where it is: a device path, a host, a USB identifier.
    target: str
    description: str = ""
    #: Keyword arguments that would connect to it.
    config: dict = field(default_factory=dict)

    def __str__(self) -> str:
        suffix = f" ({self.description})" if self.description else ""
        return f"{self.driver}: {self.target}{suffix}"
