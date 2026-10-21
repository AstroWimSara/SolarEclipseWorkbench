import logging
import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
import pytz
from solareclipseworkbench import voice_prompt, take_picture, take_burst, take_bracket, take_hdr, prepare_camera, sync_cameras, scripts, execute_command
from solareclipseworkbench import hardware_problems
from solareclipseworkbench.camera import CameraSettings, _MAX_LOCK_WAIT_S, parse_prepare_mode
from solareclipseworkbench.command_timing import (
    vendor_from_name, picture_duration_s, burst_duration_s, hdr_duration_s, bracket_duration_s,
    drive_mode, mode_switch_s, TimingProfile, DEFAULT_PROFILE, parse_timing_directives,
)
from solareclipseworkbench.notifications import check_notification
from solareclipseworkbench.bracketing import parse_bracket, parse_hdr_sequence
from solareclipseworkbench.gui import SolarEclipseController
from solareclipseworkbench.solar_eclipse import get_solar_eclipses

COMMANDS = {
    'voice_prompt': voice_prompt,
    'take_picture': take_picture,
    'take_burst': take_burst,
    'take_bracket': take_bracket,
    'take_hdr': take_hdr,
    'prepare_camera': prepare_camera,
    'sync_cameras': sync_cameras,
    'command': execute_command
}


@dataclass(frozen=True)
class CameraBusyWindow:
    """When a scheduled camera command starts and how long it keeps the camera busy."""

    camera: str
    start: datetime
    duration_s: float
    description: str
    # Drive mode of the command (see command_timing.drive_mode), and the extra time
    # it takes when the command before it on this camera used another mode.
    mode: Optional[str] = None
    switch_s: float = 0.0


@dataclass(frozen=True)
class CameraConflict:
    """A command that has to wait for the camera because an earlier one is still running."""

    window: CameraBusyWindow
    blocked_by: CameraBusyWindow
    wait_s: float
    dropped: bool
    # How long blocked_by keeps the camera busy, including a change of drive mode
    blocker_busy_s: Optional[float] = None


def estimate_busy_s(func_name: str, script_args: list, camera=None,
                    profile: TimingProfile = DEFAULT_PROFILE) -> Optional[float]:
    """Estimated time the camera is busy with a command, from its script arguments.

    Args:
        - func_name: Script command name (take_picture, take_burst, ...)
        - script_args: Script fields after the time offset, without the description:
                       camera name, shutter speed, aperture, ISO and, where applicable, the extra parameter
        - camera: Camera object, used for its vendor (falls back to the name in the script)
        - profile: Overheads to use (defaults, or measured on the camera)

    Returns: Estimated duration in seconds, or None for commands that are not estimated.
    """
    try:
        shutter = script_args[1].strip()
        if func_name == "take_picture":
            return picture_duration_s(shutter, profile)
        if func_name == "take_burst":
            vendor = getattr(camera, "vendor", None) or vendor_from_name(script_args[0])
            return burst_duration_s(vendor, float(script_args[4]), profile)
        if func_name == "take_hdr":
            return hdr_duration_s(shutter, int(script_args[4]), parse_hdr_sequence(
                script_args[5] if len(script_args) > 5 else None))
        if func_name == "take_bracket":
            vendor = getattr(camera, "vendor", None) or vendor_from_name(script_args[0])
            return bracket_duration_s(shutter, profile, script_args[4], vendor)
        if func_name == "prepare_camera":
            # Configuration round-trips only; changing drive mode is added by find_camera_conflicts
            return profile.picture_overhead_s
    except (IndexError, ValueError):
        pass
    return None


