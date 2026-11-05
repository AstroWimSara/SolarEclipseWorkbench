"""Bench console for the USB relay shutter trigger and the telescope mount.

For building and testing the hardware, not for running an eclipse.  Every
command does one step, so a fault can be isolated to one wire, one contact or
one command.

    sew_hardware
    sew_hardware --simulate
    sew_hardware --relay-port /dev/ttyUSB0

Typical order when wiring a trigger for the first time, with the camera NOT yet
connected:

    scan                 what the machine can see
    relay connect        open the board
    relay idle           confirm every contact is open and stays open
    relay pulse 1 0.5    watch and listen for one channel
    relay walk           step through channels to map them to wires
    relay timing         how much jitter the host adds

Then connect the camera, lens cap on, and use ``relay shoot`` and ``relay burst``.

For a mount, ``mount probe`` finds the port and the baud rate of the controller,
and ``mount connect`` opens it.
"""

import argparse
import logging
import shlex
import sys
import time
from typing import Optional

from solareclipseworkbench import mounts as mount_mod
from solareclipseworkbench import relay_trigger as relay_mod
from solareclipseworkbench.mounts.onstepx import DEFAULT_TCP_PORT, probe_serial

logger = logging.getLogger(__name__)

BANNER = """Solar Eclipse Workbench — relay bench console
Type 'help' for commands, 'quit' to leave.
Contacts are opened automatically on exit."""

HELP = """
General
  scan                          list USB serial ports and likely relay boards
  status                        show what is currently connected
  quit / exit                   release contacts and leave

Relay trigger
  relay backends                list installed relay backends
  relay connect [port] [kind]   open the relay (kind: auto, or see 'relay backends')
  relay wiring <s2> [s1]        set channels; omit s1 for single-channel wiring
  relay idle                    verify all contacts open, and stay open for 3 s
  relay close <ch>              close one channel and leave it closed
  relay open <ch>               open one channel
  relay pulse <ch> [seconds]    close one channel briefly (default 0.25)
  relay walk [seconds]          pulse each channel in turn, to map channel to wire
  relay shoot                   one frame, using the configured wiring
  relay burst <seconds> [ival]  hold (or pulse at ival) for a duration
  relay bulb <seconds>          hold a bulb exposure
  relay timing [samples]        measure host-to-contact latency and spread
  relay events [n]              show the last n contact transitions

Mount
  mount drivers                 list installed mount drivers
  mount find                    ask every driver where its mounts can be
  mount connect [port] [driver] open the mount (driver: onstepx, or simulator with --simulate)
  mount tcp <host> [port]       open an OnStepX mount over the network
  mount probe [port]            find the baud rate at which the controller answers
  mount info                    driver, product name and capabilities
  mount status                  decoded status of the mount
  mount pos                     current RA/Dec and Alt/Az
  mount sun                     where the Sun is now
  mount goto <ra_h> <dec_deg>   slew to coordinates
  mount gotosun [wait]          slew to the Sun
  mount track <rate>            sidereal | solar | lunar | king
  mount tracking <on|off>       start or stop tracking
  mount move <dir> [seconds]    move north|south|east|west, then stop
  mount rate <preset>           guide | center | find | fast | slew
  mount park / unpark
  mount stop                    stop all motion
  mount raw <cmd> [kind]        send any command (kind: terminated|bool|char|none)
"""


