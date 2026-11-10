"""Telescope mount control through INDI, against the built-in simulated INDI server."""
import datetime
import socket
from datetime import timedelta, timezone
from types import SimpleNamespace

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from skyfield.units import Angle

from solareclipseworkbench import hardware_problems
from solareclipseworkbench.hardware_console import Console
from solareclipseworkbench.hardware_registry import HARDWARE_COMMANDS, register_hardware
from solareclipseworkbench.indi_client import IndiClient, IndiError, XmlStream, parse_number
from solareclipseworkbench.indi_simulator import DEVICE, SimulatedIndiServer
from solareclipseworkbench.job_text import describe_job
from solareclipseworkbench.mount import (Mount, MountError, find_mounts, mount_park, mount_stop, mount_track,
                                         parse_address)
from solareclipseworkbench.reference_moments import ReferenceMomentInfo
from solareclipseworkbench.script_timeline import build_timeline
from solareclipseworkbench.utils import COMMANDS, DeviceAtRuntime, schedule_commands


@pytest.fixture(autouse=True)
def clean_state():
    hardware_problems.clear()
    register_hardware("mount", None)
    yield
    hardware_problems.clear()
    register_hardware("mount", None)


@pytest.fixture
def server():
    server = SimulatedIndiServer()
    yield server
    server.close()


@pytest.fixture
def mount(server):
    mount = Mount.open(f"127.0.0.1:{server.port}")
    yield mount
    mount.close()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# --------------------------------------------------------------- the protocol


@pytest.mark.parametrize("text, value", [
    ("1.5", 1.5), ("-3", -3.0), ("12:30:00", 12.5), ("-5 30 0", -5.5), ("12:30.5", 12.0 + 30.5 / 60),
])
def test_numbers_can_be_sexagesimal(text, value):
    assert parse_number(text) == pytest.approx(value)


def test_elements_split_across_reads_come_out_whole():
    stream = XmlStream()
    xml = b'<setNumberVector device="M" name="P" state="Ok"><oneNumber name="A">1</oneNumber></setNumberVector>'
    assert list(stream.feed(xml[:30])) == []
    elements = list(stream.feed(xml[30:] + b'<message device="M" message="hi"/>'))
    assert [e.tag for e in elements] == ["setNumberVector", "message"]
    assert elements[0][0].text == "1"


@pytest.mark.parametrize("address, expected", [
    ("", ("localhost", 7624)), ("pi.local", ("pi.local", 7624)), ("10.0.0.2:7625", ("10.0.0.2", 7625)),
])
def test_addresses(address, expected):
    assert parse_address(address) == expected


def test_a_bad_port_is_refused():
    with pytest.raises(MountError):
        parse_address("host:port")


# ---------------------------------------------------------------- connecting


def test_the_mount_is_found_and_its_driver_connected(server, mount):
    assert mount.device == DEVICE
    assert server.connected
    assert mount.connected
    assert mount.position() is not None
    assert "not tracking" in mount.describe()


def test_mounts_are_found_before_their_driver_is_connected(server):
    client = IndiClient("127.0.0.1", server.port)
    try:
        client.wait_settled()
        assert find_mounts(client) == [DEVICE]
    finally:
        client.close()


def test_no_server_is_a_mount_error():
    with pytest.raises(MountError, match="no INDI server"):
        Mount.open(f"127.0.0.1:{_free_port()}")


def test_an_unknown_device_is_a_mount_error(server):
    with pytest.raises(MountError, match="no device"):
        Mount.open(f"127.0.0.1:{server.port}", device="EQMod Mount")


def test_the_serial_port_is_set_before_connecting(server):
    mount = Mount.open(f"127.0.0.1:{server.port}", device_port="/dev/ttyACM0")
    try:
        assert server.values("DEVICE_PORT") == {"PORT": "/dev/ttyACM0"}
        names = [name for name, _ in server.received]
        assert names.index("DEVICE_PORT") < names.index("CONNECTION")
    finally:
        mount.close()


