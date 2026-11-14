"""Two ConfigManagers on one file (sew and sew_wizard at the same time) must not undo each other's saves."""
import pytest

from solareclipseworkbench.location_ui import ConfigManager


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr(ConfigManager, "_save_failure_reported", True)
    return tmp_path


def test_saves_of_two_managers_are_merged(home):
    gui, wizard = ConfigManager(), ConfigManager()
    gui.add_location("Durango", 24.8, -104.8, 1880)
    wizard.add_camera("Canon EOS R5", 600, 5.6, 32, "ND5")
    gui.set_last_used_location("Durango")

    on_disk = ConfigManager()
    assert [loc["name"] for loc in on_disk.get_locations()] == ["Durango"]
    assert [cam["name"] for cam in on_disk.get_cameras()] == ["Canon EOS R5"]
    assert on_disk.get_last_used_location() == "Durango"
    # The manager that saved last now also has what the other one saved.
    assert gui.get_camera("Canon EOS R5") is not None


def test_delete_in_one_manager_is_not_undone_by_the_other(home):
    first = ConfigManager()
    first.add_location("A", 1, 2, 3)
    first.add_location("B", 4, 5, 6)
    second = ConfigManager()
    first.delete_location("A")
    second.add_location("C", 7, 8, 9)
    assert [loc["name"] for loc in ConfigManager().get_locations()] == ["B", "C"]


def test_same_entry_changed_by_both_keeps_last_save(home):
    first = ConfigManager()
    first.add_location("Site", 1, 2, 3)
    second = ConfigManager()
    first.add_location("Site", 10, 20, 30)
    second.add_location("Site", 11, 21, 31)
    assert ConfigManager().get_location("Site")["latitude"] == 11


def test_camera_aliases_of_both_managers_are_kept(home):
    first, second = ConfigManager(), ConfigManager()
    first.set_camera_alias("111", "Body A")
    second.set_camera_alias("222", "Body B")
    aliases = ConfigManager().get_camera_aliases()
    assert set(aliases) == {"111", "222"}