def camera_busy_window(start: datetime, func_name: str, script_args: list, description: str, camera=None,
                       profile: TimingProfile = DEFAULT_PROFILE) -> Optional[CameraBusyWindow]:
    """The time a script command keeps its camera busy, or None for commands that are not estimated.

    Args:
        - start: Execution time of the command
        - func_name, script_args, camera, profile: As for estimate_busy_s
        - description: Description of the command, for the warnings
    """
    busy_s = estimate_busy_s(func_name, script_args, camera, profile)
    if busy_s is None:
        return None
    camera_name = script_args[0].strip()
    vendor = getattr(camera, "vendor", None) or vendor_from_name(camera_name)
    bracket = script_args[4] if func_name in ("take_bracket", "prepare_camera") else None
    return CameraBusyWindow(camera_name, start, busy_s, description,
                            drive_mode(func_name, bracket), mode_switch_s(vendor))


def find_camera_conflicts(windows: List[CameraBusyWindow],
                          max_wait_s: float = _MAX_LOCK_WAIT_S) -> List[CameraConflict]:
    """Replay each camera's commands the way the camera USB lock serialises them.

    A command that would have to wait for the camera longer than max_wait_s is
    dropped when it fires (see camera._serialised_on_camera) and does not keep
    the camera busy; one that waits less starts late and pushes the rest back.
    A command in another drive mode than the one before it takes its switch_s
    longer.

    Returns: The commands that will start late or be dropped, in time order.
    """
    conflicts = []
    by_camera = {}
    for window in windows:
        by_camera.setdefault(window.camera, []).append(window)

    for camera_windows in by_camera.values():
        busy_until = None
        busy_with = None
        busy_with_s = None
        mode = None
        for window in sorted(camera_windows, key=lambda w: w.start):
            wait_s = (busy_until - window.start).total_seconds() if busy_until is not None else 0.0
            if wait_s > max_wait_s:
                conflicts.append(CameraConflict(window, busy_with, wait_s, dropped=True,
                                                blocker_busy_s=busy_with_s))
                continue
            if wait_s > 0:
                conflicts.append(CameraConflict(window, busy_with, wait_s, dropped=False,
                                                blocker_busy_s=busy_with_s))
            duration_s = window.duration_s
            if window.mode is not None:
                if mode is not None and window.mode != mode:
                    duration_s += window.switch_s
                mode = window.mode
            actual_start = max(window.start, busy_until) if busy_until is not None else window.start
            busy_until = actual_start + timedelta(seconds=duration_s)
            busy_with = window
            busy_with_s = duration_s

    return sorted(conflicts, key=lambda c: c.window.start)


def _hms(moment: datetime) -> str:
    """Time of day with tenths of a second, e.g. 18:29:29.3."""
    return moment.strftime("%H:%M:%S.%f")[:-5]


def report_camera_conflicts(windows: List[CameraBusyWindow]) -> List[CameraConflict]:
    """Warn about script commands that will be dropped because their camera is still busy.

    Called when a script is loaded, so the problem shows up while the script can
    still be fixed rather than as missing pictures after the eclipse.
    """
    conflicts = find_camera_conflicts(windows)
    for conflict in conflicts:
        blocker = conflict.blocked_by
        busy_s = conflict.blocker_busy_s if conflict.blocker_busy_s is not None else blocker.duration_s
        detail = (f'"{blocker.description}" at {_hms(blocker.start)} UTC keeps {conflict.window.camera} '
                  f'busy for about {busy_s:.0f} s; "{conflict.window.description}" at '
                  f'{_hms(conflict.window.start)} UTC would have to wait {conflict.wait_s:.1f} s')
        if conflict.dropped:
            hardware_problems.report(
                "Script",
                f'"{conflict.window.description}" on {conflict.window.camera} will probably be skipped: '
                f'the camera is still busy with "{blocker.description}".  Commands that wait more than '
                f'{_MAX_LOCK_WAIT_S:.1f} s for the camera are dropped; schedule them further apart.',
                detail=detail,
                severity="warning",
            )
        elif conflict.wait_s > 0.05:
            logging.info("Script timing: %s (it will be taken late).", detail)
    return conflicts


