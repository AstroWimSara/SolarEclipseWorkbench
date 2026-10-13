"""gphoto2 values must stay untranslated on non-English systems (Issue #185)."""

import locale
from unittest.mock import patch

import pytest

from solareclipseworkbench import camera
from solareclipseworkbench.camera import _set_gphoto2_locale, get_cameras


@pytest.fixture(autouse=True)
def restore_locale():
    saved = {name: locale.setlocale(getattr(locale, name))
             for name in ('LC_CTYPE', 'LC_MESSAGES', 'LC_NUMERIC') if hasattr(locale, name)}
    yield
    for name, value in saved.items():
        locale.setlocale(getattr(locale, name), value)


def test_messages_and_numbers_use_c_locale_character_set_follows_user():
    calls = []

    def fake_setlocale(category, value=None):
        calls.append((category, value))
        return 'C'

    with patch.object(camera.locale, 'setlocale', side_effect=fake_setlocale):
        _set_gphoto2_locale()

    # The user's locale is applied first, then messages and numbers are reset to C
    assert calls[0] == (locale.LC_ALL, '')
    assert (locale.LC_MESSAGES, 'C') in calls[1:]
    assert (locale.LC_NUMERIC, 'C') in calls[1:]
    assert all(category != locale.LC_CTYPE for category, _ in calls[1:])


def test_real_locale_after_setup():
    _set_gphoto2_locale()

    assert locale.setlocale(locale.LC_MESSAGES) == 'C'
    assert locale.setlocale(locale.LC_NUMERIC) == 'C'


def test_italian_environment_gives_untranslated_messages(monkeypatch):
    monkeypatch.setenv('LC_ALL', 'it_IT.UTF-8')
    try:
        locale.setlocale(locale.LC_ALL, '')
    except locale.Error:
        pytest.skip('it_IT.UTF-8 locale is not installed')

    _set_gphoto2_locale()

    assert locale.setlocale(locale.LC_MESSAGES) == 'C'
    assert locale.setlocale(locale.LC_NUMERIC) == 'C'
    assert locale.setlocale(locale.LC_CTYPE) == 'it_IT.UTF-8'


def test_invalid_environment_locale_does_not_stop_camera_detection(monkeypatch):
    monkeypatch.setenv('LC_ALL', 'xx_INVALID.UTF-8')

    _set_gphoto2_locale()  # must not raise

    assert locale.setlocale(locale.LC_MESSAGES) == 'C'


def test_get_cameras_sets_locale_before_autodetect():
    order = []

    with patch.object(camera, '_set_gphoto2_locale', side_effect=lambda: order.append('locale')), \
            patch.object(camera, 'gp') as gp_mock:
        gp_mock.Camera.autodetect.side_effect = lambda: order.append('autodetect') or []
        get_cameras()

    assert order == ['locale', 'autodetect']