def test_a_wifi_mount_uses_the_driver_address_instead_of_searching_serial_ports(server):
    # The INDI driver of a Wi-Fi model knows the mount's address (192.168.4.1:11880 for an AZ-GTi)
    server.props["DEVICE_ADDRESS"].values = {"ADDRESS": "192.168.4.1", "PORT": "11880"}
    mount = Mount.open(f"127.0.0.1:{server.port}", network=True)
    try:
        assert server.values("CONNECTION_MODE")["CONNECTION_TCP"]
        names = [name for name, _ in server.received]
        assert "DEVICE_AUTO_SEARCH" not in names
        assert names.index("CONNECTION_MODE") < names.index("CONNECTION")
    finally:
        mount.close()


def test_a_wifi_mount_without_an_address_asks_for_one(server):
    with pytest.raises(MountError, match="host:port"):
        Mount.open(f"127.0.0.1:{server.port}", network=True)


def test_a_failed_connection_without_a_port_hints_at_wifi():
    server = SimulatedIndiServer(refuse={"CONNECTION"})
    try:
        with pytest.raises(MountError, match="Wi-Fi"):
            Mount.open(f"127.0.0.1:{server.port}", timeout=2.0)
    finally:
        server.close()


@pytest.mark.parametrize("label, network", [
    ("AZ-GTi Alt-Az WiFi", True), ("AZ-GTi Alt-Az Wired", False), ("Some mount Wi-Fi", True), ("CEM40", False),
])
def test_wifi_models_are_recognised(label, network):
    from solareclipseworkbench.indi_server import MountDriver
    assert MountDriver("SkyWatcher", label, "indi_x").network == network


def test_closing_leaves_the_mount_tracking(server, mount):
    mount.track_solar()
    mount.close()
    assert server.connected
    assert server.values("TELESCOPE_TRACK_STATE")["TRACK_ON"]
    assert "lost" in mount.describe()


def test_the_built_in_simulator_can_be_opened_by_name():
    mount = Mount.open("simulated")
    try:
        assert mount.connected
        assert "simulated" in mount.describe()
    finally:
        mount.close()


# ----------------------------------------------------------------- site and time


def test_location_and_time_are_sent(server, mount):
    utc = datetime.datetime(2026, 8, 12, 18, 0, 5, tzinfo=timezone.utc)
    sent = mount.send_site(40.4, -3.7, 650, utc)
    assert len(sent) == 2
    coord = server.values("GEOGRAPHIC_COORD")
    assert coord["LAT"] == pytest.approx(40.4)
    assert coord["LONG"] == pytest.approx(356.3)      # INDI longitudes run 0-360 east
    assert coord["ELEV"] == pytest.approx(650)
    assert server.values("TIME_UTC")["UTC"] == "2026-08-12T18:00:05"


def test_a_naive_time_is_taken_as_utc(server, mount):
    mount.send_site(0, 0, 0, datetime.datetime(2026, 8, 12, 18, 0, 5))
    assert server.values("TIME_UTC")["UTC"] == "2026-08-12T18:00:05"


# ------------------------------------------------------------------ tracking


def test_tracking_at_the_solar_rate(server, mount):
    assert mount.track_solar() == "solar"
    assert server.values("TELESCOPE_TRACK_MODE")["TRACK_SOLAR"]
    assert server.values("TELESCOPE_TRACK_STATE")["TRACK_ON"]
    assert mount.tracking and mount.track_mode == "TRACK_SOLAR"
    assert "tracking (solar)" in mount.describe()
    mount.stop_tracking()
    assert not server.values("TELESCOPE_TRACK_STATE")["TRACK_ON"]


def test_without_a_solar_rate_the_mount_tracks_sidereal():
    server = SimulatedIndiServer(solar=False)
    try:
        mount = Mount.open(f"127.0.0.1:{server.port}")
        assert mount.track_solar() == "sidereal"
        assert server.values("TELESCOPE_TRACK_MODE")["TRACK_SIDEREAL"]
        assert server.values("TELESCOPE_TRACK_STATE")["TRACK_ON"]
        mount.close()
    finally:
        server.close()


def test_a_parked_mount_is_unparked_to_track(server, mount):
    mount.park()
    assert mount.client.wait_for(lambda: mount.parked, 2.0)
    assert not mount.tracking
    mount.track_solar()
    assert not mount.parked and mount.tracking