def report_past_commands(past: list) -> None:
    """Warn about script commands whose time had already passed when the script was loaded.

    The scheduler skips them with only a line in the log, so a script loaded too
    late (or a simulation started too close to its reference moment) would
    silently lose its first commands.
    """
    if not past:
        return
    past = sorted(past)
    first_time, first = past[0]
    last_time, last = past[-1]
    if len(past) == 1:
        which = f'"{first}" at {_hms(first_time)} UTC'
    else:
        which = f'from "{first}" at {_hms(first_time)} UTC to "{last}" at {_hms(last_time)} UTC'
    hardware_problems.report(
        "Script",
        f"{len(past)} command(s) of the script are already past and will not run.  In a simulation, "
        f"start it earlier before the reference moment.",
        detail=which,
        severity="warning",
    )


def calculate_next_solar_eclipses(count: int) -> list:
    """ Calculate the next solar eclipses, starting from today.

    Args:
        - count: Number of solar eclipses to calculate

    Returns:
        - List of solar eclipses, starting from today, as an array in the DD/MM/YYYY format
    """
    # Get current date
    from datetime import datetime, timedelta
    current_date = datetime.now()
    current_date = current_date - timedelta(days=3)  # Start from 3 days ago to ensure we catch today's eclipse
    current_date = current_date.strftime("%Y-%m-%d")  # Format as YYYY-MM-DD

    return get_solar_eclipses(count, current_date)


def observe_solar_eclipse(ref_moments: dict, commands_filename: str, cameras: dict,
                          controller: SolarEclipseController, reference_moment: str,
                          minutes_to_reference_moment: float,
                          gps_time_offset: timedelta = timedelta(0)) -> BackgroundScheduler:
    """ Observe (and photograph) the solar eclipse, as per given files.

    Args:
        - ref_moments: ReferenceMomentInfo that specifies the timing of the reference moments (C1,..., C4, and
                                maximum eclipse)
        - commands_filename: Name of the configuration file that specifies which commands have to be executed at which
                             moment during the solar eclipse
        - cameras: Dictionary of camera names and camera objects
        - controller: Controller of the Solar Eclipse Workbench UI
        - reference_moment: Reference moment to use for the simulation.  Possible values are C1, C2, C3, C4, sunrise,
                            sunset, and MAX.  None if no simulation should be used
        - minutes_to_reference_moment: Minutes to reference moment when simulating, None if no simulation should be used
        - gps_time_offset: Offset between GPS UTC time and computer system time (GPS − computer).
                           When the GPS is ahead of the computer by D seconds the computer fires D seconds
                           late; subtracting this offset from every scheduled time compensates for the drift.
                           Defaults to timedelta(0) (use computer clock as-is).

    Returns: (scheduler, unknown), the scheduler used to schedule the commands and the reference moments
             the script asked for that do not exist, as {name: number of lines lost}.
    """

    # Record what this run is based on, so the log can be read on its own afterwards.
    logging.info("Starting observation with script %s", commands_filename)
    for name, moment in ref_moments.items():
        time_utc = getattr(moment, "time_utc", None)
        if time_utc is not None:
            logging.info("Reference moment %s: %s UTC", name, time_utc.strftime("%Y-%m-%d %H:%M:%S.%f")[:-5])
    if reference_moment:
        logging.info("Simulation: %s in %s minutes", reference_moment, minutes_to_reference_moment)
    logging.info("GPS - computer clock offset: %.3f s", gps_time_offset.total_seconds())
    logging.info("Cameras: %s", ", ".join(cameras.keys()) if cameras else "none")

    scheduler = start_scheduler()

    # Calculate simulated time
    if reference_moment:
        now = datetime.now(pytz.utc)
        simulated_start = now + timedelta(minutes=minutes_to_reference_moment)

        offset = ref_moments[reference_moment].time_utc - timedelta(minutes=minutes_to_reference_moment) - now
    else:
        simulated_start = None
        offset = timedelta(minutes=0)

    # Update the visualization offset only when running with a GUI; the headless
    # command-line path (sew.py without --gui) has no controller/view.
    if controller is not None:
        controller.view.eclipse_visualization.set_offset(offset)

    # Schedule commands
    unknown = schedule_commands(commands_filename, scheduler, ref_moments, cameras, controller, reference_moment,
                                simulated_start, gps_time_offset=gps_time_offset)

    return scheduler, unknown


