"""A tiny INDI server with one simulated telescope mount.

For the tests and for trying the mount controls with nothing connected (the
``simulated`` host in the `Mount` window, ``sew --mount simulated`` and
``sew_hardware --simulate``).  It speaks the same XML as a real ``indiserver``
and defines the standard telescope properties ``sew`` uses, so the real client
code path runs against it.  It does not move anything: a park or a guide pulse
is answered and remembered, nothing more.

To test against a real driver instead, run the INDI telescope simulator:

    indiserver indi_simulator_telescope
"""

import logging
import socket
import threading
from xml.sax.saxutils import escape, quoteattr

from solareclipseworkbench.indi_client import (ALERT, BUSY, IDLE, NUMBER, OK, SWITCH, TEXT, XmlStream,
                                               format_number, parse_number)

logger = logging.getLogger(__name__)

DEVICE = "Telescope Simulator"

#: Interface bit of a telescope in DRIVER_INFO.DRIVER_INTERFACE
TELESCOPE_INTERFACE = 1


class _Prop:
    def __init__(self, name: str, kind: str, values: dict, rule: str = "", perm: str = "rw",
                 needs_connection: bool = True):
        self.name, self.kind, self.values, self.rule, self.perm = name, kind, dict(values), rule, perm
        self.state = IDLE
        self.needs_connection = needs_connection


