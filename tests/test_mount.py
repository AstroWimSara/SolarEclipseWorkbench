"""The mount driver registry, the simulator and the OnStepX driver (mounts)."""
from datetime import datetime, timezone

import pytest

from solareclipseworkbench.mounts import (
    Capabilities,
    MountDriver,
    MountError,
    MountNotSupported,
    connect,
    discover_drivers,
    format_dec,
    format_ra,
    get_driver,
    list_drivers,
    parse_dec,
    parse_ra,
    push_site_and_time,
    register_driver,
)
from solareclipseworkbench.mounts import onstepx
from solareclipseworkbench.mounts.onstepx import (
    LoopbackTransport,
    OnStepXMount,
    parse_status,
)
from solareclipseworkbench.mounts.simulator import SimulatorMount


# ------------------------------------------------------------------ coordinates


@pytest.mark.parametrize("hours", [0.0, 5.5, 12.3456, 18.75])
def test_right_ascension_survives_a_round_trip(hours):
    assert parse_ra(format_ra(hours)) == pytest.approx(hours, abs=1 / 3600.0)


@pytest.mark.parametrize("degrees", [0.0, 45.0, -23.4567, 66.5])
def test_declination_survives_a_round_trip(degrees):
    assert parse_dec(format_dec(degrees)) == pytest.approx(degrees, abs=1 / 3600.0)


def test_right_ascension_wraps_at_24_hours():
    # 23.99999 h rounds up past 24 h, which is 0 h, not 24.
    assert format_ra(23.99999).startswith("00:")


def test_declination_keeps_the_sign_for_small_negatives():
    assert format_dec(-0.5).startswith("-00*30")


def test_parses_the_low_precision_reply_shape():
    # Controllers not in high-precision mode answer HH:MM.T instead.
    assert parse_ra("05:30.5") == pytest.approx(5.5083, abs=1e-3)


def test_rejects_unparseable_coordinates():
    with pytest.raises(MountError):
        parse_ra("not a coordinate")


# ---------------------------------------------------------------- the registry


def test_builtin_drivers_are_discovered():
    drivers = discover_drivers()

    assert "onstepx" in drivers
    assert "simulator" in drivers


def test_get_driver_reports_what_is_available_when_the_name_is_wrong():
    with pytest.raises(MountError, match="onstepx"):
        get_driver("no-such-mount")


def test_every_driver_declares_a_name_and_capabilities():
    for driver in list_drivers():
        assert driver.name
        assert driver.display_name
        assert isinstance(driver.capabilities, Capabilities)


def test_a_third_party_driver_can_register_itself():
    class Fake(MountDriver):
        name = "test-only-fake"
        display_name = "Fake"
        capabilities = Capabilities(park=False, tracking_rates=("sidereal",))

        def connect(self): pass
        def close(self): pass
        def describe(self): return "fake"
        def status(self): return None
        def get_radec(self): return (0.0, 0.0)
        def goto(self, ra_hours, dec_degrees, wait=False, timeout=180.0): pass
        def abort(self): pass
        def tracking_on(self): return True
        def tracking_off(self): return True

    try:
        register_driver(Fake)
        assert get_driver("test-only-fake") is Fake
    finally:
        discover_drivers()  # leave the registry populated for other tests


def test_registering_a_non_driver_is_refused():
    class NotADriver:
        name = "nope"

    with pytest.raises(TypeError):
        register_driver(NotADriver)


def test_unsupported_features_raise_rather_than_silently_doing_nothing():
    with connect(driver="simulator") as mount:
        # The simulator declares no alt/az readout, so asking must fail loudly.
        assert mount.capabilities.altaz_readout is False
        with pytest.raises(MountNotSupported):
            mount.get_altaz()


# ------------------------------------------------------------- simulator driver


def test_simulator_reports_identity_and_connects():
    with connect(driver="simulator") as mount:
        assert "simulated" in mount.describe()
        assert mount.status().connected is True


def test_simulator_goto_updates_the_reported_position():
    with connect(driver="simulator") as mount:
        mount.goto(6.0, 23.5)
        ra, dec = mount.get_radec()

    assert ra == pytest.approx(6.0)
    assert dec == pytest.approx(23.5)


def test_simulator_refuses_goto_while_parked():
    with connect(driver="simulator") as mount:
        mount.park()

        with pytest.raises(MountError, match="parked"):
            mount.goto(1.0, 2.0)


def test_simulator_solar_tracking():
    with connect(driver="simulator") as mount:
        mount.set_tracking_rate("solar")
        mount.tracking_on()
        status = mount.status()

    assert status.tracking is True
    assert status.tracking_rate == "solar"


def test_simulator_is_never_offered_by_discovery():
    # A simulated mount must not replace a real mount without a choice by the user.
    assert SimulatorMount.discover() == []


# ---------------------------------------------------------------- OnStepX driver


def _loopback() -> OnStepXMount:
    mount = OnStepXMount(transport=LoopbackTransport())
    mount.connect()
    return mount


