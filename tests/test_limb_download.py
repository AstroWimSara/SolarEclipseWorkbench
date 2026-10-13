"""Downloading the lunar limb profile.

The blob is 72 MB and only exists as a release asset, so it is fetched the first
time it is needed.  A wrong or truncated file must never end up where the solver
looks for it, and an offline machine must only pay for one failed attempt.
"""

import hashlib

import pytest
import requests

from solareclipseworkbench import limb_correction

CONTENT = b"SEWLIMB" + bytes(range(256)) * 10


class FakeResponse:
    def __init__(self, content=CONTENT, status=200):
        self.content = content
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status != 200:
            raise requests.HTTPError(f"{self.status}")

    def iter_content(self, chunk_size):
        for start in range(0, len(self.content), 1000):
            yield self.content[start:start + 1000]


@pytest.fixture
def user_data(tmp_path, monkeypatch):
    """Point every place the blob is looked for at empty temporary directories."""
    directory = tmp_path / "user"
    monkeypatch.setattr(limb_correction, "USER_DATA_DIRECTORY", directory)
    monkeypatch.setattr(limb_correction, "DATA_DIRECTORY", tmp_path / "checkout-data")
    monkeypatch.setattr(limb_correction, "PACKAGE_DIRECTORY", tmp_path / "package")
    monkeypatch.setattr(limb_correction, "load", type("Load", (), {"path_to": staticmethod(
        lambda name: str(tmp_path / "skyfield" / name))})())
    monkeypatch.setattr(limb_correction, "BAND_SHA256", hashlib.sha256(CONTENT).hexdigest())
    monkeypatch.setattr(limb_correction, "BAND_SIZE", len(CONTENT))
    monkeypatch.setattr(limb_correction, "_download_attempted", False)
    monkeypatch.delenv(limb_correction.NO_DOWNLOAD_ENV, raising=False)
    return directory


def test_download_installs_the_blob_where_it_is_looked_for(user_data, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **kw: FakeResponse())
    seen = []

    assert limb_correction.ensure_limb_profile(progress=lambda r, t: seen.append((r, t)))

    target = user_data / limb_correction.BAND_FILE_NAME
    assert target.read_bytes() == CONTENT
    assert limb_correction.band_file() == target
    assert seen[-1] == (len(CONTENT), len(CONTENT))
    assert not (user_data / (limb_correction.BAND_FILE_NAME + ".part")).exists()


def test_a_corrupt_download_is_not_installed(user_data, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **kw: FakeResponse(CONTENT[:-1] + b"x"))

    assert not limb_correction.ensure_limb_profile()

    assert list(user_data.iterdir()) == []


def test_a_failed_download_is_tried_once_per_session(user_data, monkeypatch):
    calls = []

    def offline(*args, **kwargs):
        calls.append(args)
        raise requests.ConnectionError("no network")

    monkeypatch.setattr(requests, "get", offline)

    assert not limb_correction.ensure_limb_profile()
    assert not limb_correction.ensure_limb_profile()
    assert limb_correction.load_default_limb() is None
    assert len(calls) == 1


def test_an_http_error_is_not_installed(user_data, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **kw: FakeResponse(status=404))

    assert not limb_correction.ensure_limb_profile()
    assert not (user_data / limb_correction.BAND_FILE_NAME).exists()


def test_downloading_can_be_switched_off(user_data, monkeypatch):
    monkeypatch.setenv(limb_correction.NO_DOWNLOAD_ENV, "1")
    monkeypatch.setattr(requests, "get", lambda *a, **kw: pytest.fail("must not download"))

    assert not limb_correction.ensure_limb_profile()
    assert limb_correction.load_default_limb() is None


def test_an_installed_blob_is_not_downloaded_again(user_data, monkeypatch):
    user_data.mkdir()
    (user_data / limb_correction.BAND_FILE_NAME).write_bytes(CONTENT)
    monkeypatch.setattr(requests, "get", lambda *a, **kw: pytest.fail("must not download"))

    assert limb_correction.ensure_limb_profile()
