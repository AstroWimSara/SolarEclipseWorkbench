"""Where the ephemerides and kernels are looked for.

They used to be loaded from the current directory, so sew started from another
directory while offline had no contact times at all.
"""

import pytest

from solareclipseworkbench import data_files


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    user = tmp_path / "user"
    monkeypatch.setattr(data_files, "USER_DATA_DIRECTORY", user)
    monkeypatch.setattr(data_files, "CHECKOUT_DIRECTORY", tmp_path / "checkout")
    monkeypatch.setattr(data_files, "PACKAGE_DIRECTORY", tmp_path / "package")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    return user, cwd


def test_a_missing_file_resolves_to_the_user_data_directory(dirs):
    user, _ = dirs
    assert data_files.find_data_file("de421.bsp") is None
    assert data_files.data_path("de421.bsp") == user / "de421.bsp"


def test_the_user_data_directory_wins_over_the_current_directory(dirs):
    user, cwd = dirs
    user.mkdir()
    (user / "de421.bsp").write_bytes(b"user")
    (cwd / "de421.bsp").write_bytes(b"cwd")
    assert data_files.find_data_file("de421.bsp") == user / "de421.bsp"


def test_a_file_only_in_the_current_directory_is_copied_to_the_user_data_directory(dirs):
    user, cwd = dirs
    (cwd / "de421.bsp").write_bytes(b"legacy")

    found = data_files.find_data_file("de421.bsp")

    assert found == user / "de421.bsp"
    assert found.read_bytes() == b"legacy"
    assert not (user / "de421.bsp.part").exists()


def test_downloads_go_to_the_user_data_directory(dirs):
    user, _ = dirs
    assert data_files.loader().path_to("de440s.bsp") == str(user / "de440s.bsp")


def test_the_real_ephemeris_loads_from_anywhere(tmp_path, monkeypatch):
    if data_files.find_data_file("de421.bsp") is None:
        pytest.skip("de421.bsp not installed")
    monkeypatch.chdir(tmp_path)
    eph = data_files.load_ephemeris("de421.bsp")
    assert "earth" in str(eph).lower()


def test_a_file_in_the_checkout_is_copied_to_the_user_data_directory(dirs, tmp_path):
    user, _ = dirs
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "de440s.bsp").write_bytes(b"checkout")

    found = data_files.find_data_file("de440s.bsp")

    assert found == user / "de440s.bsp"
    assert found.read_bytes() == b"checkout"


def test_a_failed_copy_still_uses_the_file_where_it_is(dirs, monkeypatch):
    _, cwd = dirs
    (cwd / "de421.bsp").write_bytes(b"legacy")

    def refuse(*args, **kwargs):
        raise OSError("read-only")
    monkeypatch.setattr(data_files.shutil, "copyfile", refuse)

    assert data_files.find_data_file("de421.bsp") == cwd / "de421.bsp"
