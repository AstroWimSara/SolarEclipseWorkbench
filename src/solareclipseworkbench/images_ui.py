"""Dialogs for after the eclipse: sort the images of a run, and align a timelapse.

Both are opened from the Run report window: "Sort images..." sorts the images of
the run that is shown there (see image_sorter, the GUI of sew_sort), "Align
timelapse..." aligns the frames in a folder on the sun (see timelapse, the GUI of
sew_align).  Reading the capture times, copying the images and finding the sun
take seconds to minutes, so they run in a thread, with a progress bar and a
Cancel button.
"""

import logging
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout,
                             QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSpinBox,
                             QVBoxLayout, QWidget)

from solareclipseworkbench import image_sorter, run_report, timelapse

LOGGER = logging.getLogger(__name__)

MODES = (("Copy", "copy"), ("Move", "move"), ("Hard link", "link"))


class Cancelled(Exception):
    """The user pressed Cancel."""


class Task(QThread):
    """Runs work(progress) in a thread.  progress(done, total, what) shows on the dialog and raises on Cancel."""

    progressed = pyqtSignal(int, int, str)
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, work: Callable, parent=None):
        super().__init__(parent)
        self._work = work
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def progress(self, done: int, total: int, what: str):
        if self._cancel:
            raise Cancelled()
        self.progressed.emit(done, total, what)

    def run(self):
        try:
            result = self._work(self.progress)
        except Cancelled:
            self.cancelled.emit()
        except Exception as error:      # noqa: BLE001 - shown to the user, not lost in the thread
            LOGGER.exception("Task failed")
            self.failed.emit(f"{type(error).__name__}: {error}" if not str(error) else str(error))
        else:
            self.succeeded.emit(result)


def _monospace() -> QFont:
    font = QFont("Monospace")
    font.setStyleHint(QFont.StyleHint.TypeWriter)
    return font