def start_scheduler():
    """ Start background scheduler and return it.

    Returns: Background scheduler that has been started.
    """

    # Use the default misfire_grace_time (1 s).  Timing accuracy is enforced
    # inside _serialised_on_camera: if the USB lock is busy for more than
    # _MAX_LOCK_WAIT_S the shot is dropped rather than taken late.
    scheduler = BackgroundScheduler()
    scheduler.start()

    return scheduler


def schedule_commands(filename: str, scheduler: BackgroundScheduler, reference_moments: dict,
                      cameras: dict, controller: SolarEclipseController, reference_moment, simulated_start: datetime,
                      gps_time_offset: timedelta = timedelta(0)):
    """ Schedule commands as specified in the given file.

    Args:
        - filename: Name of the file in which the commands have been listed, scheduled relatively to the given
                    reference moments
        - scheduler: Background scheduler to use to schedule the commands
        - reference_moments: Dictionary with the reference moments (1st - 4th contact and maximum eclipse), with
                             respect to which the commands are scheduled
        - cameras: Dictionary of camera names and camera objects
        - controller: Controller of the Solar Eclipse Workbench UI
        - reference_moment: Reference moment to use for the simulation.  Possible values are C1, C2, C3, C4, sunrise,
                            sunset, LAST and MAX. None if no simulation should be used.
        - simulated_start: datetime with the time to simulate relative to the reference moment.
                            None if no simulation is to be used.
        - gps_time_offset: GPS–computer time offset (see observe_solar_eclipse).  Defaults to timedelta(0).

    Returns: Reference moments the script asked for that do not exist, as {name: number of lines lost}.
             Empty when every line found its moment.
    """
    script_file = scripts.convert_script(filename, reference_moments)
    script_file.seek(0)

    # A script fitted to a tested camera records the timing it was planned with
    try:
        with open(filename, encoding="utf-8", errors="replace") as f:
            timing_profiles = parse_timing_directives(f)
    except OSError:
        timing_profiles = {}

    unknown: dict = {}
    past: list = []

    # Loop over all lines in script file
    busy_windows = []
    for cmd_str in script_file:
        window = schedule_command(
            scheduler, reference_moments, cmd_str, cameras, controller, reference_moment, simulated_start,
            gps_time_offset=gps_time_offset, unknown_moments=unknown, timing_profiles=timing_profiles,
            past_commands=past)
        if window is not None:
            busy_windows.append(window)

    report_past_commands(past)
    report_camera_conflicts(busy_windows)
    time_shift = gps_time_offset
    if reference_moment:
        time_shift += reference_moments[reference_moment.upper()].time_utc - simulated_start
    warn_if_script_outlasts_totality(scheduler, reference_moments, time_shift)

    return unknown


# Camera commands that take the time they were scheduled for (see camera._shutter_release)
TIMED_CAMERA_COMMANDS = ('take_picture', 'take_burst', 'take_bracket', 'take_hdr', 'prepare_camera')


# Commands that need the camera in a continuous release mode (Nikon bodies may set it with a physical dial)
CONTINUOUS_MODE_COMMANDS = ('take_burst', 'take_bracket')


