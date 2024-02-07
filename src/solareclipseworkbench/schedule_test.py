from astropy.time import Time
from datetime import datetime, timedelta
from solareclipseworkbench.reference_moments import calculate_reference_moments
from solareclipseworkbench.utils import observe_solar_eclipse
import pytz


def main():
    eclipse_date = Time('2024-04-08')
    # eclipse_date = Time('2024-10-02')
    timings, magnitude, eclipse_type = calculate_reference_moments(-104.63525, 24.01491, 1877.3, eclipse_date)
    # timings, magnitude, eclipse_type = calculate_reference_moments(-75.18647, -47.29000, 1877.3, eclipse_date)

    # filename = "/Users/wim/GitHub/SolarEclipseWorkbench/config/scripts/voice_prompts.txt"
    filename = "/Users/wim/GitHub/SolarEclipseWorkbench/config/scripts/test.txt"
    # C1 in 2 minutes
    simulated_start = datetime.now(pytz.utc) + timedelta(minutes=2) 

    scheduler = observe_solar_eclipse(timings, filename, simulated_start)

    print(scheduler.get_jobs())


if __name__ == "__main__":
    main()