class Console:
    def __init__(self, simulate: bool = False):
        self.simulate = simulate
        self.trigger: Optional[relay_mod.RelayTrigger] = None
        self.mount: Optional[mount_mod.MountDriver] = None

    # ------------------------------------------------------------------ helpers

    def out(self, message: str = "") -> None:
        print(message, flush=True)

    def need_trigger(self) -> bool:
        if self.trigger is None:
            self.out("No relay connected.  Run 'relay connect' first.")
            return False
        return True

    def need_mount(self) -> bool:
        if self.mount is None:
            self.out("No mount connected.  Run 'mount connect' first.")
            return False
        return True

    # ------------------------------------------------------------------ general

    def cmd_scan(self, args) -> None:
        """Every place a relay backend thinks one of its boards might be."""
        candidates = relay_mod.discover_relays()
        if not candidates:
            self.out("Nothing found.  Connect the hardware, or use --simulate.")
            return

        for candidate in candidates:
            self.out(f"  {candidate.target:<24} {candidate.driver:<10} {candidate.description}")
        self.out()
        self.out("A USB serial adapter is a reason to probe, not proof of what is behind it.")
        self.out("Most relay boards answer nothing, so map one by pulsing and listening.")

    def cmd_status(self, args) -> None:
        if self.trigger is None:
            self.out("Relay:  not connected")
        else:
            wiring = self.trigger.wiring
            layout = ("single channel, S2 on %d" % wiring.s2_channel if wiring.is_single_channel
                      else "dual channel, S1 on %d, S2 on %d" % (wiring.s1_channel, wiring.s2_channel))
            self.out(f"Relay:  {self.trigger.describe()}")
            self.out(f"        {layout}")
            self.out(f"        closed channels: {sorted(self.trigger.closed_channels) or 'none'}")
        if self.mount is None:
            self.out("Mount:  not connected")
        else:
            self.out(f"Mount:  {self.mount.describe()}")
            try:
                self.out(f"        {self.mount.status().summary()}")
            except mount_mod.MountError as exc:
                self.out(f"        status not available: {exc}")

    # -------------------------------------------------------------------- relay

    def cmd_relay(self, args) -> None:
        if not args:
            self.out("Missing relay subcommand.  See 'help'.")
            return
        sub, rest = args[0], args[1:]
        handler = getattr(self, f"_relay_{sub}", None)
        if handler is None:
            self.out(f"Unknown relay subcommand: {sub}")
            return
        handler(rest)

    def _relay_backends(self, args) -> None:
        self.out("Installed relay backends:")
        for backend in relay_mod.list_backends():
            self.out(f"  {backend.name:<12} {backend.description or backend.__doc__.splitlines()[0]}")

    def _relay_connect(self, args) -> None:
        port = args[0] if args else None
        kind = args[1] if len(args) > 1 else ("simulated" if self.simulate else "auto")
        try:
            self.trigger = relay_mod.open_trigger(kind=kind, port=port)
            self.out(f"Connected: {self.trigger.describe()}")
            self.out("Contacts are open.  Verify with 'relay idle' before wiring the camera.")
        except relay_mod.RelayError as exc:
            self.out(f"Could not connect: {exc}")

    def _relay_wiring(self, args) -> None:
        if not self.need_trigger():
            return
        if not args:
            self.out("Usage: relay wiring <s2_channel> [s1_channel]")
            return
        s2 = int(args[0])
        s1 = int(args[1]) if len(args) > 1 else None
        self.trigger.wiring = relay_mod.Wiring(s2_channel=s2, s1_channel=s1)
        self.out(f"Wiring set: {self.trigger.describe()}")

    def _relay_idle(self, args) -> None:
        """Confirm nothing is closed, and nothing closes on its own."""
        if not self.need_trigger():
            return
        self.trigger.release_all()
        self.out("All channels commanded open.  Watching for 3 s...")
        self.out("Meter across NO and COM now — it must read open the whole time.")
        time.sleep(3.0)
        closed = sorted(self.trigger.closed_channels)
        if closed:
            self.out(f"WARNING: channels still believed closed: {closed}")
        else:
            self.out("Idle state is clean.")

    def _relay_close(self, args) -> None:
        if not self.need_trigger() or not args:
            self.out("Usage: relay close <channel>")
            return
        channel = int(args[0])
        self.trigger._set(channel, True)
        self.out(f"Channel {channel} closed.  It stays closed until you open it.")

    def _relay_open(self, args) -> None:
        if not self.need_trigger() or not args:
            self.out("Usage: relay open <channel>")
            return
        channel = int(args[0])
        self.trigger._set(channel, False)
        self.out(f"Channel {channel} open.")

    def _relay_pulse(self, args) -> None:
        if not self.need_trigger() or not args:
            self.out("Usage: relay pulse <channel> [seconds]")
            return
        channel = int(args[0])
        seconds = float(args[1]) if len(args) > 1 else 0.25
        self.trigger._set(channel, True)
        time.sleep(seconds)
        self.trigger._set(channel, False)
        self.out(f"Pulsed channel {channel} for {seconds:.2f} s.")

    def _relay_walk(self, args) -> None:
        """Pulse each channel in turn so you can map channel numbers to wires."""
        if not self.need_trigger():
            return
        seconds = float(args[0]) if args else 0.4
        for channel in (1, 2, 3, 4):
            self.out(f"  channel {channel}...")
            try:
                self.trigger._set(channel, True)
                time.sleep(seconds)
                self.trigger._set(channel, False)
            except relay_mod.RelayError as exc:
                self.out(f"    channel {channel} refused: {exc}")
            time.sleep(0.3)
        self.out("Walk complete.  Boards ignore channels they do not have.")

    def _relay_shoot(self, args) -> None:
        if not self.need_trigger():
            return
        self.trigger.shoot()
        self.out("Fired one frame.")

    def _relay_burst(self, args) -> None:
        if not self.need_trigger() or not args:
            self.out("Usage: relay burst <seconds> [interval]")
            return
        duration = float(args[0])
        interval = float(args[1]) if len(args) > 1 else None
        pulses = self.trigger.burst(duration, interval)
        if interval is None:
            self.out(f"Held the contact for {duration:.2f} s.  Count the frames on the camera —")
            self.out("that number divided by the duration is your real frame rate.")
        else:
            self.out(f"Issued {pulses} pulses over {duration:.2f} s.")

    def _relay_bulb(self, args) -> None:
        if not self.need_trigger() or not args:
            self.out("Usage: relay bulb <seconds>")
            return
        seconds = float(args[0])
        self.out(f"Holding bulb for {seconds:.2f} s (shutter dial must be at B)...")
        self.trigger.bulb(seconds)
        self.out("Released.")

    def _relay_timing(self, args) -> None:
        if not self.need_trigger():
            return
        samples = int(args[0]) if args else 20
        self.out(f"Measuring {samples} close/open cycles...")
        stats = self.trigger.timing_sample(samples)
        self.out(f"  mean   {stats['mean_ms']:.2f} ms")
        self.out(f"  median {stats['median_ms']:.2f} ms")
        self.out(f"  min    {stats['min_ms']:.2f} ms")
        self.out(f"  max    {stats['max_ms']:.2f} ms")
        self.out(f"  spread {stats['spread_ms']:.2f} ms")
        self.out()
        self.out("This is the host-to-contact path only.  Camera shutter lag is not included —")
        self.out("for that, photograph a running millisecond timer and compare.")

    def _relay_events(self, args) -> None:
        if not self.need_trigger():
            return
        limit = int(args[0]) if args else 20
        events = self.trigger.recent_events(limit)
        if not events:
            self.out("No contact transitions recorded yet.")
            return
        self.out("      time  ch  state   elapsed")
        for event in events:
            stamp = time.strftime("%H:%M:%S", time.localtime(event.at))
            state = "closed" if event.closed else "open"
            flag = f"  ERROR: {event.error}" if event.error else ""
            self.out(f"  {stamp}  {event.channel:>2}  {state:<6}  {event.elapsed_ms:6.2f} ms{flag}")

    # -------------------------------------------------------------------- mount

    def cmd_mount(self, args) -> None:
        if not args:
            self.out("Missing mount subcommand.  See 'help'.")
            return
        sub, rest = args[0], args[1:]
        handler = getattr(self, f"_mount_{sub}", None)
        if handler is None:
            self.out(f"Unknown mount subcommand: {sub}")
            return
        handler(rest)

    def _mount_drivers(self, args) -> None:
        self.out("Installed mount drivers:")
        for driver in mount_mod.list_drivers():
            self.out(f"  {driver.name:<12} {driver.description or driver.display_name}")

    def _mount_find(self, args) -> None:
        candidates = mount_mod.discover_mounts()
        if not candidates:
            self.out("Nothing found.  Connect the mount, or use 'mount connect - simulator'.")
            return
        for candidate in candidates:
            self.out(f"  {candidate}")
        self.out()
        self.out("A USB serial adapter is a reason to probe, not proof of what is behind it.")
        self.out("'mount probe <port>' asks the port for an LX200 answer.")

    def _mount_connect(self, args) -> None:
        port = args[0] if args and args[0] not in ("-", "auto") else None
        driver = args[1] if len(args) > 1 else ("simulator" if self.simulate else "onstepx")
        config = {"port": port} if port else {}
        self.mount = mount_mod.connect(driver=driver, **config)
        self.out(f"Connected: {self.mount.describe()}")

    def _mount_tcp(self, args) -> None:
        if not args:
            self.out("Usage: mount tcp <host> [port]")
            return
        tcp_port = int(args[1]) if len(args) > 1 else DEFAULT_TCP_PORT
        self.mount = mount_mod.connect(driver="onstepx", host=args[0], tcp_port=tcp_port)
        self.out(f"Connected: {self.mount.describe()}")

    def _mount_probe(self, args) -> None:
        ports = [args[0]] if args else [c.target for c in mount_mod.discover_mounts("onstepx")]
        if not ports:
            self.out("No USB serial ports to probe.")
            return
        for port in ports:
            self.out(f"Probing {port}...")
            baudrate = probe_serial(port)
            if baudrate:
                self.out(f"  the controller answers at {baudrate} baud")
            else:
                self.out("  no answer at any baud rate")

    def _mount_info(self, args) -> None:
        if not self.need_mount():
            return
        capabilities = self.mount.capabilities
        self.out(f"  {self.mount.describe()}")
        self.out(f"  driver:   {self.mount.name}")
        self.out(f"  rates:    {', '.join(capabilities.tracking_rates)}")
        self.out(f"  can:      {'goto ' if capabilities.goto else ''}{'sync ' if capabilities.sync else ''}"
                 f"{'park ' if capabilities.park else ''}{'guide ' if capabilities.pulse_guide else ''}"
                 f"{'site-and-time' if capabilities.site_time else ''}")

    def _mount_status(self, args) -> None:
        if not self.need_mount():
            return
        status = self.mount.status()
        self.out(f"  raw:      {status.raw}")
        self.out(f"  summary:  {status.summary()}")
        self.out(f"  tracking: {status.tracking} ({status.tracking_rate})")
        self.out(f"  slewing:  {status.slewing}")
        self.out(f"  parked:   {status.parked}")
        self.out(f"  at home:  {status.at_home}")
        self.out(f"  type:     {status.mount_type}")
        if status.error_code and status.error_code != "0":
            self.out(f"  error:    {status.error_code}")

    def _mount_pos(self, args) -> None:
        if not self.need_mount():
            return
        ra, dec = self.mount.get_radec()
        self.out(f"  RA  {mount_mod.format_ra(ra)}  ({ra:.5f} h)")
        self.out(f"  Dec {mount_mod.format_dec(dec)}  ({dec:.5f}°)")
        try:
            alt, az = self.mount.get_altaz()
            self.out(f"  Alt {alt:.4f}°  Az {az:.4f}°")
        except mount_mod.MountError as exc:
            self.out(f"  Alt/Az not available: {exc}")

    def _mount_sun(self, args) -> None:
        ra, dec = mount_mod.sun_radec()
        self.out(f"  The Sun is at RA {mount_mod.format_ra(ra)}  Dec {mount_mod.format_dec(dec)}")

    def _mount_goto(self, args) -> None:
        if not self.need_mount():
            return
        if len(args) < 2:
            self.out("Usage: mount goto <ra_hours> <dec_degrees>")
            return
        self.mount.goto(float(args[0]), float(args[1]))
        self.out("Slew accepted.")

    def _mount_gotosun(self, args) -> None:
        if not self.need_mount():
            return
        wait = bool(args) and args[0].lower() in ("wait", "true", "1", "yes")
        ra, dec = self.mount.goto_sun(wait=wait)
        self.out(f"Slewing to the Sun: RA {mount_mod.format_ra(ra)} Dec {mount_mod.format_dec(dec)}")
        if wait:
            self.out("Slew complete.")

    def _mount_track(self, args) -> None:
        if not self.need_mount():
            return
        if not args:
            self.out("Usage: mount track <sidereal|solar|lunar|king>")
            return
        self.mount.set_tracking_rate(args[0])
        self.out(f"Tracking rate set to {args[0]}.")

    def _mount_tracking(self, args) -> None:
        if not self.need_mount():
            return
        if not args:
            self.out("Usage: mount tracking <on|off>")
            return
        if args[0].lower() in ("on", "1", "true", "yes"):
            self.out("Tracking started." if self.mount.tracking_on() else "The mount did not start tracking.")
        else:
            self.out("Tracking stopped." if self.mount.tracking_off() else "The mount did not stop tracking.")

    def _mount_move(self, args) -> None:
        if not self.need_mount():
            return
        if not args:
            self.out("Usage: mount move <north|south|east|west> [seconds]")
            return
        direction = args[0]
        seconds = float(args[1]) if len(args) > 1 else 1.0
        self.mount.move(direction)
        try:
            time.sleep(seconds)
        finally:
            self.mount.stop_move(direction)
        self.out(f"Moved {direction} for {seconds:.2f} s.")

    def _mount_rate(self, args) -> None:
        if not self.need_mount():
            return
        if not args:
            self.out("Usage: mount rate <guide|center|find|fast|slew>")
            return
        self.mount.set_rate(args[0])
        self.out(f"Rate preset set to {args[0]}.")

    def _mount_park(self, args) -> None:
        if not self.need_mount():
            return
        self.out("Parked." if self.mount.park() else "The mount did not park.")

    def _mount_unpark(self, args) -> None:
        if not self.need_mount():
            return
        self.out("Unparked." if self.mount.unpark() else "The mount did not unpark.")

    def _mount_stop(self, args) -> None:
        if not self.need_mount():
            return
        self.mount.abort()
        self.out("All motion stopped.")

    def _mount_raw(self, args) -> None:
        if not self.need_mount():
            return
        if not args:
            self.out("Usage: mount raw <command> [terminated|bool|char|none]")
            return
        kind = args[1] if len(args) > 1 else "terminated"
        self.out(f"  -> {self.mount.raw(args[0], kind)!r}")

    # --------------------------------------------------------------------- loop

    def dispatch(self, line: str) -> bool:
        """Run one line.  Returns False to exit."""
        try:
            parts = shlex.split(line)
        except ValueError as exc:
            self.out(f"Could not parse that line: {exc}")
            return True

        if not parts:
            return True

        command, args = parts[0].lower(), parts[1:]

        if command in ("quit", "exit"):
            return False
        if command in ("help", "?"):
            self.out(HELP)
            return True

        handler = getattr(self, f"cmd_{command}", None)
        if handler is None:
            self.out(f"Unknown command: {command}.  Type 'help'.")
            return True

        try:
            handler(args)
        except (relay_mod.RelayError, mount_mod.MountError) as exc:
            self.out(f"Error: {exc}")
        except (ValueError, IndexError) as exc:
            self.out(f"Bad arguments: {exc}")
        return True

    def run(self) -> None:
        self.out(BANNER)
        if self.simulate:
            self.out("Running with simulated hardware — nothing will actually move.")
        self.out()
        try:
            while True:
                try:
                    line = input("sew> ")
                except EOFError:
                    self.out()
                    break
                except KeyboardInterrupt:
                    self.out("\nInterrupted — releasing contacts.")
                    break
                if not self.dispatch(line):
                    break
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        if self.trigger is not None:
            self.trigger.close()
            self.out("Relay contacts released.")
        if self.mount is not None:
            self.mount.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Bench console for the USB relay shutter trigger and the mount")
    parser.add_argument("--simulate", action="store_true",
                        help="use a simulated relay and mount, to try the console with nothing connected")
    parser.add_argument("--relay-port", help="connect the relay on this port at startup")
    parser.add_argument("--relay-kind", default="auto",
                        help="relay backend: auto, lcus, dsd, numato, hid, simulated")
    parser.add_argument("--mount-port", help="connect the mount on this port at startup")
    parser.add_argument("--mount-driver", default="onstepx", help="mount driver (see 'mount drivers')")
    parser.add_argument("--debug", action="store_true", help="log every contact change and mount command")
    parser.add_argument("command", nargs="*",
                        help="run a single command and exit, instead of starting the prompt")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    console = Console(simulate=args.simulate)

    # Call the handler directly rather than building a command string: an omitted
    # port would otherwise shift the remaining words into the wrong argument.
    if args.relay_port:
        console._relay_connect([args.relay_port, args.relay_kind])
    if args.mount_port:
        console.dispatch(f"mount connect {shlex.quote(args.mount_port)} {shlex.quote(args.mount_driver)}")

    if args.command:
        try:
            console.dispatch(" ".join(args.command))
        finally:
            console.shutdown()
        return 0

    console.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
