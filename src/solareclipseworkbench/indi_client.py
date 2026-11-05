"""A small INDI client: XML over TCP, in pure Python.

INDI (https://indilib.org) drives astronomy hardware through an ``indiserver``
that loads one driver per device.  A client talks to the server over TCP (port
7624 by default) in a stream of XML elements with no enclosing root:

    client → server   <getProperties version="1.7"/>
                      <newSwitchVector device=".." name=".."><oneSwitch name="..">On</oneSwitch></newSwitchVector>
    server → client   <defNumberVector device=".." name=".." state="Idle" ...><defNumber name="..">1.5</defNumber>...
                      <setNumberVector device=".." name=".." state="Ok" ...><oneNumber name="..">1.6</oneNumber>...
                      <delProperty device=".." name=".."/>
                      <message device=".." message=".."/>

Only what mount control needs is here: switch, number and text vectors (lights
are kept, BLOBs are never asked for).  The compiled ``pyindi-client`` would do
the same, but it has to be built against libindi, which the installers would
then have to provide on every platform.

A reader thread keeps a cache of every property; the calls that change one wait
for the server's answer to it (see ``IndiClient.change``).
"""

import logging
import socket
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Callable, Iterator, Optional
from xml.sax.saxutils import escape, quoteattr

logger = logging.getLogger(__name__)

DEFAULT_PORT = 7624

#: Property states, as INDI spells them
IDLE, OK, BUSY, ALERT = "Idle", "Ok", "Busy", "Alert"

SWITCH, NUMBER, TEXT, LIGHT, BLOB = "Switch", "Number", "Text", "Light", "BLOB"
KINDS = (SWITCH, NUMBER, TEXT, LIGHT, BLOB)


class IndiError(Exception):
    """The INDI server could not be reached, or refused or did not answer a change."""


def parse_number(text: str) -> float:
    """An INDI number: decimal, or sexagesimal ("12:30:15", "-5 30 0", "12:30.5")."""
    text = (text or "").strip()
    try:
        return float(text)
    except ValueError:
        pass
    parts = text.replace(":", " ").split()
    if not parts:
        raise ValueError(f"not a number: {text!r}")
    negative = parts[0].startswith("-")
    value = 0.0
    for scale, part in zip((1.0, 60.0, 3600.0), parts):
        value += abs(float(part)) / scale
    return -value if negative else value


def format_number(value: float) -> str:
    return f"{float(value):.10g}"


@dataclass
class Property:
    """One INDI property (a vector of elements) as last reported by the server."""
    device: str
    name: str
    kind: str
    state: str = IDLE
    label: str = ""
    group: str = ""
    perm: str = "rw"
    rule: str = ""
    #: Element name → value: bool for switches, float for numbers, str otherwise
    values: dict = field(default_factory=dict)
    #: Element name → label, as defined by the driver (e.g. "SLEW_GUIDE" → "Guide")
    labels: dict = field(default_factory=dict)
    #: The message that came with the last definition or update
    message: str = ""
    #: Counts the definitions and updates received, so a caller can wait for the next one
    updates: int = 0

    def on_switches(self) -> list:
        return [name for name, on in self.values.items() if on]


class XmlStream:
    """Turns a byte stream of INDI XML elements into whole top-level elements."""

    def __init__(self):
        self._parser = ET.XMLPullParser(events=("start", "end"))
        self._parser.feed("<indi>")
        self._root: Optional[ET.Element] = None
        self._depth = 0

    def feed(self, data: bytes) -> Iterator[ET.Element]:
        self._parser.feed(data)
        for event, element in self._parser.read_events():
            if event == "start":
                self._depth += 1
                if self._root is None:
                    self._root = element
            else:
                self._depth -= 1
                if self._depth == 1:
                    yield element
                    # Keep memory flat: the stream never ends, so neither would the tree
                    self._root.remove(element)


def _element_value(kind: str, text: Optional[str]):
    if kind == SWITCH:
        return (text or "").strip() == "On"
    if kind == NUMBER:
        try:
            return parse_number(text or "")
        except ValueError:
            return float("nan")
    return (text or "").strip()


