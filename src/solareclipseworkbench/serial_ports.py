"""Serial port enumeration, with the platform differences handled once.

macOS exposes each USB serial adapter twice: as ``/dev/tty.usbserial-X`` and as
``/dev/cu.usbserial-X``.  They are not interchangeable.  Opening the ``tty``
node blocks until it sees carrier detect, which a relay board or a mount
controller never asserts, so the open hangs or times out.  The ``cu`` node
("call-up") does not wait, and is the one to use for anything that is not a
modem.

Enumerating both would also make every device appear twice in the bench
console's scan, and half of those entries would hang if selected.
"""

import logging
import sys

import serial.tools.list_ports

logger = logging.getLogger(__name__)


def usb_serial_ports() -> list:
    """USB serial ports worth trying, as pyserial ListPortInfo objects.

    Ports with no USB vendor ID are dropped: on macOS those are the built-in
    Bluetooth serial devices, which are never what we are looking for.
    """
    ports = [p for p in serial.tools.list_ports.comports() if p.vid is not None]

    if sys.platform == "darwin":
        # Prefer the call-up node, and drop the matching tty node so the same
        # adapter is not offered twice.
        callout = [p for p in ports if "/cu." in p.device]
        if callout:
            paired = {p.device.replace("/cu.", "/tty.") for p in callout}
            ports = callout + [p for p in ports if p.device not in paired
                               and "/cu." not in p.device]
            logger.debug("macOS: using call-up nodes %s", [p.device for p in callout])
        ports = _one_node_per_chip(ports)

    return ports


#: Driver families that can both claim the same chip, best first.  The Silicon
#: Labs kext names its nodes SLAB_USBtoUART*, Apple's built-in CP210x driver
#: names them usbserial-*.
_DRIVER_ORDER = ("SLAB_USBtoUART", "usbserial")


def _one_node_per_chip(ports: list) -> list:
    """Collapse the several device nodes that can front one physical adapter.

    With both the Silicon Labs kext and Apple's own CP210x driver installed,
    every adapter appears twice - /dev/cu.SLAB_USBtoUART8 and
    /dev/cu.usbserial-7 are one chip, not two.  Nothing in the name says so,
    and cheap boards can ship with identical serial numbers (often "0001"),
    so the only field that separates one adapter from another is `location`.

    Left uncollapsed, a scan offers four ports for two devices, and a probe can
    open another device's chip through its alias: that device holds it,
    pyserial opens exclusively, and the relay reports its port locked while
    pointing at hardware that is not the relay.
    """
    groups: dict = {}
    for p in ports:
        # location is per physical port; fall back to the name when a driver
        # does not report one, which at worst keeps today's behaviour.
        ident = getattr(p, "location", None) or p.device
        groups.setdefault(ident, []).append(p)

    def rank(port):
        for i, family in enumerate(_DRIVER_ORDER):
            if family in port.device:
                return i
        return len(_DRIVER_ORDER)

    kept = []
    for ident, group in groups.items():
        group.sort(key=rank)
        kept.append(group[0])
        if len(group) > 1:
            logger.debug("macOS: %s is one adapter behind %s; using %s",
                         ident, [g.device for g in group], group[0].device)
    return kept


def resolve_port(requested: str) -> str:
    """The device node to actually open for a port somebody asked for.

    Two things make a saved port name go stale.  Adapters can swap names when
    they are replugged (usbserial-0001 one evening, usbserial-7 the next), and
    on macOS each chip can front two nodes, so collapsing them to one can hide
    the name a previous run saved: /dev/cu.usbserial-0001 and
    /dev/cu.SLAB_USBtoUART can be one adapter.

    So a request that is not currently offered is matched by physical port -
    `location` - to the node that is.  If nothing matches, the request is
    returned unchanged and the caller fails as it would have anyway.
    """
    if not requested:
        return requested
    offered = usb_serial_ports()
    if any(p.device == requested for p in offered):
        return requested

    where = None
    for p in serial.tools.list_ports.comports():
        if p.device == requested:
            where = getattr(p, "location", None)
            break
    if where:
        for p in offered:
            if getattr(p, "location", None) == where:
                logger.info("%s is not offered; it is the same adapter as %s "
                            "(port %s), using that", requested, p.device, where)
                return p.device
    return requested
