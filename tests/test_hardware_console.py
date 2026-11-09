"""The relay bench console drives a simulated board end to end."""
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


def test_the_command_history_is_kept_between_sessions(tmp_path):
    import pytest
    from solareclipseworkbench import hardware_console

    readline = hardware_console.readline
    if readline is None:
        pytest.skip("readline is not available on this platform")
    history = tmp_path / "history"
    readline.clear_history()
    readline.add_history("relay connect")
    readline.add_history("mount track")
    hardware_console._save_history(history)

    readline.clear_history()
    hardware_console._load_history(history)
    assert [readline.get_history_item(i) for i in (1, 2)] == ["relay connect", "mount track"]
    readline.clear_history()
