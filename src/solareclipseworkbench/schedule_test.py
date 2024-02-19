from time import sleep

from astropy.time import Time
from datetime import datetime, timedelta
from solareclipseworkbench.reference_moments import calculate_reference_moments
from solareclipseworkbench.utils import observe_solar_eclipse
import pytz
import camera


def main():
    eclipse_date = Time('2024-04-08')

    timings, magnitude, eclipse_type = calculate_reference_moments(-104.63525, 24.01491, 1877.3, eclipse_date)

    # filename = "/Users/wim/GitHub/SolarEclipseWorkbench/config/scripts/voice_prompts.txt"
    filename = "/Users/wim/GitHub/SolarEclipseWorkbench/config/scripts/testEOS80D.txt"

    cameras = camera.get_camera_dict()

    # C1 in 2 minutes
    simulated_start = datetime.now(pytz.utc) + timedelta(minutes=2)

    scheduler = observe_solar_eclipse(timings, filename, cameras, simulated_start)

    while len(scheduler.get_jobs()) > 0:
        sleep(5)


if __name__ == "__main__":
    main()
