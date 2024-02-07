import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from solareclipseworkbench import voice_prompt, take_picture
from solareclipseworkbench.camera import CameraSettings
from solareclipseworkbench.reference_moments import ReferenceMomentInfo

COMMANDS = {
    'voice_prompt': voice_prompt,
    'take_picture': take_picture
}


def observe_solar_eclipse(ref_moments: ReferenceMomentInfo, commands_filename: str, simulated_c1: datetime) -> BackgroundScheduler:
    """ Observe (and photograph) the solar eclipse, as per given files.

    Args:
        - ref_moments: ReferenceMomentInfo that specifies the timing of the reference moments (C1,..., C4, and
                                maximum eclipse)
        - commands_filename: Name of the configuration file that specifies which commands have to be executed at which
                             moment during the solar eclipse
        - simulated_c1: Simulated date and time for C1.  Can be used to simulate the solar eclipse.  
                        None if no simulation should be used.

    Returns: Scheduler that is used to schedule the commands.
    """

    scheduler = start_scheduler()

    # Schedule commands

    schedule_commands(commands_filename, scheduler, ref_moments, simulated_c1)

    return scheduler


def start_scheduler():
    """ Start background scheduler and return it.

    Returns: Background scheduler that has been started.
    """

    scheduler = BackgroundScheduler()
    scheduler.start()

    return scheduler


def schedule_commands(filename: str, scheduler: BackgroundScheduler, reference_moments: ReferenceMomentInfo, simulated_c1: datetime):
    """ Schedule commands as specified in the given file.

    Args:
        - filename: Name of the file in which the commands have been listed, scheduled relatively to the given
                    reference moments
        - scheduler: Background scheduler to use to schedule the commands
        - reference_moments: Dictionary with the reference moments (1st - 4th contact and maximum eclipse), with
                             respect to which the commands are scheduled
        - simulated_c1: datetime with the time to simulate C1. None if no simulation is to be used.

    Returns: Scheduler that is used to schedule the commands.
    """

    with open(filename, "r") as file:
        for cmd_str in file:
            schedule_command(scheduler, reference_moments, cmd_str, simulated_c1)


def schedule_command(scheduler: BackgroundScheduler, reference_moments, cmd_str: str, simulated_c1: datetime):
    """ Schedule the given command with the given scheduler and reference moments.

    Args:
        - scheduler: Background scheduler to use to schedule the command
        - reference_moments: Dictionary with the reference moments of the solar eclipse, as ReferenceMomentInfo objects.
        - cmd_str: Command string
        - simulated_c1: datetime with the time to simulate C1. None if no simulation is to be used.
    """

    cmd_str_split = cmd_str.split(",")
    func_name = cmd_str_split[0].lstrip()
    ref_moment = cmd_str_split[1].lstrip()
    sign = cmd_str_split[2].lstrip()    # + or -
    hours, minutes, seconds = cmd_str_split[3].lstrip().split(":")   # hh:mm:ss.ss
    description = cmd_str_split[-1].lstrip()

    logging.info(f"Scheduling {func_name} at {ref_moment}{sign}{cmd_str_split[3].lstrip()}")

    args = cmd_str_split[4:-1]

    if func_name == "take_picture":
        settings = CameraSettings(args[1].strip(), args[2].strip(), args[3].strip())
        new_args = [args[0].strip(), settings]
        args = new_args

    func = COMMANDS[func_name]

    reference_moment = reference_moments[ref_moment].time_utc
    delta = timedelta(hours=float(hours), minutes=float(minutes), seconds=float(seconds))

    if sign == "+":
        execution_time = reference_moment + delta
    else:
        execution_time = reference_moment - delta

    if (simulated_c1):
        diff = reference_moments['C1'].time_utc - simulated_c1
        execution_time = execution_time - diff

    trigger = CronTrigger(year=execution_time.year, month=execution_time.month, day=execution_time.day,
                          hour=execution_time.hour, minute=execution_time.minute,
                          second=execution_time.second, timezone=pytz.utc)

    scheduler.add_job(func, trigger=trigger, args=args, name=description)