def get_continuous_mode_commands(scheduler: BackgroundScheduler, cameras: dict) -> dict:
    """ Find out which cameras the scheduled jobs drive with take_burst or take_bracket.

    Args:
        - scheduler: Scheduler with the jobs of the loaded script
        - cameras: Dictionary of camera names and camera objects

    Returns: Dictionary with, per camera name, the set of these commands that are scheduled for that camera.
    """
    command_names = {COMMANDS[name]: name for name in CONTINUOUS_MODE_COMMANDS}
    camera_names = {}
    for name, camera in (cameras or {}).items():
        camera_names.setdefault(id(camera), []).append(name)

    result = {}
    for job in scheduler.get_jobs():
        command_name = command_names.get(job.func)
        if command_name is None or not job.args:
            continue
        for name in camera_names.get(id(job.args[0]), []):
            result.setdefault(name, set()).add(command_name)
    return result


def _bracket_is_valid(args: list, cmd_str: str) -> bool:
    """Check the bracket of a take_bracket now, so a typo shows up when the script is loaded."""
    try:
        parse_bracket(args[4])
        return True
    except IndexError:
        problem = "take_bracket has no bracket: give the EV step and the number of frames, e.g. \"1 3\""
    except ValueError as e:
        problem = str(e)
    hardware_problems.report("Script", f"{problem}.  This bracket will not be taken.", detail=cmd_str.strip())
    return False


def _prepare_mode_is_valid(args: list, cmd_str: str) -> bool:
    """Check the drive mode of a prepare_camera now, so a typo shows up when the script is loaded."""
    try:
        parse_prepare_mode(args[4])
        return True
    except IndexError:
        problem = "prepare_camera has no drive mode: give single, burst or a bracket, e.g. \"1 3\""
    except ValueError as e:
        problem = f"prepare_camera needs single, burst or a bracket: {e}"
    hardware_problems.report("Script", f"{problem}.  The camera will not be prepared.", detail=cmd_str.strip())
    return False


def _hdr_is_valid(args: list, cmd_str: str) -> bool:
    """Check the stops and sequence of a take_hdr now, so a typo shows up when the script is loaded."""
    try:
        if int(args[4]) < 1:
            raise ValueError
    except (IndexError, ValueError):
        problem = "take_hdr needs a whole number of stops of at least 1"
    else:
        try:
            parse_hdr_sequence(args[5] if len(args) > 5 else None)
            return True
        except ValueError as e:
            problem = str(e)
    hardware_problems.report("Script", f"{problem}.  This HDR sequence will not be taken.", detail=cmd_str.strip())
    return False


#: Commands that leave the camera alone, so a job running one of them is not
#: holding the shutter when the next contact needs it.
CAMERA_FREE_COMMANDS = frozenset({'voice_prompt'})

#: Which script command each scheduled job runs, by job id.  Filled in as the
#: script is scheduled: the scheduler itself only knows times, not what a job
#: will do, and most of the jobs around second contact are voice prompts.
JOB_COMMANDS: dict = {}

#: The reference moment each scheduled job was written against, by job id.
JOB_REFERENCES: dict = {}

#: Reference moments that move with third contact.  A command written against
#: one of them (e.g. a chromosphere shot at C3-2s) follows the totality it runs
#: in, so it cannot be a sign of a script written for a longer totality.
THIRD_CONTACT_REFERENCES = frozenset({"C3", "C3_MEAN", "BEADS_C3", "BEADS_C3_START", "BEADS_C3_END"})

#: A totality command finishing this close to third contact is treated as
#: overrunning it.  A corona ladder takes about six and a half seconds, so
#: anything starting inside that window is still holding the camera when the
#: beads sequence needs it.
TOTALITY_OVERRUN_MARGIN_S = 8.0


def job_touches_camera(job) -> bool:
    """Whether this job will use the camera or fire the shutter.

    Unknown jobs count as touching it: not knowing what a job does is not a
    reason to assume the camera is free.
    """
    return JOB_COMMANDS.get(getattr(job, 'id', None), '') not in CAMERA_FREE_COMMANDS


