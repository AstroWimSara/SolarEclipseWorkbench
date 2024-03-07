import argparse
from time import sleep

from astropy.time import Time

import camera
from solareclipseworkbench import gui
from solareclipseworkbench.reference_moments import calculate_reference_moments
from solareclipseworkbench.utils import observe_solar_eclipse


def main(args):
    if args.gui:
        gui.main()
    else:
        # Check for all needed parameters
        if args.date and args.longitude and args.latitude and args.altitude and args.script:
            eclipse_date = Time(args.date)
            timings, magnitude, eclipse_type = calculate_reference_moments(args.longitude, args.latitude, args.altitude,
                                                                           eclipse_date)

            filename = args.script

            cameras = camera.get_camera_dict()

            # Only do a simulation if args.c1 is set
            if args.ref_moment:
                scheduler = observe_solar_eclipse(timings, filename, cameras, None, args.ref_moment, args.minutes)
            else:
                scheduler = observe_solar_eclipse(timings, filename, cameras, None, None, None)

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