class IndiClient:
    """Connection to one INDI server.

    Args:
        - host, port: The server
        - timeout: Seconds to wait for the TCP connection
        - on_message: Called on the reader thread with (device, message) for every
                      message a driver sends.  Must return quickly.
    """

    def __init__(self, host: str = "localhost", port: int = DEFAULT_PORT, timeout: float = 5.0,
                 on_message: Optional[Callable[[str, str], None]] = None):
        self.host, self.port = host, int(port)
        self._on_message = on_message
        self._properties: dict = {}         # (device, name) → Property
        self._cond = threading.Condition()
        self._send_lock = threading.Lock()
        self._last_definition = 0.0
        self._closed = False
        self.messages: list = []            # (time, device, message), the last 50
        try:
            self._sock = socket.create_connection((self.host, self.port), timeout=timeout)
        except OSError as exc:
            raise IndiError(f"no INDI server at {self.host}:{self.port} ({exc})") from exc
        self._sock.settimeout(None)
        self._reader = threading.Thread(target=self._read, name=f"indi-{self.host}:{self.port}", daemon=True)
        self._reader.start()
        self._send('<getProperties version="1.7"/>')

    # ----------------------------------------------------------------- state

    @property
    def connected(self) -> bool:
        return not self._closed

    def describe(self) -> str:
        return f"{self.host}:{self.port}"

    def devices(self) -> list:
        with self._cond:
            return sorted({device for device, _ in self._properties})

    def property(self, device: str, name: str) -> Optional[Property]:
        with self._cond:
            return self._properties.get((device, name))

    def value(self, device: str, name: str, element: str, default=None):
        with self._cond:
            prop = self._properties.get((device, name))
            if prop is None:
                return default
            return prop.values.get(element, default)

    def wait_settled(self, quiet_s: float = 0.4, timeout: float = 3.0) -> None:
        """Wait until the server has sent its definitions: some arrived, then none for ``quiet_s``."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while time.monotonic() < deadline and not self._closed:
                if self._properties and time.monotonic() - self._last_definition >= quiet_s:
                    return
                self._cond.wait(min(quiet_s, max(0.0, deadline - time.monotonic())))

    def wait_for(self, predicate: Callable[[], bool], timeout: float) -> bool:
        """Wait until ``predicate()`` is true (it is called with the property cache locked)."""
        with self._cond:
            return self._cond.wait_for(lambda: self._closed or predicate(), timeout) and not self._closed

    # --------------------------------------------------------------- changes

    def change(self, device: str, name: str, values: dict, timeout: float = 5.0,
               wait_done: bool = True) -> Property:
        """Ask the server to change a property, and wait for its answer.

        Args:
            - values: Element name → new value.  For a switch vector give only the
                      switches to change (one True for a one-of-many switch).
            - wait_done: Wait until the property is no longer Busy.  False for
                         changes that start something long (park, a guide pulse):
                         the first answer is enough then.

        Raises IndiError when the property does not exist, the server marks it
        Alert, or no answer comes within ``timeout``.
        """
        with self._cond:
            prop = self._properties.get((device, name))
            if prop is None:
                raise IndiError(f"{device} has no property {name}")
            kind, before = prop.kind, prop.updates
        self._send(self._new_vector(device, name, kind, values))

        def answered():
            p = self._properties.get((device, name))
            return p is not None and p.updates > before and (p.state != BUSY or not wait_done)

        with self._cond:
            ok = self._cond.wait_for(lambda: self._closed or answered(), timeout)
            prop = self._properties.get((device, name))
        if self._closed:
            raise IndiError(f"the connection to the INDI server at {self.describe()} was lost")
        if not ok:
            raise IndiError(f"{device} did not answer the change of {name} within {timeout:.0f} s")
        if prop.state == ALERT:
            raise IndiError(f"{device} refused the change of {name}" + (f": {prop.message}" if prop.message else ""))
        return prop

    @staticmethod
    def _new_vector(device: str, name: str, kind: str, values: dict) -> str:
        if kind == SWITCH:
            body = "".join(f"<oneSwitch name={quoteattr(k)}>{'On' if v else 'Off'}</oneSwitch>"
                           for k, v in values.items())
        elif kind == NUMBER:
            body = "".join(f"<oneNumber name={quoteattr(k)}>{format_number(v)}</oneNumber>"
                           for k, v in values.items())
        elif kind == TEXT:
            body = "".join(f"<oneText name={quoteattr(k)}>{escape(str(v))}</oneText>" for k, v in values.items())
        else:
            raise IndiError(f"{name} is a {kind} property, which cannot be changed")
        return (f"<new{kind}Vector device={quoteattr(device)} name={quoteattr(name)}>"
                f"{body}</new{kind}Vector>")

    def _send(self, xml: str) -> None:
        if self._closed:
            raise IndiError(f"not connected to the INDI server at {self.describe()}")
        logger.debug("INDI → %s", xml)
        try:
            with self._send_lock:
                self._sock.sendall(xml.encode())
        except OSError as exc:
            self._lost(exc)
            raise IndiError(f"the connection to the INDI server at {self.describe()} was lost ({exc})") from exc

    def close(self) -> None:
        """Close the connection.  The drivers stay connected to their devices."""
        if self._closed:
            return
        self._closed = True
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._sock.close()
        with self._cond:
            self._cond.notify_all()

    # ---------------------------------------------------------------- reader

    def _lost(self, reason) -> None:
        if not self._closed:
            logger.warning("Lost the connection to the INDI server at %s: %s", self.describe(), reason)
        self._closed = True
        with self._cond:
            self._cond.notify_all()

    def _read(self) -> None:
        stream = XmlStream()
        try:
            while True:
                data = self._sock.recv(65536)
                if not data:
                    self._lost("the server closed the connection")
                    return
                for element in stream.feed(data):
                    self._handle(element)
        except (OSError, ET.ParseError) as exc:
            self._lost(exc)

    def _handle(self, element: ET.Element) -> None:
        tag, attrs = element.tag, element.attrib
        device, name = attrs.get("device", ""), attrs.get("name", "")
        message = attrs.get("message", "")
        if message:
            self._remember_message(device, message)

        if tag == "message":
            return
        if tag == "delProperty":
            with self._cond:
                if name:
                    self._properties.pop((device, name), None)
                else:
                    for key in [k for k in self._properties if k[0] == device]:
                        del self._properties[key]
                self._cond.notify_all()
            return

        for kind in KINDS:
            if tag == f"def{kind}Vector":
                prop = Property(device, name, kind, state=attrs.get("state", IDLE), label=attrs.get("label", name),
                                group=attrs.get("group", ""), perm=attrs.get("perm", "rw"),
                                rule=attrs.get("rule", ""), message=message)
                for child in element:
                    if child.tag == f"def{kind}":
                        element_name = child.attrib.get("name", "")
                        prop.values[element_name] = _element_value(kind, child.text)
                        prop.labels[element_name] = child.attrib.get("label", element_name)
                with self._cond:
                    old = self._properties.get((device, name))
                    prop.updates = (old.updates if old else 0) + 1
                    self._properties[(device, name)] = prop
                    self._last_definition = time.monotonic()
                    self._cond.notify_all()
                return
            if tag == f"set{kind}Vector":
                with self._cond:
                    prop = self._properties.get((device, name))
                    if prop is None:
                        return
                    prop.state = attrs.get("state", prop.state)
                    prop.message = message
                    for child in element:
                        if child.tag == f"one{kind}":
                            prop.values[child.attrib.get("name", "")] = _element_value(kind, child.text)
                    prop.updates += 1
                    self._cond.notify_all()
                logger.debug("INDI ← %s.%s %s %s", device, name, prop.state, prop.values)
                return

    def _remember_message(self, device: str, message: str) -> None:
        logger.info("INDI %s: %s", device or "server", message)
        self.messages = (self.messages + [(time.time(), device, message)])[-50:]
        if self._on_message is not None:
            try:
                self._on_message(device, message)
            except Exception:
                logger.debug("INDI message callback failed", exc_info=True)