def test_status_treats_absent_flags_as_active_states():
    # 'n' means NOT tracking and 'N' means NO goto, so their absence is the
    # positive case.
    status = parse_status("pNO#")

    assert status.tracking is True
    assert status.slewing is False
    assert status.parked is False
    assert status.tracking_rate == "solar"


def test_status_reports_parked_and_home():
    status = parse_status("nNPH")

    assert status.parked is True
    assert status.at_home is True
    assert status.tracking is False
    assert "parked" in status.summary()


def test_status_reads_the_tracking_rate():
    assert parse_status("nN(").tracking_rate == "lunar"
    assert parse_status("nNk").tracking_rate == "king"
    assert parse_status("nN").tracking_rate == "sidereal"


def test_onstepx_reports_identity():
    mount = _loopback()

    assert "OnStepX" in mount.product_name()
    assert mount.firmware_version()


def test_onstepx_goto_updates_the_reported_position():
    mount = _loopback()

    mount.goto(6.0, 23.5)
    ra, dec = mount.get_radec()

    assert ra == pytest.approx(6.0, abs=1e-3)
    assert dec == pytest.approx(23.5, abs=1e-3)


def test_onstepx_goto_raises_with_the_controllers_reason_when_parked():
    mount = _loopback()
    mount.park()

    with pytest.raises(MountError, match="parked"):
        mount.goto(1.0, 2.0)


def test_onstepx_commands_are_framed_even_when_given_bare():
    mount = _loopback()

    mount.send("GVP")

    assert mount.traffic[-1][1] == ":GVP#"


def test_onstepx_rejects_an_unknown_tracking_rate():
    mount = _loopback()

    with pytest.raises(MountError):
        mount.set_tracking_rate("warp")


def test_onstepx_requires_an_address():
    with pytest.raises(MountError, match="port"):
        OnStepXMount().connect()


def test_onstepx_tells_the_controller_where_and_when():
    # The clock is sent as UTC with a zero offset, and the longitude is sent
    # west positive, which is the LX200 convention.
    mount = _loopback()
    mount.set_datetime(datetime(2030, 3, 4, 17, 30, 45, tzinfo=timezone.utc))
    mount.set_site(latitude_deg=39.5, longitude_deg=-2.5)

    sent = mount.transport.site_time
    assert sent["SG"] == "+00:00"
    assert sent["SL"] == "17:30:45"
    assert sent["SC"] == "03/04/30"
    assert sent["St"] == "+39*30:00"
    assert sent["Sg"] == "+002*30:00", "2.5 degrees west is not west positive"


def test_the_site_and_time_go_to_a_mount_that_takes_them():
    mount = _loopback()

    push_site_and_time(mount, 39.5, -2.5)

    assert set(mount.transport.site_time) == {"SG", "SL", "SC", "St", "Sg"}


def test_only_the_time_goes_when_no_location_is_known():
    mount = _loopback()

    push_site_and_time(mount)

    assert set(mount.transport.site_time) == {"SG", "SL", "SC"}


def test_a_mount_that_takes_no_site_is_left_alone():
    with connect(driver="simulator") as mount:
        assert mount.capabilities.site_time is False
        push_site_and_time(mount, 39.5, -2.5)


def test_onstepx_refuses_a_port_where_nothing_answers(monkeypatch):
    # With no answer at any baud rate, connect() must not open the port at a
    # default rate.  A link to a device that is not a mount does not work.
    monkeypatch.setattr(onstepx, "probe_serial", lambda port: None)

    mount = OnStepXMount(port="/dev/cu.some-relay")
    with pytest.raises(MountError, match="answered"):
        mount.connect()
    assert mount.transport is None


def test_a_controller_that_will_not_name_itself_is_still_found():
    """OnStepX 10.27 answers :GVP# with a bare "0", with no name and no
    terminator, but it answers :GVN#, :GU# and the coordinates.  The probe
    must find this mount."""
    class _MuteName(LoopbackTransport):
        def _respond(self, command: str) -> str:
            if command == ":GVP#":
                return "0"
            return super()._respond(command)

    transport = _MuteName()
    opened = []

    def _fake_serial(port, baudrate, timeout=None):
        opened.append(baudrate)
        return transport

    original = onstepx.SerialTransport
    onstepx.SerialTransport = _fake_serial
    try:
        assert onstepx.probe_serial("/dev/fake", baudrates=[9600]) == 9600
    finally:
        onstepx.SerialTransport = original

    # And the driver still describes itself, standing on the firmware version.
    mount = OnStepXMount(transport=_MuteName())
    mount.connect()
    assert mount.product_name() == "OnStepX 10.24"


def test_a_port_with_nothing_on_it_is_still_refused():
    # The probe asks more than one question, but a port that answers none of
    # them is not a mount.
    class _Mute(LoopbackTransport):
        def _respond(self, command: str) -> str:
            return ""

    original = onstepx.SerialTransport
    onstepx.SerialTransport = lambda port, baudrate, timeout=None: _Mute()
    try:
        assert onstepx.probe_serial("/dev/fake", baudrates=[9600]) is None
    finally:
        onstepx.SerialTransport = original