def warn_if_script_outlasts_totality(scheduler, reference_moments: dict,
                                     time_shift: timedelta = timedelta(0)) -> float:
    """Say so when the script was written for a longer totality than this one.

    Returns the seconds of overrun, 0.0 when there are none.

    Args:
        - scheduler: Scheduler with the jobs of the loaded script
        - reference_moments: Reference moments the script was scheduled against
        - time_shift: How much earlier than the reference moments the jobs were scheduled
                      (simulation offset plus GPS-computer time offset)

    Loading the wrong duration is silent and costs the part of the eclipse that
    cannot be retaken: the last corona ladder of a script written for a longer
    totality is still running at third contact, so the command that loads the
    bead exposure waits, is dropped, and the bead burst fires at the corona
    ladder's exposure instead.  Fewer frames, none of them beads, and nothing
    says anything until the photographs are reviewed.

    The scheduler already knows every job's time and the eclipse already knows
    when third contact is; comparing them is the difference between a warning
    while there is still time to load another file and a ruined third contact.
    """
    c2 = reference_moments.get("C2")
    c3 = reference_moments.get("C3")
    if c2 is None or c3 is None:
        return 0.0

    deadline = c3.time_utc - timedelta(seconds=TOTALITY_OVERRUN_MARGIN_S)
    latest = None
    for job in scheduler.get_jobs():
        when = getattr(job, "next_run_time", None)
        if when is None or not job_touches_camera(job):
            continue
        if JOB_REFERENCES.get(getattr(job, "id", None)) in THIRD_CONTACT_REFERENCES:
            continue
        # Back on the time scale of the reference moments
        when = when + time_shift
        if c2.time_utc <= when < c3.time_utc and when > deadline:
            if latest is None or when > latest:
                latest = when
    if latest is None:
        return 0.0

    overrun = (latest - deadline).total_seconds()
    totality = (c3.time_utc - c2.time_utc).total_seconds()
    logging.error(
        "This script was written for a longer totality than this one: a camera "
        "command runs %.1f s into the %.0f s reserved before third contact, and "
        "totality here is %.0f s.  Load the script for %.0f s - the one running "
        "will hold the camera when the third contact beads need it",
        overrun, TOTALITY_OVERRUN_MARGIN_S, totality, totality)
    hardware_problems.report(
        "Script",
        "Written for a longer totality: %.0f s here" % totality,
        detail="a camera command runs %.1f s into the third contact reserve" % overrun,
    )
    return overrun


