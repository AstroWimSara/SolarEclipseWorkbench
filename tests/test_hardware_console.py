"""The bench console drives a simulated relay board and a simulated mount end to end."""
from solareclipseworkbench.hardware_console import Console, main


def test_a_simulated_relay_can_be_connected_fired_and_released(capsys):
    console = Console(simulate=True)

    for line in ("relay connect", "relay wiring 2 1", "relay shoot", "relay burst 0.05",
                 "relay events 4", "status"):
        assert console.dispatch(line) is True
    assert console.trigger.closed_channels == set()

    assert console.dispatch("quit") is False
    console.shutdown()
    out = capsys.readouterr().out
    assert "Connected: simulated relay" in out
    assert "Fired one frame." in out
    assert "dual channel, S1 on 1, S2 on 2" in out
    assert "Relay contacts released." in out


def test_a_bad_command_does_not_end_the_console(capsys):
    console = Console(simulate=True)

    assert console.dispatch("relay pulse") is True
    assert console.dispatch("nonsense") is True
    assert console.dispatch("relay connect") is True
    assert console.dispatch("relay pulse x") is True

    console.shutdown()
    out = capsys.readouterr().out
    assert "Unknown command: nonsense" in out
    assert "Bad arguments" in out


def test_one_command_from_the_command_line(capsys):
    assert main(["--simulate", "relay", "backends"]) == 0

    assert "simulated" in capsys.readouterr().out


def test_a_simulated_mount_can_be_connected_moved_and_parked(capsys):
    console = Console(simulate=True)

    for line in ("mount drivers", "mount connect", "mount goto 6 23.5", "mount track solar",
                 "mount tracking on", "mount status", "mount pos", "status", "mount park"):
        assert console.dispatch(line) is True

    console.shutdown()
    out = capsys.readouterr().out
    assert "onstepx" in out and "simulator" in out
    assert "Connected: simulated mount" in out
    assert "tracking: True (solar)" in out
    assert "RA  06:00:00" in out
    assert "Alt/Az not available" in out
    assert "Parked." in out


def test_a_mount_command_without_a_mount_says_so(capsys):
    console = Console(simulate=True)

    assert console.dispatch("mount status") is True
    assert console.dispatch("mount nonsense") is True

    out = capsys.readouterr().out
    assert "No mount connected" in out
    assert "Unknown mount subcommand: nonsense" in out


def test_a_mount_error_does_not_end_the_console(capsys):
    console = Console(simulate=True)

    assert console.dispatch("mount connect - no-such-driver") is True

    assert "unknown mount driver 'no-such-driver'" in capsys.readouterr().out
