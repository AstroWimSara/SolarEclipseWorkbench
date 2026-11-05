"""Where the Fujifilm SDK is found, on each platform.

Every test fakes the platform, so the whole file runs anywhere.  The tests that
need the real SDK libraries are skipped when they are not installed.
"""

from unittest.mock import patch

import pytest

import fujixsdk._library as sdk_lib
import solareclipseworkbench.fuji_camera as fuji


@pytest.mark.parametrize("system,expected", [
    ("Linux", "XAPI.so"),
    ("Darwin", "XAPI.bundle"),
    ("Windows", "XAPI.dll"),
])
def test_sdk_marker_matches_the_platform(system, expected):
    # Searching for the Linux name on a Mac finds nothing, which disables the
    # whole Fuji support without an error.
    with patch.object(fuji.platform, "system", return_value=system):
        assert fuji._sdk_marker() == expected


def test_the_environment_variable_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("FUJI_SDK_PATH", str(tmp_path))
    assert fuji.find_fuji_sdk_path() == str(tmp_path)


def test_an_sdk_folder_is_found_by_its_library(tmp_path, monkeypatch):
    library = tmp_path / "fujixsdk" / "SDK13410" / "REDISTRIBUTABLES" / "Linux" / "Linux64PC"
    library.mkdir(parents=True)
    (library / "XAPI.so").touch()
    monkeypatch.delenv("FUJI_SDK_PATH", raising=False)
    monkeypatch.setattr(fuji.Path, "home", lambda: tmp_path)

    with patch.object(fuji.platform, "system", return_value="Linux"):
        assert fuji.find_fuji_sdk_path() == str(tmp_path / "fujixsdk" / "SDK13410")


def test_no_sdk_is_none(tmp_path, monkeypatch):
    monkeypatch.delenv("FUJI_SDK_PATH", raising=False)
    monkeypatch.setattr(fuji.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(fuji, "__file__", str(tmp_path / "src" / "solareclipseworkbench" / "fuji_camera.py"))

    with patch.object(fuji.platform, "system", return_value="Linux"):
        assert fuji.find_fuji_sdk_path() is None


def _sdk_root():
    root = fuji.find_fuji_sdk_path()
    if not root:
        pytest.skip("Fujifilm SDK not installed")
    return root


def test_macos_loader_finds_the_bundle_below_the_sdk_root():
    # Callers pass the SDK root; the redistributables sit several levels down.
    root = _sdk_root()

    with patch.object(sdk_lib.platform, "system", return_value="Darwin"):
        binary = sdk_lib.find_library(root)

    assert binary.exists()
    assert binary.name == "XAPI"
    assert "XAPI.bundle" in str(binary)


def test_macos_loader_finds_the_model_libraries():
    root = _sdk_root()

    with patch.object(sdk_lib.platform, "system", return_value="Darwin"):
        libraries = sdk_lib.find_model_libraries(root)

    # A shallow glob from the SDK root finds none of these.
    assert len(libraries) > 10
    assert all(path.exists() for path in libraries)


def test_macos_needs_no_library_path_change():
    # The bundles load through @rpath, and SIP strips DYLD_* across exec, so
    # macOS never restarts the process for the library path.
    with patch.object(sdk_lib.platform, "system", return_value="Darwin"):
        assert sdk_lib.ensure_ld_library_path("/anything") is True
