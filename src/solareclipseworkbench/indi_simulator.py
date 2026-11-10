"""A tiny INDI server with one simulated telescope mount.

For the tests and for trying the mount controls with nothing connected (the
``simulated`` host in the `Mount` window, ``sew --mount simulated`` and
``sew_hardware --simulate``).  It speaks the same XML as a real ``indiserver``
and defines the standard telescope properties ``sew`` uses, so the real client
code path runs against it.

The simulated mount starts pointed at the sun and moves like a mount would: the
position drifts with the sky when it does not track, holds when it tracks, and
follows the nudges (at the chosen slew rate), the guide pulses and a park.

To test against a real driver instead, run the INDI telescope simulator:

    indiserver indi_simulator_telescope
"""

import logging
import socket
import threading
import time
from xml.sax.saxutils import escape, quoteattr

from solareclipseworkbench.indi_client import (ALERT, BUSY, IDLE, NUMBER, OK, SWITCH, TEXT, XmlStream,
                                               format_number, parse_number)

logger = logging.getLogger(__name__)

DEVICE = "Telescope Simulator"

#: Interface bit of a telescope in DRIVER_INFO.DRIVER_INTERFACE
TELESCOPE_INTERFACE = 1

#: How fast the sky turns: sidereal rate in hours of right ascension per second
SIDEREAL_H_PER_S = 1.00273791 / 3600.0

#: Slew rates as multiples of the sidereal rate (15″/s)
SLEW_RATE_MULTIPLES = {"1x": 1.0, "2x": 8.0, "3x": 64.0, "4x": 400.0}

#: Guide pulses move at half the sidereal rate, as most drivers do by default
GUIDE_RATE = 0.5

#: How often the position is updated
TICK_S = 0.2


def sun_position() -> tuple:
    """(right ascension in hours, declination in degrees) of the sun now; the pole when unknown."""
    try:
        from astropy.coordinates import get_sun
        from astropy.time import Time
        sun = get_sun(Time.now())
        return float(sun.ra.hour), float(sun.dec.deg)
    except Exception:
        logger.debug("No sun position for the simulated mount", exc_info=True)
        return 0.0, 90.0