def _open_folder(path: Path):
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class _TaskDialog(QDialog):
    """A dialog with a text area, a progress bar and Cancel, that runs one Task at a time."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.task: Optional[Task] = None
        self.output_text = QPlainTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setFont(_monospace())
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.status = QLabel("")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)

    def busy(self) -> bool:
        return self.task is not None and self.task.isRunning()

    def start(self, work: Callable, on_success: Callable[[object], None]):
        """Run work(progress) in a thread, then on_success(result) in the GUI thread."""
        if self.busy():
            return
        self.task = Task(work, self)
        self.task.progressed.connect(self._on_progress)
        self.task.succeeded.connect(on_success)
        self.task.failed.connect(self._on_failed)
        self.task.cancelled.connect(lambda: self.status.setText("Cancelled"))
        self.task.finished.connect(self._on_finished)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(True)
        self.cancel_button.setEnabled(True)
        self.set_running(True)
        self.task.start()

    def set_running(self, running: bool):
        """Enable or disable the controls that must not change while a task runs."""

    def cancel(self):
        if self.busy():
            self.task.cancel()
            self.status.setText("Cancelling ...")

    def _on_progress(self, done: int, total: int, what: str):
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(done)
        self.status.setText(f"{what} ({done} of {total})" if total > 1 else what)

    def _on_failed(self, message: str):
        self.status.setText("Failed")
        self.output_text.appendPlainText(f"\nError: {message}")

    def _on_finished(self):
        self.progress_bar.setVisible(False)
        self.cancel_button.setEnabled(False)
        self.set_running(False)

    def closeEvent(self, event):
        if self.busy():
            self.task.cancel()
            self.task.wait(10000)
        super().closeEvent(event)

    @staticmethod
    def _folder_row(edit: QLineEdit, browse: Callable) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(edit, 1)
        button = QPushButton("Browse...")
        button.clicked.connect(browse)
        layout.addWidget(button)
        return row


class SortImagesDialog(_TaskDialog):
    """Sort the images of a run into folders by the script line that took them (the GUI of sew_sort)."""

    sorted_into = pyqtSignal(str)

    def __init__(self, run: run_report.Run, log_path: Optional[Path] = None, images_dir: str = "", parent=None):
        super().__init__("Sort images", parent)
        self.run = run
        self.log_path = log_path
        self.resize(820, 620)
        self._infos = None            # (folder, images) of the last folder read: reading is the slow part
        self._plan_key = None

        layout = QVBoxLayout(self)
        intro = QLabel(f"Run: <b>{Path(run.script).name}</b>, loaded {run.started:%Y-%m-%d %H:%M:%S} UTC"
                       + (f" (simulation: {run.simulation})" if run.simulation else "")
                       + "<br>Each image goes in a folder per phase and description, and every bracket, HDR "
                         "series or burst in a folder of its own.  The originals are copied unless chosen otherwise.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self.images_edit = QLineEdit(images_dir)
        self.images_edit.setPlaceholderText("folder with the images, e.g. the DCIM folder of the card")
        self.images_edit.textChanged.connect(self._images_changed)
        form.addRow("Images:", self._folder_row(self.images_edit, self.choose_images))
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("<images>/sorted")
        form.addRow("Sort into:", self._folder_row(self.output_edit, self.choose_output))

        self.camera_box = QComboBox()
        self.camera_box.addItem("Found from the camera model in the images", None)
        for name in image_sorter.run_cameras(run):
            self.camera_box.addItem(name, name)
        self.camera_box.setToolTip("The camera of the script the images are from.  Needed only to tell two "
                                   "bodies of the same model apart: sort the card of each on its own")
        form.addRow("Camera:", self.camera_box)

        offset_row = QWidget()
        offset_layout = QHBoxLayout(offset_row)
        offset_layout.setContentsMargins(0, 0, 0, 0)
        self.offset_check = QCheckBox("Set by hand:")
        self.offset_check.setToolTip("Normally the offset of the camera clock is found from the images.  Set it "
                                     "when the result warns that another offset fits nearly as well")
        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(-2 * 86400, 2 * 86400)
        self.offset_spin.setDecimals(1)
        self.offset_spin.setSuffix(" s")
        self.offset_spin.setEnabled(False)
        self.offset_check.toggled.connect(self.offset_spin.setEnabled)
        offset_layout.addWidget(QLabel("found from the images, or"))
        offset_layout.addWidget(self.offset_check)
        offset_layout.addWidget(self.offset_spin)
        offset_layout.addWidget(QLabel("(camera − computer)"))
        offset_layout.addStretch(1)
        form.addRow("Camera clock:", offset_row)

        self.mode_box = QComboBox()
        for label, mode in MODES:
            self.mode_box.addItem(label, mode)
        self.mode_box.setToolTip("Copy keeps the originals where they are.  Hard link takes no extra space, "
                                 "but only works on the same disk")
        form.addRow("Images are:", self.mode_box)
        self.unmatched_check = QCheckBox("Also put the images that match no command in 'unmatched'")
        self.unmatched_check.setChecked(True)
        form.addRow("", self.unmatched_check)
        layout.addLayout(form)

        layout.addWidget(self.output_text, 1)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        self.preview_button = QPushButton("Preview")
        self.preview_button.setToolTip("Read the images and show where they would go, without touching them")
        self.preview_button.clicked.connect(self.preview)
        self.sort_button = QPushButton("Sort")
        self.sort_button.setDefault(True)
        self.sort_button.clicked.connect(self.sort)
        self.open_button = QPushButton("Open folder")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(lambda: _open_folder(self.output_dir()))
        for button in (self.preview_button, self.sort_button, self.cancel_button, self.open_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

        self.note = ""
        if run.commands and not any(c.planned is not None for c in run.commands):
            self.note = ("This log was written by version 2.0.0 or older: the images are sorted by command, but "
                         "in a simulation the phase is not known.\n\n")
        self.output_text.setPlainText(self.note)

    # Folders

    def images_dir(self) -> Optional[Path]:
        text = self.images_edit.text().strip()
        return Path(text).expanduser() if text else None

    def output_dir(self) -> Optional[Path]:
        text = self.output_edit.text().strip()
        if text:
            return Path(text).expanduser()
        images = self.images_dir()
        return images / "sorted" if images is not None else None

    def choose_images(self):
        folder = QFileDialog.getExistingDirectory(self, "Folder with the images", self.images_edit.text())
        if folder:
            self.images_edit.setText(folder)

    def choose_output(self):
        start = str(self.output_dir() or "")
        folder = QFileDialog.getExistingDirectory(self, "Sort the images into", start)
        if folder:
            self.output_edit.setText(folder)

    def _images_changed(self):
        self._infos = None
        self.open_button.setEnabled(False)

    def set_running(self, running: bool):
        for widget in (self.preview_button, self.sort_button, self.images_edit, self.output_edit, self.camera_box,
                       self.offset_check, self.mode_box, self.unmatched_check):
            widget.setEnabled(not running)
        self.offset_spin.setEnabled(not running and self.offset_check.isChecked())

    # Work

    def _settings(self):
        cameras = [self.camera_box.currentData()] if self.camera_box.currentData() else None
        offset = self.offset_spin.value() if self.offset_check.isChecked() else None
        return cameras, offset

    def _checked_folders(self) -> bool:
        images = self.images_dir()
        if images is None or not images.is_dir():
            QMessageBox.warning(self, "Sort images", "Choose the folder with the images first.")
            return False
        return True

    def _plan(self, images_dir: Path, output: Path, cameras, offset, progress) -> image_sorter.SortPlan:
        if self._infos is None or self._infos[0] != images_dir:
            progress(0, 1, "Looking for images")
            paths = [p for p in image_sorter.find_images(images_dir)
                     if output.resolve() not in p.resolve().parents]
            self._infos = (images_dir, image_sorter.read_image_infos(paths, progress=progress))
        progress(0, 1, "Matching the images to the commands")
        return image_sorter.plan_sorting(self.run, self._infos[1], cameras, offset)

    def preview(self):
        if not self._checked_folders():
            return
        images, output = self.images_dir(), self.output_dir()
        cameras, offset = self._settings()
        self.output_text.setPlainText("")
        self.start(lambda progress: self._plan(images, output, cameras, offset, progress), self._show_preview)

    def _show_preview(self, plan: image_sorter.SortPlan):
        if not plan.placements:
            self.output_text.setPlainText(f"No images in {self.images_dir()}")
            self.status.setText("")
            return
        self.output_text.setPlainText(self.note + image_sorter.format_summary(plan))
        self.status.setText(f"{len(plan.matched)} of {len(plan.placements)} images match a command.  "
                            f"Press Sort to {self.mode_box.currentText().lower()} them into {self.output_dir()}")

    def sort(self):
        if not self._checked_folders():
            return
        images, output = self.images_dir(), self.output_dir()
        mode = self.mode_box.currentData()
        if mode == "move" and QMessageBox.question(
                self, "Sort images", f"Move the images out of {images}?\n\nThey will only be in {output} "
                                     "afterwards.  Copy is safer while the card is still the only copy.") \
                != QMessageBox.StandardButton.Yes:
            return
        cameras, offset = self._settings()
        include_unmatched = self.unmatched_check.isChecked()
        self.output_text.setPlainText("")

        def work(progress):
            plan = self._plan(images, output, cameras, offset, progress)
            if not plan.placements:
                return plan, None
            manifest = image_sorter.apply_plan(plan, output, mode, include_unmatched, progress)
            if mode == "move":
                self._infos = None      # the images are not there any more
            return plan, manifest

        self.start(work, self._show_sorted)

    def _show_sorted(self, result):
        plan, manifest = result
        if manifest is None:
            self.output_text.setPlainText(f"No images in {self.images_dir()}")
            return
        self.output_text.setPlainText(self.note + image_sorter.format_summary(plan)
                                      + f"\n\nWhere every image went: {manifest}")
        self.status.setText(f"{len(plan.matched)} images sorted into {self.output_dir()}")
        self.open_button.setEnabled(True)
        self.sorted_into.emit(str(self.output_dir()))


class AlignTimelapseDialog(_TaskDialog):
    """Align the frames of a timelapse on the sun and crop them, optionally with a video (the GUI of sew_align)."""

    def __init__(self, frames_dir: str = "", parent=None):
        super().__init__("Align timelapse", parent)
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        intro = QLabel("Puts the centre of the sun in the middle of every frame and crops the frames to the same "
                       "size.  Frames in totality are centred by interpolation.  Choose a folder made by "
                       "<i>Sort images</i>, e.g. the partial phase.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self.frames_edit = QLineEdit(frames_dir)
        self.frames_edit.setPlaceholderText("folder with the frames")
        form.addRow("Frames:", self._folder_row(self.frames_edit, self.choose_frames))
        self.subfolders_check = QCheckBox("Include the subfolders")
        self.subfolders_check.setChecked(True)
        form.addRow("", self.subfolders_check)
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("<frames>/aligned")
        form.addRow("Aligned frames into:", self._folder_row(self.output_edit, self.choose_output))

        self.size_spin = QSpinBox()
        self.size_spin.setRange(0, 20000)
        self.size_spin.setSingleStep(100)
        self.size_spin.setSpecialValueText(f"Automatic ({2 * timelapse.DEFAULT_MARGIN:g} diameters of the sun)")
        self.size_spin.setSuffix(" px")
        form.addRow("Size:", self.size_spin)
        self.format_box = QComboBox()
        self.format_box.addItems(["png", "jpg", "tif"])
        form.addRow("Format:", self.format_box)

        video_row = QWidget()
        video_layout = QHBoxLayout(video_row)
        video_layout.setContentsMargins(0, 0, 0, 0)
        self.video_check = QCheckBox("Make a video at")
        self.fps_spin = QDoubleSpinBox()
        self.fps_spin.setRange(1, 120)
        self.fps_spin.setValue(12)
        self.fps_spin.setSuffix(" frames/s")
        video_layout.addWidget(self.video_check)
        video_layout.addWidget(self.fps_spin)
        video_layout.addWidget(QLabel("(timelapse.mp4 in the folder of the aligned frames)"))
        video_layout.addStretch(1)
        if timelapse.ffmpeg_path() is None:
            self.video_check.setEnabled(False)
            self.video_check.setToolTip("No ffmpeg found")
        else:
            self.video_check.setChecked(True)
        form.addRow("Video:", video_row)
        layout.addLayout(form)

        layout.addWidget(self.output_text, 1)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.align_button = QPushButton("Align")
        self.align_button.setDefault(True)
        self.align_button.clicked.connect(self.align)
        self.open_button = QPushButton("Open folder")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(lambda: _open_folder(self.output_dir()))
        self.video_button = QPushButton("Play video")
        self.video_button.setEnabled(False)
        self.video_button.clicked.connect(lambda: _open_folder(self.video_path()))
        for button in (self.align_button, self.cancel_button, self.open_button, self.video_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

    def frames_dir(self) -> Optional[Path]:
        text = self.frames_edit.text().strip()
        return Path(text).expanduser() if text else None

    def output_dir(self) -> Optional[Path]:
        text = self.output_edit.text().strip()
        if text:
            return Path(text).expanduser()
        frames = self.frames_dir()
        return frames / "aligned" if frames is not None else None

    def video_path(self) -> Optional[Path]:
        output = self.output_dir()
        return output / "timelapse.mp4" if output is not None else None

    def choose_frames(self):
        folder = QFileDialog.getExistingDirectory(self, "Folder with the frames", self.frames_edit.text())
        if folder:
            self.frames_edit.setText(folder)

    def choose_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Aligned frames into", str(self.output_dir() or ""))
        if folder:
            self.output_edit.setText(folder)

    def set_running(self, running: bool):
        for widget in (self.align_button, self.frames_edit, self.output_edit, self.subfolders_check, self.size_spin,
                       self.format_box, self.fps_spin):
            widget.setEnabled(not running)
        self.video_check.setEnabled(not running and timelapse.ffmpeg_path() is not None)

    def align(self):
        frames = self.frames_dir()
        if frames is None or not frames.is_dir():
            QMessageBox.warning(self, "Align timelapse", "Choose the folder with the frames first.")
            return
        output = self.output_dir()
        size = self.size_spin.value() or None
        fmt = self.format_box.currentText()
        video = self.video_path() if self.video_check.isChecked() else None
        fps = self.fps_spin.value()
        recursive = self.subfolders_check.isChecked()
        self.output_text.setPlainText("")
        self.open_button.setEnabled(False)
        self.video_button.setEnabled(False)
        lines = []

        def work(progress):
            written = timelapse.align_folder(frames, output, size, fmt, video, fps, recursive, progress,
                                             report=lines.append)
            return written, lines

        self.start(work, self._show_aligned)

    def _show_aligned(self, result):
        written, lines = result
        self.output_text.setPlainText("\n".join(lines))
        self.status.setText(f"{len(written)} aligned frames in {self.output_dir()}")
        self.open_button.setEnabled(bool(written))
        video = self.video_path()
        self.video_button.setEnabled(video is not None and video.exists())
