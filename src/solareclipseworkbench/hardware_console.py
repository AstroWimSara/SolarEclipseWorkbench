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

A mount is tested through its INDI server (``indiserver`` with the mount's driver):

    mount connect localhost         connect, list what the mount reports
    mount site 40.4 -3.7 650        send a location and the time
    mount track                     track at the solar rate
    mount guide N 1000              a one-second guide pulse
"""

import argparse
import logging
import shlex
import sys
import time
from typing import Optional

from solareclipseworkbench import relay_trigger as relay_mod
from solareclipseworkbench.indi_client import IndiError
from solareclipseworkbench.mount import Mount, MountError, SIMULATED_HOST

logger = logging.getLogger(__name__)

BANNER = """Solar Eclipse Workbench — hardware bench console
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

Telescope mount (through an INDI server)
  mount connect [host[:port]] [device] [serial port]
                                connect (default localhost; 'simulated' for none)
  mount status                  what the mount reports
  mount site <lat> <lon> [elev] send a location (north and east positive) and the time
  mount track                   track at the solar rate (unparks first)
  mount stop                    stop tracking
  mount park / unpark           park (moves the mount!) or unpark
  mount abort                   stop every motion
  mount guide <N|S|E|W> <ms>    one guide pulse
  mount disconnect              close the connection; the mount keeps tracking
"""


class Console:
    def __init__(self, simulate: bool = False):
        self.simulate = simulate
        self.trigger: Optional[relay_mod.RelayTrigger] = None
        self.mount: Optional[Mount] = None

    # ------------------------------------------------------------------ helpers

    def out(self, message: str = "") -> None:
        print(message, flush=True)

    def need_trigger(self) -> bool:
        if self.trigger is None:
            self.out("No relay connected.  Run 'relay connect' first.")
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
        self.out(f"Mount:  {self.mount.describe() if self.mount is not None else 'not connected'}")
        if self.trigger is None:
            self.out("Relay:  not connected")
            return
        wiring = self.trigger.wiring
        layout = ("single channel, S2 on %d" % wiring.s2_channel if wiring.is_single_channel
                  else "dual channel, S1 on %d, S2 on %d" % (wiring.s1_channel, wiring.s2_channel))
        self.out(f"Relay:  {self.trigger.describe()}")
        self.out(f"        {layout}")
        self.out(f"        closed channels: {sorted(self.trigger.closed_channels) or 'none'}")

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
        if sub != "connect" and self.mount is None:
            self.out("No mount connected.  Run 'mount connect' first.")
            return
        handler(rest)

    def _mount_connect(self, args) -> None:
        if self.mount is not None:
            self.mount.close()
            self.mount = None
        address = args[0] if args else (SIMULATED_HOST if self.simulate else "localhost")
        device = args[1] if len(args) > 1 else None
        port = args[2] if len(args) > 2 else None
        self.mount = Mount.open(address, device, port)
        self.out(f"Connected: {self.mount.describe()}")
        self._mount_status([])

    def _mount_status(self, args) -> None:
        mount = self.mount
        self.out(f"  {mount.describe()}")
        position = mount.position()
        if position is not None:
            self.out(f"  RA {position[0]:.4f} h, Dec {position[1]:.4f}°")
        self.out(f"  track mode {mount.track_mode or 'unknown'}"
                 f"{'' if mount.has_solar_rate else ' (no solar rate)'}")

    def _mount_site(self, args) -> None:
        if len(args) < 2:
            self.out("Usage: mount site <latitude> <longitude> [elevation]")
            return
        sent = self.mount.send_site(float(args[0]), float(args[1]), float(args[2]) if len(args) > 2 else 0.0)
        self.out("Sent: " + ("; ".join(sent) or "nothing (the driver takes neither)"))

    def _mount_track(self, args) -> None:
        rate = self.mount.track_solar()
        self.out(f"Tracking at the {rate} rate.")

    def _mount_stop(self, args) -> None:
        self.mount.stop_tracking()
        self.out("Tracking stopped.")

    def _mount_park(self, args) -> None:
        self.mount.park()
        self.out("Parking.")

    def _mount_unpark(self, args) -> None:
        self.mount.unpark()
        self.out("Unparked.")

    def _mount_abort(self, args) -> None:
        self.mount.abort()
        self.out("Motion aborted.")

    def _mount_guide(self, args) -> None:
        if len(args) < 2:
            self.out("Usage: mount guide <N|S|E|W> <milliseconds>")
            return
        self.mount.guide(args[0], float(args[1]))
        self.out(f"Guide pulse {args[0].upper()} {float(args[1]):.0f} ms sent.")

    def _mount_disconnect(self, args) -> None:
        self.mount.close()
        self.mount = None
        self.out("Disconnected.  The mount keeps tracking.")

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
        except (relay_mod.RelayError, MountError, IndiError) as exc:
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
        if self.mount is not None:
            self.mount.close()
            self.mount = None
        if self.trigger is not None:
            self.trigger.close()
            self.out("Relay contacts released.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Bench console for the USB relay shutter trigger and the telescope mount")
    parser.add_argument("--simulate", action="store_true",
                        help="use a simulated relay, to try the console with nothing connected")
    parser.add_argument("--relay-port", help="connect the relay on this port at startup")
    parser.add_argument("--relay-kind", default="auto",
                        help="relay backend: auto, lcus, dsd, numato, hid, simulated")
    parser.add_argument("--debug", action="store_true", help="log every contact change")
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