#: Labels of the slew rates, as the INDI telescope base class names them
SLEW_RATE_LABELS = {"1x": "Guide", "2x": "Centering", "3x": "Find", "4x": "Max"}


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
        - guide_rate: Speed of the guide pulses, as a multiple of the sidereal rate
                      (tests use a fast one, so a calibration takes seconds, not minutes)
        - track_drops: How many times switching tracking on is answered "tracking" and switched
                       off again 50 ms later, as the iOptron v3 driver does with a HAZ31
    """

    def __init__(self, port: int = 0, solar: bool = True, refuse=(), silent=(), device: str = DEVICE,
                 guide_rate: float = GUIDE_RATE, track_drops: int = 0):
        self.device = device
        self.guide_rate = guide_rate
        self.track_drops = track_drops
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
            _Prop("DEVICE_AUTO_SEARCH", SWITCH, {"INDI_ENABLED": False, "INDI_DISABLED": True}, rule="OneOfMany",
                  needs_connection=False),
            _Prop("CONNECTION_MODE", SWITCH, {"CONNECTION_SERIAL": True, "CONNECTION_TCP": False},
                  rule="OneOfMany", needs_connection=False),
            _Prop("DEVICE_ADDRESS", TEXT, {"ADDRESS": "", "PORT": ""}, needs_connection=False),
            _Prop("GEOGRAPHIC_COORD", NUMBER, {"LAT": 0.0, "LONG": 0.0, "ELEV": 0.0}),
            _Prop("TIME_UTC", TEXT, {"UTC": "", "OFFSET": "0"}),
            _Prop("EQUATORIAL_EOD_COORD", NUMBER, dict(zip(("RA", "DEC"), sun_position())), perm="ro"),
            _Prop("TELESCOPE_TRACK_MODE", SWITCH, modes, rule="OneOfMany"),
            _Prop("TELESCOPE_TRACK_STATE", SWITCH, {"TRACK_ON": False, "TRACK_OFF": True}, rule="OneOfMany"),
            _Prop("TELESCOPE_PARK", SWITCH, {"PARK": False, "UNPARK": True}, rule="OneOfMany"),
            _Prop("TELESCOPE_ABORT_MOTION", SWITCH, {"ABORT": False}, rule="AtMostOne"),
            _Prop("TELESCOPE_TIMED_GUIDE_NS", NUMBER, {"TIMED_GUIDE_N": 0.0, "TIMED_GUIDE_S": 0.0}),
            _Prop("TELESCOPE_TIMED_GUIDE_WE", NUMBER, {"TIMED_GUIDE_W": 0.0, "TIMED_GUIDE_E": 0.0}),
            _Prop("TELESCOPE_SLEW_RATE", SWITCH, {"1x": True, "2x": False, "3x": False, "4x": False},
                  rule="OneOfMany"),
            _Prop("TELESCOPE_MOTION_NS", SWITCH, {"MOTION_NORTH": False, "MOTION_SOUTH": False}, rule="AtMostOne"),
            _Prop("TELESCOPE_MOTION_WE", SWITCH, {"MOTION_WEST": False, "MOTION_EAST": False}, rule="AtMostOne"),
        ]
        self.props = {p.name: p for p in props}
        self._server = socket.create_server(("127.0.0.1", port))
        self.port = self._server.getsockname()[1]
        self._running = True
        self._thread = threading.Thread(target=self._accept, name="indi-simulator", daemon=True)
        self._thread.start()
        threading.Thread(target=self._move, name="indi-simulator-motion", daemon=True).start()
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

    # ---------------------------------------------------------------- motion

    def _offset(self, ra_h: float = 0.0, dec_deg: float = 0.0) -> None:
        """Move the pointing; called with the lock held."""
        coord = self.props["EQUATORIAL_EOD_COORD"].values
        coord["RA"] = (coord["RA"] + ra_h) % 24.0
        coord["DEC"] = max(-90.0, min(90.0, coord["DEC"] + dec_deg))

    def _move(self) -> None:
        """Move the pointing with the sky and the motors, and tell the clients once a second."""
        last, last_sent = time.monotonic(), 0.0
        while self._running:
            time.sleep(TICK_S)
            now = time.monotonic()
            dt, last = now - last, now
            with self._lock:
                if not self.connected:
                    continue
                props = self.props
                tracking = props["TELESCOPE_TRACK_STATE"].values["TRACK_ON"]
                if not tracking and not props["TELESCOPE_PARK"].values["PARK"]:
                    # A mount standing still sees the sky turn past it
                    self._offset(ra_h=SIDEREAL_H_PER_S * dt)
                rate = next((k for k, on in props["TELESCOPE_SLEW_RATE"].values.items() if on), "1x")
                step_deg = SLEW_RATE_MULTIPLES.get(rate, 1.0) * 15.0 / 3600.0 * dt
                ns, we = props["TELESCOPE_MOTION_NS"].values, props["TELESCOPE_MOTION_WE"].values
                moving = any(ns.values()) or any(we.values())
                self._offset(dec_deg=step_deg * (ns["MOTION_NORTH"] - ns["MOTION_SOUTH"]),
                             ra_h=step_deg / 15.0 * (we["MOTION_EAST"] - we["MOTION_WEST"]))
                if moving or now - last_sent >= 1.0:
                    last_sent = now
                    xml = self._vector(props["EQUATORIAL_EOD_COORD"], "set")
                else:
                    xml = ""
            if xml:
                self._broadcast(xml)

    def _pulse(self, name: str, changes: dict) -> None:
        """Apply a guide pulse at once; called with the lock held."""
        step_deg = self.guide_rate * 15.0 / 3600.0 / 1000.0     # per millisecond
        for element, ms in changes.items():
            sign = {"TIMED_GUIDE_N": 1, "TIMED_GUIDE_S": -1, "TIMED_GUIDE_E": 1, "TIMED_GUIDE_W": -1}[element]
            if name.endswith("_NS"):
                self._offset(dec_deg=sign * step_deg * ms)
            else:
                self._offset(ra_h=sign * step_deg * ms / 15.0)

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

    def _drop_tracking(self) -> None:
        """Switch tracking off again, as a driver does when the mount did not take the command."""
        with self._lock:
            prop = self.props["TELESCOPE_TRACK_STATE"]
            prop.values.update(TRACK_ON=False, TRACK_OFF=True)
            prop.state = IDLE
            xml = self._vector(prop, "set")
        self._broadcast(xml)

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
        def label(key):
            return f" label={quoteattr(SLEW_RATE_LABELS.get(key, key))}" if verb == "def" else ""

        body = "".join(f"<{element}{prop.kind} name={quoteattr(k)}{label(k)}>{self._value_text(prop.kind, v)}"
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
                self.props["EQUATORIAL_EOD_COORD"].values["DEC"] = 90.0     # parked at the pole
            if name == "TELESCOPE_ABORT_MOTION":
                for motion in ("TELESCOPE_MOTION_NS", "TELESCOPE_MOTION_WE"):
                    self.props[motion].values.update({k: False for k in self.props[motion].values})
            if name.startswith("TELESCOPE_TIMED_GUIDE"):
                self._pulse(name, changes)
            # A guide pulse or a park starts something long: answer Busy first.  Tracking and moving
            # stay Busy for as long as they last, as real INDI drivers keep them
            long_change = name.startswith("TELESCOPE_TIMED_GUIDE") or name == "TELESCOPE_PARK"
            if name == "TELESCOPE_TRACK_STATE":
                prop.state = BUSY if prop.values["TRACK_ON"] else IDLE
            elif name.startswith("TELESCOPE_MOTION"):
                prop.state = BUSY if any(prop.values.values()) else IDLE
            else:
                prop.state = BUSY if long_change else OK
            xml = self._vector(prop, "set")
            if long_change:
                prop.state = OK
                xml += self._vector(prop, "set")
            if name == "TELESCOPE_PARK":
                xml += self._vector(self.props["TELESCOPE_TRACK_STATE"], "set")
            if long_change:
                xml += self._vector(self.props["EQUATORIAL_EOD_COORD"], "set")
            drop = name == "TELESCOPE_TRACK_STATE" and prop.values["TRACK_ON"] and self.track_drops > 0
            if drop:
                self.track_drops -= 1
        self._broadcast(xml)
        if drop:
            timer = threading.Timer(0.05, self._drop_tracking)
            timer.daemon = True
            timer.start()

        if name == "CONNECTION" and self.connected != was_connected:
            with self._lock:
                if self.connected:
                    xml = "".join(self._vector(p, "def") for p in self.props.values() if p.needs_connection)
                else:
                    xml = "".join(f"<delProperty device={quoteattr(self.device)} name={quoteattr(p.name)}/>"
                                  for p in self.props.values() if p.needs_connection)
            self._broadcast(xml)

