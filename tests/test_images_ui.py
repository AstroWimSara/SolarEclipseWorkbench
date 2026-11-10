"""The Sort images and Align timelapse dialogs, opened from the Run report window."""

import os
import sys
import time
from datetime import timedelta
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtWidgets import QApplication, QMessageBox

from solareclipseworkbench import images_ui
from tests.test_image_sorter import C2, CAMERA, _Log


@pytest.fixture(scope="module")
def app():
    # Reuse a QApplication if another test already made one
    return QApplication.instance() or QApplication(sys.argv)


def _finish(app, dialog, timeout=60):
    """Wait for the task of a dialog, and deliver its signals."""
    deadline = time.monotonic() + timeout
    while dialog.busy() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    dialog.task.wait()
    for _ in range(5):
        app.processEvents()
    assert not dialog.busy()


def _card(tmp_path, log):
    """A run with a bracket after C2, and a card with its three frames and a test shot."""
    released = log.add("take_bracket", "C2", C2 + timedelta(seconds=10), 3.0, "corona")
    card = tmp_path / "card"
    card.mkdir()
    times = [released + timedelta(seconds=0.5 * k) for k in range(3)] + [released - timedelta(minutes=20)]
    for n, moment in enumerate(times, start=1):
        moment = moment.replace(tzinfo=None) + timedelta(hours=2)        # camera on local time
        exif = Image.Exif()
        exif[0x010F] = "Canon"
        exif[0x0110] = CAMERA
        exif.get_ifd(0x8769)[0x9003] = moment.strftime("%Y:%m:%d %H:%M:%S")
        exif.get_ifd(0x8769)[0x9291] = f"{moment.microsecond // 10000:02d}"
        Image.new("RGB", (4, 4)).save(card / f"IMG_{n:04d}.JPG", exif=exif)
    return card


def test_preview_then_sort(app, tmp_path):
    log = _Log()
    card = _card(tmp_path, log)
    dialog = images_ui.SortImagesDialog(log.run(), images_dir=str(card))
    assert dialog.output_dir() == card / "sorted"
    assert [dialog.camera_box.itemData(i) for i in range(dialog.camera_box.count())] == [None, CAMERA]

    dialog.preview()
    _finish(app, dialog)
    assert "3 of 4 images matched" in dialog.output_text.toPlainText()
    assert not (card / "sorted").exists()            # a preview touches nothing

    sorted_into = []
    dialog.sorted_into.connect(sorted_into.append)
    dialog.sort()
    _finish(app, dialog)
    frames = list((card / "sorted").rglob("*_IMG_*.JPG"))
    assert len(frames) == 3
    assert all("take_bracket" in str(f.parent) for f in frames)
    assert (card / "sorted" / "unmatched" / "IMG_0004.JPG").exists()
    assert (card / "IMG_0001.JPG").exists()          # copied
    assert sorted_into == [str(card / "sorted")]
    assert dialog.open_button.isEnabled()
    assert dialog.sort_button.isEnabled()


def test_clock_offset_by_hand(app, tmp_path):
    log = _Log()
    card = _card(tmp_path, log)
    dialog = images_ui.SortImagesDialog(log.run(), images_dir=str(card))
    dialog.offset_check.setChecked(True)
    dialog.offset_spin.setValue(0.0)                 # wrong: the camera is 2 h ahead
    dialog.preview()
    _finish(app, dialog)
    assert "0 of 4 images matched" in dialog.output_text.toPlainText()


def test_sort_without_folder_warns(app, monkeypatch):
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warned.append(args[2]))
    dialog = images_ui.SortImagesDialog(_Log().run())
    dialog.sort()
    assert warned and dialog.task is None


def test_cancel_stops_the_task(app):
    dialog = images_ui.AlignTimelapseDialog()
    cancelled = []

    def work(progress):
        for i in range(500):
            progress(i, 500, "working")
            time.sleep(0.01)

    dialog.start(work, lambda result: None)
    dialog.task.cancelled.connect(lambda: cancelled.append(True))
    dialog.cancel()
    _finish(app, dialog)
    assert cancelled
    assert dialog.status.text() == "Cancelled"
    assert dialog.align_button.isEnabled()


def test_align_real_frames(app, tmp_path):
    folder = Path(__file__).parent / "data" / "sun"
    names = ["EosR-100.png", "EosR-330.png", "EosR-500.png"]
    if not all((folder / n).exists() for n in names):
        pytest.skip("eclipse frames not available")
    frames = tmp_path / "frames"
    frames.mkdir()
    for name in names:
        (frames / name).symlink_to(folder / name)
    dialog = images_ui.AlignTimelapseDialog(str(frames))
    dialog.video_check.setChecked(False)
    dialog.size_spin.setValue(200)
    dialog.align()
    _finish(app, dialog)
    assert sorted(p.name for p in (frames / "aligned").glob("frame_*.png")) == \
        ["frame_00001.png", "frame_00002.png", "frame_00003.png"]
    assert "aligned frames" in dialog.output_text.toPlainText()
    assert dialog.open_button.isEnabled()


def test_run_report_window_has_the_buttons(app, tmp_path, monkeypatch):
    from solareclipseworkbench import report_ui, run_report
    monkeypatch.setattr(run_report, "LOG_DIR", tmp_path)
    window = report_ui.RunReportWindow()
    assert window.sort_button.text() == "Sort images..."
    informed = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: informed.append(args[2]))
    window.sort_images()                             # no log, so no run
    assert informed
    window._sorted_dir = str(tmp_path)
    window.align_timelapse()
    assert window._align_dialog.frames_edit.text() == str(tmp_path)
    window._align_dialog.close()