def test_tracking_that_the_driver_drops_is_switched_on_again():
    # As the iOptron v3 driver with a HAZ31: "tracking", then off again 60 ms later, twice
    server = SimulatedIndiServer(track_drops=2)
    try:
        mount = Mount.open(f"127.0.0.1:{server.port}")
        assert mount.track_solar() == "solar"
        assert mount.tracking and server.values("TELESCOPE_TRACK_STATE")["TRACK_ON"]
        assert [values for name, values in server.received
                if name == "TELESCOPE_TRACK_STATE"] == [{"TRACK_ON": True}] * 3
        assert server.received.count(("TELESCOPE_TRACK_MODE", {"TRACK_SOLAR": True})) == 3
        mount.close()
    finally:
        server.close()


def test_tracking_that_never_holds_is_an_error_not_a_success():
    server = SimulatedIndiServer(track_drops=10)
    try:
        mount = Mount.open(f"127.0.0.1:{server.port}")
        with pytest.raises(MountError, match="does not keep tracking"):
            mount.track_solar()
        assert not mount.tracking
        assert [name for name, _ in server.received].count("TELESCOPE_TRACK_STATE") == Mount.TRACK_ATTEMPTS
        mount.close()
    finally:
        server.close()


def test_tracking_that_holds_is_switched_on_once(server, mount):
    mount.track_solar()
    assert [name for name, _ in server.received].count("TELESCOPE_TRACK_STATE") == 1


def test_a_refused_change_is_a_mount_error():
    server = SimulatedIndiServer(refuse={"TELESCOPE_TRACK_STATE"})
    try:
        mount = Mount.open(f"127.0.0.1:{server.port}")
        with pytest.raises(MountError, match="refused"):
            mount.track_solar()
        mount.close()
    finally:
        server.close()


def test_a_change_without_answer_times_out():
    server = SimulatedIndiServer(silent={"TELESCOPE_TRACK_STATE"})
    try:
        mount = Mount.open(f"127.0.0.1:{server.port}")
        with pytest.raises(IndiError, match="did not answer"):
            mount.client.change(mount.device, "TELESCOPE_TRACK_STATE", {"TRACK_ON": True}, timeout=0.3)
        mount.close()
    finally:
        server.close()


def test_guide_pulses_and_nudges(server, mount):
    mount.guide("north", 500)
    mount.guide("W", 250)
    mount.nudge_start("e")
    assert server.values("TELESCOPE_MOTION_WE")["MOTION_EAST"]
    mount.nudge_stop("e")
    assert not server.values("TELESCOPE_MOTION_WE")["MOTION_EAST"]
    received = dict(server.received)
    assert server.received.count(("TELESCOPE_TIMED_GUIDE_NS", {"TIMED_GUIDE_N": 500.0})) == 1
    assert received["TELESCOPE_TIMED_GUIDE_WE"] == {"TIMED_GUIDE_W": 250.0}
    with pytest.raises(MountError):
        mount.guide("up", 100)


# ------------------------------------------------------------ script commands


def test_every_mount_command_can_be_scheduled():
    for name, kind in HARDWARE_COMMANDS.items():
        if kind == "mount":
            assert name in COMMANDS


def test_mount_commands_drive_the_mount(server, mount):
    mount_track(mount)
    assert mount.tracking
    mount_stop(mount)
    assert not mount.tracking
    mount_park(mount)
    assert mount.client.wait_for(lambda: mount.parked, 2.0)
    assert hardware_problems.peek() == []


def test_a_mount_without_solar_rate_is_reported_as_a_warning():
    server = SimulatedIndiServer(solar=False)
    try:
        mount = Mount.open(f"127.0.0.1:{server.port}")
        mount_track(mount)
        assert mount.tracking
        [problem] = hardware_problems.peek()
        assert problem.source == "Mount" and problem.severity == "warning"
        mount.close()
    finally:
        server.close()


def test_a_failing_mount_command_is_reported_not_raised(server, mount):
    mount.close()
    mount_track(mount)
    [problem] = hardware_problems.peek()
    assert problem.source == "Mount" and "mount_track" in problem.message