class SimulatedIndiServer:
    """INDI server on ``localhost`` with one mount, on a free port unless one is given.

    Args:
        - solar: Whether the mount offers TRACK_SOLAR (many drivers do not)
        - refuse: Property names whose changes are answered with Alert
        - silent: Property names whose changes get no answer at all
        - device: Name of the mount
    """

    def __init__(self, port: int = 0, solar: bool = True, refuse=(), silent=(), device: str = DEVICE):
        self.device = device
        self.refuse, self.silent = set(refuse), set(silent)
        #: Every change received, as (property name, {element: value})
        self.received: list = []
        self._lock = threading.Lock()
        self._clients: list = []
        modes = {"TRACK_SIDEREAL": True, "TRACK_LUNAR": False}
        if solar:
            modes["TRACK_SOLAR"] = False
        props = [
            _Prop("CONNECTION", SWITCH, {"CONNECT": False, "DISCONNECT": True}, rule="OneOfMany",
                  needs_connection=False),
            _Prop("DRIVER_INFO", TEXT, {"DRIVER_NAME": "Telescope Simulator", "DRIVER_EXEC": "indi_simulator",
                                        "DRIVER_VERSION": "1.0",
                                        "DRIVER_INTERFACE": str(TELESCOPE_INTERFACE)},
                  perm="ro", needs_connection=False),
            _Prop("DEVICE_PORT", TEXT, {"PORT": "/dev/ttyUSB0"}, needs_connection=False),
            _Prop("GEOGRAPHIC_COORD", NUMBER, {"LAT": 0.0, "LONG": 0.0, "ELEV": 0.0}),
            _Prop("TIME_UTC", TEXT, {"UTC": "", "OFFSET": "0"}),
            _Prop("EQUATORIAL_EOD_COORD", NUMBER, {"RA": 0.0, "DEC": 90.0}),
            _Prop("TELESCOPE_TRACK_MODE", SWITCH, modes, rule="OneOfMany"),
            _Prop("TELESCOPE_TRACK_STATE", SWITCH, {"TRACK_ON": False, "TRACK_OFF": True}, rule="OneOfMany"),
            _Prop("TELESCOPE_PARK", SWITCH, {"PARK": False, "UNPARK": True}, rule="OneOfMany"),
            _Prop("TELESCOPE_ABORT_MOTION", SWITCH, {"ABORT": False}, rule="AtMostOne"),
            _Prop("TELESCOPE_TIMED_GUIDE_NS", NUMBER, {"TIMED_GUIDE_N": 0.0, "TIMED_GUIDE_S": 0.0}),
            _Prop("TELESCOPE_TIMED_GUIDE_WE", NUMBER, {"TIMED_GUIDE_W": 0.0, "TIMED_GUIDE_E": 0.0}),
            _Prop("TELESCOPE_MOTION_NS", SWITCH, {"MOTION_NORTH": False, "MOTION_SOUTH": False}, rule="AtMostOne"),
            _Prop("TELESCOPE_MOTION_WE", SWITCH, {"MOTION_WEST": False, "MOTION_EAST": False}, rule="AtMostOne"),
        ]
        self.props = {p.name: p for p in props}
        self._server = socket.create_server(("127.0.0.1", port))
        self.port = self._server.getsockname()[1]
        self._running = True
        self._thread = threading.Thread(target=self._accept, name="indi-simulator", daemon=True)
        self._thread.start()
        logger.info("Simulated INDI server with %r on port %d", device, self.port)

    # --------------------------------------------------------------- helpers

    @property
    def connected(self) -> bool:
        return self.props["CONNECTION"].values["CONNECT"]

    def values(self, name: str) -> dict:
        with self._lock:
            return dict(self.props[name].values)

    def close(self) -> None:
        self._running = False
        try:
            self._server.close()
        except OSError:
            pass
        with self._lock:
            clients, self._clients = self._clients, []
        for conn in clients:
            try:
                conn.shutdown(socket.SHUT_RDWR)
                conn.close()
            except OSError:
                pass

    # ---------------------------------------------------------------- server

    def _accept(self) -> None:
        while self._running:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            with self._lock:
                self._clients.append(conn)
            threading.Thread(target=self._serve, args=(conn,), daemon=True, name="indi-simulator-client").start()

    def _serve(self, conn: socket.socket) -> None:
        stream = XmlStream()
        try:
            while self._running:
                data = conn.recv(65536)
                if not data:
                    break
                for element in stream.feed(data):
                    self._handle(element)
        except Exception:
            logger.debug("Simulated INDI client gone", exc_info=True)
        finally:
            with self._lock:
                if conn in self._clients:
                    self._clients.remove(conn)
            try:
                conn.close()
            except OSError:
                pass

    def _broadcast(self, xml: str) -> None:
        with self._lock:
            clients = list(self._clients)
        for conn in clients:
            try:
                conn.sendall(xml.encode())
            except OSError:
                pass

    @staticmethod
    def _value_text(kind: str, value) -> str:
        if kind == SWITCH:
            return "On" if value else "Off"
        if kind == NUMBER:
            return format_number(value)
        return escape(str(value))

    def _vector(self, prop: _Prop, verb: str, message: str = "") -> str:
        element = "def" if verb == "def" else "one"
        body = "".join(f"<{element}{prop.kind} name={quoteattr(k)}>{self._value_text(prop.kind, v)}"
                       f"</{element}{prop.kind}>" for k, v in prop.values.items())
        extra = f" rule={quoteattr(prop.rule)}" if verb == "def" and prop.rule else ""
        if verb == "def":
            extra += f" perm={quoteattr(prop.perm)} label={quoteattr(prop.name)}"
        if message:
            extra += f" message={quoteattr(message)}"
        return (f"<{verb}{prop.kind}Vector device={quoteattr(self.device)} name={quoteattr(prop.name)} "
                f"state={quoteattr(prop.state)}{extra}>{body}</{verb}{prop.kind}Vector>")

    def _defined(self) -> list:
        return [p for p in self.props.values() if self.connected or not p.needs_connection]

    def _handle(self, element) -> None:
        tag, attrs = element.tag, element.attrib
        if tag == "getProperties":
            with self._lock:
                xml = "".join(self._vector(p, "def") for p in self._defined())
            self._broadcast(xml)
            return
        if not tag.startswith("new") or attrs.get("device") != self.device:
            return
        name = attrs.get("name", "")
        with self._lock:
            prop = self.props.get(name)
            if prop is None or not (self.connected or not prop.needs_connection):
                return
            changes = {}
            for child in element:
                key = child.attrib.get("name", "")
                if key not in prop.values:
                    continue
                if prop.kind == SWITCH:
                    changes[key] = (child.text or "").strip() == "On"
                elif prop.kind == NUMBER:
                    changes[key] = parse_number(child.text or "0")
                else:
                    changes[key] = (child.text or "").strip()
            self.received.append((name, changes))
        if name in self.silent:
            return
        if name in self.refuse:
            with self._lock:
                prop.state = ALERT
                xml = self._vector(prop, "set", message=f"{name} refused by the simulator")
            self._broadcast(xml)
            return

        was_connected = self.connected
        with self._lock:
            if prop.kind == SWITCH and prop.rule == "OneOfMany":
                chosen = [k for k, v in changes.items() if v]
                if chosen:
                    for key in prop.values:
                        prop.values[key] = key == chosen[0]
            elif prop.kind == SWITCH and name == "TELESCOPE_ABORT_MOTION":
                pass    # momentary
            else:
                prop.values.update(changes)
            if name == "TELESCOPE_PARK" and prop.values["PARK"]:
                self.props["TELESCOPE_TRACK_STATE"].values.update(TRACK_ON=False, TRACK_OFF=True)
            # A guide pulse or a park starts something long: answer Busy first
            long_change = name.startswith("TELESCOPE_TIMED_GUIDE") or name == "TELESCOPE_PARK"
            prop.state = BUSY if long_change else OK
            xml = self._vector(prop, "set")
            if long_change:
                prop.state = OK
                xml += self._vector(prop, "set")
            if name == "TELESCOPE_PARK":
                xml += self._vector(self.props["TELESCOPE_TRACK_STATE"], "set")
        self._broadcast(xml)

        if name == "CONNECTION" and self.connected != was_connected:
            with self._lock:
                if self.connected:
                    xml = "".join(self._vector(p, "def") for p in self.props.values() if p.needs_connection)
                else:
                    xml = "".join(f"<delProperty device={quoteattr(self.device)} name={quoteattr(p.name)}/>"
                                  for p in self.props.values() if p.needs_connection)
            self._broadcast(xml)

