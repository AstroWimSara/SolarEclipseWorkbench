import argparse
import logging
from time import sleep

from astropy.time import Time

from solareclipseworkbench import camera
from solareclipseworkbench import gui
from solareclipseworkbench.fuji_camera import maybe_reexec_for_fuji_sdk
from solareclipseworkbench.hardware_registry import register_hardware
from solareclipseworkbench import solar_radius
from solareclipseworkbench.location_ui import ConfigManager
from solareclipseworkbench.logging_setup import setup_logging
from solareclipseworkbench.reference_moments import calculate_reference_moments
from solareclipseworkbench.relay_trigger import RelayError, open_trigger
from solareclipseworkbench.utils import observe_solar_eclipse


def open_relay(args) -> None:
    """Open and register the relay asked for with --relay, for the relay_* script commands.

    The GUI connects the relay from its toolbar.  On the command line nothing
    is opened unless --relay is given: 'auto' tries every USB serial port,
    and those can be a GPS receiver or another device.
    """
    if not args.relay:
        return
    port = None if args.relay == "auto" else args.relay
    try:
        trigger = open_trigger(args.relay_backend, port,
                               s2_channel=args.relay_s2, s1_channel=args.relay_s1)
    except RelayError as exc:
        logging.error("No relay could be opened, the relay commands in the script will fail: %s", exc)
        print(f"WARNING: no relay could be opened: {exc}")
        return
    register_hardware('relay', trigger)


def main(args):
    if args.gui:
        gui.main()
    else:
        # Before anything else: when the Fujifilm SDK libraries are not on the
        # library path yet, the process restarts here, before a log file is made.
        maybe_reexec_for_fuji_sdk()
        setup_logging("sew")
        solar_radius.load_saved()
        # Check for all needed parameters
        # Use "is not False" rather than truthiness: an altitude (or longitude/
        # latitude) of 0 is valid but falsy, and would otherwise be rejected.
        if (args.date is not False and args.longitude is not False
                and args.latitude is not False and args.altitude is not False
                and args.script is not False):
            eclipse_date = Time(args.date)
            timings, magnitude, eclipse_type = calculate_reference_moments(args.longitude, args.latitude, args.altitude,
                                                                           eclipse_date)

            filename = args.script

            cameras = camera.get_camera_dict(
                is_simulator=args.virtual_camera,
                alias_map=ConfigManager().get_camera_aliases() or None,
            )

            open_relay(args)

            # Only do a simulation if args.c1 is set
            if args.ref_moment:
                scheduler, _ = observe_solar_eclipse(timings, filename, cameras, None, args.ref_moment, args.minutes)
            else:
                scheduler, _ = observe_solar_eclipse(timings, filename, cameras, None, None, None)

            while len(scheduler.get_jobs()) > 0:
                sleep(5)
        else:
            print("When using the command line, you must specify the date, "
                  "script to execute and the exact location of the solar eclipse.")
            exit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Solar Eclipse Workbench")
    parser.add_argument(
        "-g",
        "--gui",
        help="start the Solar Eclipse Workbench GUI",
        default=False,
        action='store_true'
    )
    parser.add_argument(
        "-d",
        "--date",
        help="date of the solar eclipse (in YYYY-MM-DD format)",
        default=False,
    )
    parser.add_argument(
        "-lon",
        "--longitude",
        help="longitude of the location where to watch the solar eclipse (W is negative)",
        default=False,
        type=float
    )

    parser.add_argument(
        "-lat",
        "--latitude",
        help="latitude of the location where to watch the solar eclipse (N is positive)",
        default=False,
        type=float
    )

    parser.add_argument(
        "-alt",
        "--altitude",
        help="altitude of the location where to watch the solar eclipse (in meters)",
        default=False,
        type=float
    )

    parser.add_argument(
        "-s",
        "--script",
        help="script to execute (with voice prompts and camera commands)",
        default=False,
    )

    parser.add_argument(
        "--virtual-camera",
        help="Use virtual camera instead of physical cameras",
        action='store_true',
        default=False,
    )

    parser.add_argument(
        "--relay",
        help="open a USB relay shutter trigger for the relay_* commands: a serial port, or 'auto'",
        default=None,
    )

    parser.add_argument(
        "--relay-backend",
        help="relay board type: auto (default), lcus, dsd, numato, hid or simulated",
        default="auto",
    )

    parser.add_argument(
        "--relay-s2",
        help="relay channel wired to S2, the full press (default 1)",
        default=1,
        type=int,
    )

    parser.add_argument(
        "--relay-s1",
        help="relay channel wired to S1, the half press (default: S1 shares the S2 contact)",
        default=None,
        type=int,
    )

    parser.add_argument(
        "-r",
        "--ref_moment",
        help="reference moment for simulation (C1, C2, C3, C4, Max)",
        default=False,
        type=str
    )

    parser.add_argument(
        "-m",
        "--minutes",
        help="minutes to reference moment for simulation",
        default=False,
        type=float
    )

    arguments = parser.parse_args()

    main(arguments)