def test_mount_commands_in_a_script(tmp_path, server, mount):
    script = tmp_path / "script.txt"
    script.write_text('mount_track, C2, -, 1:00:00.0, "track"\n'
                      'mount_park, C2, +, 1:30:00.0, "park"\n'
                      'mount_stop, C2, +, 1:00:00.0, extra, "bad"\n')
    c2 = datetime.datetime.now(timezone.utc) + timedelta(hours=2)
    moments = {"C2": ReferenceMomentInfo(c2, Angle(degrees=250.0), 30.0, timezone.utc)}
    scheduler = BackgroundScheduler()
    try:
        schedule_commands(str(script), scheduler, moments, {}, None, None, None)
        jobs = {job.name: job for job in scheduler.get_jobs()}
        assert set(jobs) == {"track", "park"}
        assert isinstance(jobs["track"].args[0], DeviceAtRuntime)
        assert jobs["track"].args[1:] == ()
        assert describe_job(jobs["track"], ev=0) == "Mount: track the sun"
        [problem] = hardware_problems.peek()
        assert "takes no arguments" in problem.message

        # The mount is looked up when the job fires
        register_hardware("mount", mount)
        jobs["track"].func(*jobs["track"].args)
        assert mount.tracking
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


def test_mount_commands_keep_no_camera_busy_in_the_timeline(tmp_path):
    script = tmp_path / "script.txt"
    script.write_text('mount_track, C2, -, 1:00:00.0, "track"\n')
    c2 = datetime.datetime(2026, 8, 12, 18, 28, 25, tzinfo=timezone.utc)
    timeline = build_timeline(str(script), {"C2": SimpleNamespace(time_utc=c2)})
    assert timeline.cameras == []
    assert [c.func_name for c in timeline.commands] == ["mount_track"]


# ----------------------------------------------------------------- the console


def test_the_bench_console_drives_a_simulated_mount(capsys):
    console = Console(simulate=True)
    try:
        for line in ("mount connect", "mount site 40.4 -3.7 650", "mount track", "mount guide N 200", "status"):
            assert console.dispatch(line)
        out = capsys.readouterr().out
        assert "Tracking at the solar rate." in out
        assert "tracking (solar)" in out
        console.dispatch("mount guide X 200")
        assert "Error: not a direction" in capsys.readouterr().out
    finally:
        console.shutdown()


def test_the_example_script_for_the_mount_loads():
    """example_scripts/testMount.txt, check 1.S2 of docs/MOUNT_TESTING.md."""
    from pathlib import Path

    import solareclipseworkbench

    script = Path(solareclipseworkbench.__file__).parent / "example_scripts" / "testMount.txt"
    c1 = datetime.datetime(2026, 8, 12, 17, 36, 47, tzinfo=timezone.utc)
    timeline = build_timeline(str(script), {"C1": SimpleNamespace(time_utc=c1)})
    commands = [c.func_name for c in timeline.commands]
    assert commands.count("mount_track") == 2
    assert commands.count("mount_park") == 1 and commands.count("mount_stop") == 1
    assert commands.count("take_bracket") == 3
    assert commands.count("take_picture") == 15                 # 6 single, 9 in the tight series
    assert timeline.cameras == ["VirtualCamera"]
    assert timeline.dropped == [] and timeline.late == []
    assert timeline.unknown_moments == {}


def test_position_updates_do_not_flood_the_debug_log(caplog):
    """Drivers send the position several times a second: with --debug that buried everything else."""
    import logging

    client = IndiClient.__new__(IndiClient)
    client._logged = {}
    with caplog.at_level(logging.DEBUG, logger="solareclipseworkbench.indi_client"):
        logged = [client._worth_logging("Number", "Mount", "EQUATORIAL_EOD_COORD", "Ok", "") for _ in range(20)]
        assert logged == [True] + [False] * 19
        assert client._worth_logging("Number", "Mount", "EQUATORIAL_EOD_COORD", "Busy", "")     # a slew starts
        assert client._worth_logging("Number", "Mount", "EQUATORIAL_EOD_COORD", "Busy", "slewing")  # a message
        assert client._worth_logging("Switch", "Mount", "TELESCOPE_PARK", "Ok", "")
        assert client._worth_logging("Switch", "Mount", "TELESCOPE_PARK", "Ok", "")          # switches: always
    with caplog.at_level(logging.INFO, logger="solareclipseworkbench.indi_client"):
        assert not client._worth_logging("Switch", "Mount", "TELESCOPE_PARK", "Ok", "")      # no debug: nothing