def schedule_command(scheduler: BackgroundScheduler, reference_moments: dict, cmd_str: str, cameras: dict,
                     controller: SolarEclipseController, reference_moment_for_simulation: str,
                     simulated_start: datetime,
                     gps_time_offset: timedelta = timedelta(0),
                     unknown_moments: Optional[dict] = None,
                     timing_profiles: Optional[dict] = None,
                     past_commands: Optional[list] = None) -> Optional[CameraBusyWindow]:
    """ Schedule the given command with the given scheduler and reference moments.

    Args:
        - scheduler: Background scheduler to use to schedule the command
        - reference_moments: Dictionary with the reference moments of the solar eclipse, as ReferenceMomentInfo objects.
        - cmd_str: Command string
        - cameras: Dictionary of camera names and camera objects
        - controller: Controller of the Solar Eclipse Workbench UI
        - reference_moment_for_simulation: Reference moment to use for the simulation.  Possible values are C1, C2, C3,
                            C4, sunrise, sunset, LAST and MAX. None if no simulation should be used.
        - simulated_start: datetime with the time to simulate relative to the reference moment.
                            None if no simulation is to be used.
        - gps_time_offset: GPS–computer time offset (GPS UTC − computer UTC).  When positive the computer
                            is slow; execution times are shifted earlier by this amount so that actions
                            fire at the correct GPS-referenced wall-clock time.  Defaults to timedelta(0).
        - unknown_moments: When given, a line asking for a reference moment that does not exist is counted
                           here, as {name: number of lines lost}, so the caller can report it.
        - timing_profiles: Timing per camera name the script was planned with (see
                           command_timing.parse_timing_directives); other cameras use the defaults.
        - past_commands: When given, a command whose time has already passed (it will not run) is
                         added here as (execution time, description), so the caller can report it.

    Returns: For a camera command, when it starts and how long it is expected to keep the camera
             busy; None otherwise (or when the command was not scheduled).
    """
    # Use CSV reader to properly handle quoted fields with commas
    try:
        cmd_str_split = next(csv.reader([cmd_str], skipinitialspace=True))
    except StopIteration:
        logging.error(f"Could not parse command: {cmd_str}")
        return
    
    func_name = cmd_str_split[0].strip()
    ref_moment = cmd_str_split[1].strip()

    if ref_moment.upper() == "SUNRISE":
        ref_moment = "sunrise"

    if ref_moment.upper() == "SUNSET":
        ref_moment = "sunset"

    sign = cmd_str_split[2].strip()    # + or -
    hours, minutes, seconds = cmd_str_split[3].strip().split(":")   # hh:mm:ss.ss
    description = cmd_str_split[-1].strip()

    logging.info(f"Scheduling {func_name} at {ref_moment}{sign}{cmd_str_split[3].strip()}")

    args = cmd_str_split[4:-1]
    script_args = list(args)
    camera_obj = None

    if func_name == "voice_prompt":
        # Resolve the prompt now rather than when the job fires: a typo would
        # otherwise raise mid-eclipse and the prompt would simply not be heard.
        problem = check_notification(args[0] if args else "")
        if problem is not None:
            hardware_problems.report(
                "Script", f"{problem}.  This prompt will not be played.",
                detail=cmd_str.strip(),
            )
            return
    elif func_name != "command":
        if func_name == "take_bracket" and not _bracket_is_valid(args, cmd_str):
            return
        if func_name == "take_hdr" and not _hdr_is_valid(args, cmd_str):
            return
        if func_name == "prepare_camera" and not _prepare_mode_is_valid(args, cmd_str):
            return
        if cameras is not None:
            try:
                if func_name != "sync_cameras":
                    camera_obj = cameras[args[0].strip()]
                if func_name == "take_picture":
                    settings = CameraSettings(args[0].strip(), args[1].strip(), args[2].strip(), int(args[3].strip()))
                    new_args = [cameras[args[0].strip()], settings]
                    args = new_args
                elif func_name == "take_burst":
                    settings = CameraSettings(args[0].strip(), args[1].strip(), args[2].strip(), int(args[3].strip()))
                    new_args = [cameras[args[0].strip()], settings, float(args[4].strip())]
                    args = new_args
                elif func_name == "take_bracket":
                    settings = CameraSettings(args[0].strip(), args[1].strip(), args[2].strip(), int(args[3].strip()))
                    new_args = [cameras[args[0].strip()], settings, str(args[4].strip())]
                    args = new_args
                elif func_name == "prepare_camera":
                    settings = CameraSettings(args[0].strip(), args[1].strip(), args[2].strip(), int(args[3].strip()))
                    args = [cameras[args[0].strip()], settings, parse_prepare_mode(args[4])]
                elif func_name == "take_hdr":
                    settings = CameraSettings(args[0].strip(), args[1].strip(), args[2].strip(), int(args[3].strip()))
                    new_args = [cameras[args[0].strip()], settings, int(args[4].strip()),
                                parse_hdr_sequence(args[5] if len(args) > 5 else None)]
                    args = new_args
                elif func_name == "sync_cameras":
                    args = [controller]
            except KeyError:
                camera_name_in_script = args[0].strip() if args else '(unknown)'
                available = list(cameras.keys()) if cameras else []
                logging.warning(
                    'schedule_command: camera "%s" not found in camera dict.  '
                    'Available cameras: %s.  '
                    'Check that the camera name in the script exactly matches the '
                    'name shown in the Camera(s) overview (or the alias you configured '
                    'in the wizard).  This command will be skipped.',
                    camera_name_in_script, available,
                )
                return
        else:
            # No camera dict at all: the script was loaded before any camera was
            # detected.  Every camera command in the file is dropped here, so say
            # so per command rather than leaving a script that looks loaded but
            # only ever plays its voice prompts.
            logging.warning(
                'schedule_command: no cameras have been detected, so "%s" will be '
                'skipped.  Detect the camera(s) first, then load the script: the '
                'commands are bound to a camera when they are scheduled, not when '
                'they run.',
                func_name,
            )
            return

    func = COMMANDS[func_name]


    try:
        if ref_moment == "LAST":
            try:
                # Get last job from scheduler
                last_job = scheduler.get_jobs()[-1]

                # Get the last job's time
                reference_moment = last_job.next_run_time.astimezone(pytz.utc)
            except AttributeError:
                logging.error("No jobs found in the scheduler. Cannot determine LAST reference moment.")
                return
        else:
            reference_moment = reference_moments[ref_moment].time_utc


        delta = timedelta(hours=float(hours), minutes=float(minutes), seconds=float(seconds))

        if sign == "+":
            execution_time = reference_moment + delta
        else:
            execution_time = reference_moment - delta

        if reference_moment_for_simulation:
            diff = reference_moments[reference_moment_for_simulation.upper()].time_utc - simulated_start
            execution_time = execution_time - diff

        # Compensate for the GPS–computer time offset.
        # If GPS time is ahead of the computer (offset > 0), the computer is slow
        # and would fire the shutter late.  Scheduling earlier on the computer clock
        # by subtracting the offset ensures the action happens at the correct moment.
        execution_time = execution_time - gps_time_offset

        now = datetime.now(timezone.utc)
        if execution_time.tzinfo is None:
            now = now.replace(tzinfo=None)
        if past_commands is not None and execution_time < now:
            past_commands.append((execution_time, description))

        trigger = DateTrigger(run_date=execution_time, timezone=pytz.utc)

        # Camera commands log how long after this time they released the shutter
        kwargs = {'scheduled_at': execution_time} if func_name in TIMED_CAMERA_COMMANDS else None
        job = scheduler.add_job(func, trigger=trigger, args=args, kwargs=kwargs, name=description)
        JOB_COMMANDS[job.id] = func_name
        JOB_REFERENCES[job.id] = ref_moment
    except KeyError as missing:
        # A line naming a moment the calculation did not produce.  Usually a
        # limb-corrected moment — BEADS_C2 and friends only exist when the
        # correction is on and the limb profile is installed — or a typo.  The
        # line cannot be scheduled, but it must not disappear without a word:
        # silently dropping the contact bursts is exactly the failure nobody
        # notices until the eclipse is over.  The name is counted for the caller,
        # which is holding the user at the moment the script is loaded.
        name = missing.args[0] if missing.args else str(missing)
        logging.warning(
            'schedule_command: no reference moment %s, so "%s" (%s) is not scheduled — '
            'the rest of the script is unaffected', name, func_name, description)
        if unknown_moments is not None:
            unknown_moments[name] = unknown_moments.get(name, 0) + 1
        return None

    if camera_obj is None:
        return None
    profile = (timing_profiles or {}).get(script_args[0].strip(), DEFAULT_PROFILE)
    return camera_busy_window(execution_time, func_name, script_args, description, camera_obj, profile)

# Main
def main():
    """ Main function to test the utility functions. """
    # Example usage of calculate_next_solar_eclipses
    eclipses = calculate_next_solar_eclipses(5)
    print("Next Solar Eclipses:", eclipses)

    # Example usage of observe_solar_eclipse
    # This would require actual reference moments and cameras to work properly
    # observe_solar_eclipse({}, "commands.txt", {}, SolarEclipseController(), "C1", 10)

if __name__ == "__main__":
    main()
