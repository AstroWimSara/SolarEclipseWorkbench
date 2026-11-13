"""Sort the images of a run by the script line that took them.

After the eclipse, the card holds a few hundred or thousand frames named
IMG_1234.CR2.  Which ones are the bracket of the diamond ring, which the HDR
series of the corona, which the partial phases for the timelapse?  The log of
the run knows: every command has a "Planned:" line (time, camera, reference,
description), and a "released the shutter" line with the time the shutter was
really released (see run_report).  This module lines the capture time of each
image up against those commands, and copies (or moves, or links) the images into
folders ready for stacking:

    <out>/[<camera>/]<phase>/<label>/<file>                         take_picture, relay_shoot, relay_bulb
    <out>/[<camera>/]<phase>/<label>/<time>_<reference>_<command>/<file>   take_bracket, take_hdr, take_burst, relay_burst

The phase is the part of the eclipse the command was written for (before C1,
C1-C2, C2-C3, C3-C4, after C4), the label the description of the script line.
A command that takes more than one frame (a bracket, an HDR series, a burst) gets
its own folder, so it can be given to a stacking or HDR program as it is.  The
single shots with the same description (a for loop over the partial phase) stay
together in one folder: that is the timelapse (see timelapse.py).

The camera clock is not the computer clock: it is often on local time, and a
camera clock drifts seconds per week.  The offset is found from the images
themselves: it is the offset at which most images fall in the time a command
kept the camera busy.  It can also be given (--clock-offset).

Images that match no command (test shots, frames of a dropped command) go to
``unmatched``.  ``sorting.csv`` in the output folder lists where every image
went and why.

The capture time is read with exiftool when it is installed (every raw format),
otherwise with a small reader built in here: JPEG, TIFF-based raws (CR2, NEF,
ARW, DNG, ORF, PEF, RW2), Fujifilm RAF, Canon CR3, and PNG with XMP.
"""

import argparse
import csv
import json
import logging
import os
import re
import shutil
import struct
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from solareclipseworkbench import run_report

LOGGER = logging.getLogger(__name__)

#: File extensions treated as images (lower case)
IMAGE_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".tif", ".tiff", ".png", ".heic", ".heif", ".hif",
    ".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".dng", ".raf", ".orf", ".rw2", ".pef",
})

#: Commands that release the shutter, and those of them that take more than one frame
SHOT_COMMANDS = frozenset({"take_picture", "take_burst", "take_bracket", "take_hdr",
                           "relay_shoot", "relay_burst", "relay_bulb"})
GROUP_COMMANDS = frozenset({"take_burst", "take_bracket", "take_hdr", "relay_burst"})

#: An image this many seconds before or after the time a command kept the camera busy still belongs to it
DEFAULT_TOLERANCE_S = 1.0

#: Time a command keeps the camera busy when neither the log nor the estimate says
_DEFAULT_BUSY_S = 1.0

#: Order of the contacts, to name the phase of a command
_CONTACTS = ("C1", "C2", "C3", "C4")

UNMATCHED = "unmatched"

#: Called as progress(done, total, what) while a long step runs; it may raise to stop the step
Progress = Callable[[int, int, str], None]


# --- Capture time -------------------------------------------------------------

@dataclass
class ImageInfo:
    """An image and what its metadata says about when and with what it was taken."""
    path: Path
    taken: Optional[datetime] = None        # camera clock, naive
    has_subseconds: bool = False
    make: str = ""
    model: str = ""
    serial: str = ""

    @property
    def body(self) -> str:
        """The camera body, as far as the metadata tells."""
        name = self.model.strip()
        make = self.make.strip()
        if make and not name.lower().startswith(make.split()[0].lower()):
            name = f"{make} {name}".strip()
        if self.serial:
            name = f"{name} #{self.serial}"
        return name or "unknown camera"


_EXIF_DATE = re.compile(r"^(\d{4}):(\d\d):(\d\d)[ T](\d\d):(\d\d):(\d\d)(\.\d+)?")


def _parse_exif_date(value, subsec=None) -> Tuple[Optional[datetime], bool]:
    """A naive datetime from an EXIF date ("2026:08:12 20:29:22"), with its sub-seconds when given."""
    if value is None:
        return None, False
    if isinstance(value, bytes):
        value = value.decode("ascii", "replace")
    match = _EXIF_DATE.match(str(value).strip().strip("\x00"))
    if match is None:
        return None, False
    try:
        moment = datetime(*(int(g) for g in match.groups()[:6]))
    except ValueError:
        return None, False
    fraction = match.group(7)
    if subsec not in (None, ""):
        if isinstance(subsec, bytes):
            subsec = subsec.decode("ascii", "replace")
        digits = re.sub(r"\D", "", str(subsec))
        if digits:
            fraction = "." + digits
    if fraction:
        moment += timedelta(seconds=float(fraction))
        return moment, True
    return moment, False


# TIFF tags
_MAKE, _MODEL, _DATETIME, _EXIF_IFD = 0x010F, 0x0110, 0x0132, 0x8769
_DATETIME_ORIGINAL, _SUBSEC_ORIGINAL, _SUBSEC = 0x9003, 0x9291, 0x9290
_BODY_SERIAL = 0xA431
_TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4}


def _read_ifd(data: bytes, offset: int, endian: str, base: int = 0) -> Dict[int, object]:
    """The tags of one IFD of a TIFF structure that starts at base, as {tag: value} (ASCII and LONG only)."""
    tags: Dict[int, object] = {}
    if offset + base + 2 > len(data):
        return tags
    (count,) = struct.unpack_from(endian + "H", data, base + offset)
    for i in range(min(count, 1000)):
        entry = base + offset + 2 + 12 * i
        if entry + 12 > len(data):
            break
        tag, kind, n = struct.unpack_from(endian + "HHI", data, entry)
        size = _TYPE_SIZES.get(kind, 1) * n
        where = entry + 8 if size <= 4 else base + struct.unpack_from(endian + "I", data, entry + 8)[0]
        if kind == 2:
            tags[tag] = data[where:where + n].split(b"\x00")[0].decode("ascii", "replace").strip()
        elif kind == 4 and n == 1:
            tags[tag] = struct.unpack_from(endian + "I", data, where)[0]
        elif kind == 13 and n == 1:     # IFD
            tags[tag] = struct.unpack_from(endian + "I", data, where)[0]
    return tags


def _tiff_info(data: bytes, base: int = 0, exif_base: Optional[int] = None) -> dict:
    """Make, model, serial and time from a TIFF structure at base (the start of a TIFF raw, or an APP1 segment)."""
    order = data[base:base + 2]
    if order not in (b"II", b"MM"):
        return {}
    endian = "<" if order == b"II" else ">"
    (ifd0,) = struct.unpack_from(endian + "I", data, base + 4)
    tags = _read_ifd(data, ifd0, endian, base)
    info = {"make": tags.get(_MAKE, ""), "model": tags.get(_MODEL, ""), "date": tags.get(_DATETIME)}
    if _EXIF_IFD in tags:
        exif = _read_ifd(data, int(tags[_EXIF_IFD]), endian, base)
        info.update(_exif_fields(exif))
    return info


def _exif_fields(exif: dict) -> dict:
    out = {}
    if exif.get(_DATETIME_ORIGINAL):
        out["date"] = exif[_DATETIME_ORIGINAL]
        out["subsec"] = exif.get(_SUBSEC_ORIGINAL)
    if exif.get(_BODY_SERIAL):
        out["serial"] = exif[_BODY_SERIAL]
    return out


def _jpeg_info(data: bytes) -> dict:
    """The EXIF of a JPEG: the TIFF structure in its APP1 segment."""
    position = 2
    while position + 4 <= len(data) and data[position] == 0xFF:
        marker = data[position + 1]
        (length,) = struct.unpack_from(">H", data, position + 2)
        if marker == 0xE1 and data[position + 4:position + 10] == b"Exif\x00\x00":
            return _tiff_info(data, position + 10)
        if marker in (0xDA, 0xD9):      # start of scan, end of image
            break
        position += 2 + length
    return {}


def _cr3_info(data: bytes) -> dict:
    """Canon CR3: IFD0 is in the CMT1 box, the EXIF IFD in CMT2, each a TIFF structure of its own."""
    info: dict = {}
    for box in (b"CMT1", b"CMT2"):
        at = data.find(box)
        if at < 4:
            continue
        start = at + 4
        order = data[start:start + 2]
        if order not in (b"II", b"MM"):
            continue
        endian = "<" if order == b"II" else ">"
        (ifd,) = struct.unpack_from(endian + "I", data, start + 4)
        tags = _read_ifd(data, ifd, endian, start)
        if box == b"CMT1":
            info.update({"make": tags.get(_MAKE, ""), "model": tags.get(_MODEL, "")})
            info.setdefault("date", tags.get(_DATETIME))
        else:
            info.update(_exif_fields(tags))
    return info


def _builtin_info(path: Path) -> dict:
    """Make, model, serial, date and sub-seconds without exiftool."""
    suffix = path.suffix.lower()
    with open(path, "rb") as f:
        head = f.read(4 * 1024 * 1024)
    if head[:2] == b"\xff\xd8":
        return _jpeg_info(head)
    if head[:2] in (b"II", b"MM"):
        return _tiff_info(head)
    if head[:15] == b"FUJIFILMCCD-RAW":
        # The header points at an embedded JPEG with the full EXIF
        (offset, length) = struct.unpack_from(">II", head, 84)
        with open(path, "rb") as f:
            f.seek(offset)
            return _jpeg_info(f.read(min(length, 1024 * 1024)))
    if suffix == ".cr3" or head[4:12] == b"ftypcrx ":
        return _cr3_info(head)
    if head[:8] == b"\x89PNG\r\n\x1a\n" or suffix in (".heic", ".heif", ".hif"):
        try:
            from PIL import Image
            with Image.open(path) as image:
                xmp = image.info.get("XML:com.adobe.xmp", "") or ""
                if isinstance(xmp, bytes):
                    xmp = xmp.decode("utf-8", "replace")
                exif = image.getexif()
                sub = exif.get_ifd(_EXIF_IFD)
                info = {"make": exif.get(_MAKE, ""), "model": exif.get(_MODEL, ""), "date": exif.get(_DATETIME)}
                info.update(_exif_fields(sub))
                match = re.search(r'(?:exif:DateTimeOriginal|xmp:CreateDate|photoshop:DateCreated)="([^"]+)"', xmp)
                if not info.get("date") and match:
                    info["date"] = match.group(1).replace("-", ":", 2)
                return info
        except Exception as error:          # noqa: BLE001 - an image Pillow cannot read has no time
            LOGGER.debug("%s: %s", path, error)
    return {}


def _info_from_fields(path: Path, fields: dict) -> ImageInfo:
    taken, has_sub = _parse_exif_date(fields.get("date"), fields.get("subsec"))
    return ImageInfo(path=path, taken=taken, has_subseconds=has_sub, make=str(fields.get("make") or ""),
                     model=str(fields.get("model") or ""), serial=str(fields.get("serial") or ""))


def _exiftool_infos(paths: Sequence[Path], progress: Optional[Progress] = None) -> Optional[Dict[Path, ImageInfo]]:
    """Read all images with one call of exiftool, None when it is not installed or fails."""
    exe = shutil.which("exiftool")
    if exe is None or not paths:
        return None
    infos: Dict[Path, ImageInfo] = {}
    tags = ["-DateTimeOriginal", "-SubSecTimeOriginal", "-CreateDate", "-Make", "-Model", "-SerialNumber"]
    chunk = 200
    for start in range(0, len(paths), chunk):
        if progress is not None:
            progress(start, len(paths), "Reading the capture times")
        batch = [str(p) for p in paths[start:start + chunk]]
        try:
            result = subprocess.run([exe, "-json", "-q", "-q", "-d", "%Y:%m:%d %H:%M:%S", *tags, *batch],
                                    capture_output=True, text=True, timeout=600, check=False)
            rows = json.loads(result.stdout or "[]")
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            LOGGER.warning("exiftool failed (%s), using the built-in reader", error)
            return None
        for row in rows:
            path = Path(row.get("SourceFile", ""))
            fields = {"date": row.get("DateTimeOriginal") or row.get("CreateDate"),
                      "subsec": row.get("SubSecTimeOriginal"), "make": row.get("Make"),
                      "model": row.get("Model"), "serial": row.get("SerialNumber")}
            infos[path] = _info_from_fields(path, {k: (str(v) if v is not None else None) for k, v in fields.items()})
    return infos


def read_image_info(path: Path) -> ImageInfo:
    """Capture time, make, model and serial of one image, with the built-in reader."""
    try:
        return _info_from_fields(path, _builtin_info(path))
    except (OSError, struct.error, ValueError) as error:
        LOGGER.debug("%s: %s", path, error)
        return ImageInfo(path=path)


def read_image_infos(paths: Sequence[Path], use_exiftool: bool = True,
                     progress: Optional[Progress] = None) -> List[ImageInfo]:
    """Capture time, make, model and serial of the images; exiftool when installed, else the built-in reader."""
    from_tool = _exiftool_infos(paths, progress) if use_exiftool else None
    infos = []
    for number, path in enumerate(paths):
        if progress is not None and from_tool is None and number % 20 == 0:
            progress(number, len(paths), "Reading the capture times")
        info = from_tool.get(path) if from_tool is not None else None
        if info is None or info.taken is None:
            info = read_image_info(path)
        infos.append(info)
    return infos


def find_images(folder: Path, recursive: bool = True) -> List[Path]:
    """Image files in a folder (and its subfolders), sorted by name."""
    folder = Path(folder)
    pattern = folder.rglob("*") if recursive else folder.glob("*")
    return sorted(p for p in pattern if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
                  and not p.name.startswith("."))


# --- Commands of the run ------------------------------------------------------

@dataclass
class ShotCommand:
    """A command of the run that released the shutter, and the time the camera was busy with it."""
    outcome: run_report.CommandOutcome
    start: float                     # computer clock, seconds since the epoch
    end: float
    eclipse_time: Optional[datetime]  # the time of the eclipse it was written for (UTC)
    phase: str

    @property
    def func_name(self) -> str:
        return self.outcome.func_name

    @property
    def camera(self) -> str:
        return self.outcome.camera or "relay"

    @property
    def label(self) -> str:
        return self.outcome.description.strip() or self.func_name


def _simulation_shift(run: run_report.Run) -> Optional[timedelta]:
    """Planned time minus the time of the eclipse it was written for: the simulation offset and the GPS correction.

    None when the log does not tell (no "Planned:" lines, logs before the run report) and the run was a
    simulation; outside a simulation the computer clock is the time of the eclipse.
    """
    shifts = []
    for command in run.commands:
        moment = run.reference_moments.get(command.reference_moment) or \
            run.reference_moments.get(command.reference_moment.lower())
        if command.planned is None or moment is None or command.offset_s is None:
            continue
        shifts.append((command.planned - moment - timedelta(seconds=command.offset_s)).total_seconds())
    if shifts:
        return timedelta(seconds=float(np.median(shifts)))
    return None if run.simulation else timedelta(0)


def phase_names(run: run_report.Run) -> List[Tuple[str, Optional[datetime]]]:
    """The phases of the eclipse, as (folder name, start); the first starts at the beginning of time."""
    moments = {name: run.reference_moments.get(name) for name in _CONTACTS}
    if moments["C2"] is None or moments["C3"] is None:      # a partial eclipse
        bounds = [("C1", moments["C1"]), ("C4", moments["C4"])]
    else:
        bounds = [(name, moments[name]) for name in _CONTACTS]
    bounds = [(name, moment) for name, moment in bounds if moment is not None]
    if not bounds:
        return [("all", None)]
    phases = [(f"0_before_{bounds[0][0]}", None)]
    for i, (name, moment) in enumerate(bounds[:-1]):
        phases.append((f"{i + 1}_{name}-{bounds[i + 1][0]}", moment))
    phases.append((f"{len(bounds)}_after_{bounds[-1][0]}", bounds[-1][1]))
    return phases


def _phase_of(moment: Optional[datetime], phases: List[Tuple[str, Optional[datetime]]]) -> str:
    if moment is None:
        return "phase_unknown"
    name = phases[0][0]
    for phase, start in phases:
        if start is None or moment >= start:
            name = phase
    return name


def shot_commands(run: run_report.Run, cameras: Optional[Iterable[str]] = None) -> List[ShotCommand]:
    """The commands of a run that released (or will have released) the shutter, with their busy time."""
    wanted = set(cameras) if cameras else None
    shift = _simulation_shift(run)
    phases = phase_names(run)
    commands = []
    for outcome in run.commands:
        if outcome.func_name not in SHOT_COMMANDS:
            continue
        if outcome.dropped or outcome.missed_by is not None:
            continue
        if outcome.failed and outcome.released_at is None:
            continue
        camera = outcome.camera or "relay"
        if wanted is not None and camera not in wanted:
            continue
        start = outcome.released_at or outcome.planned
        if start is None:
            continue
        busy = outcome.busy_s if outcome.busy_s is not None else outcome.estimated_busy_s
        if busy is None or busy <= 0:
            busy = _DEFAULT_BUSY_S
        if outcome.released_at is not None and outcome.planned is not None and outcome.busy_s is not None:
            # The busy time runs from the planned time, the release can be later
            busy = max(0.0, busy - (outcome.released_at - outcome.planned).total_seconds())
        planned = outcome.planned or start
        eclipse_time = planned - shift if shift is not None else None
        commands.append(ShotCommand(outcome=outcome, start=start.timestamp(), end=start.timestamp() + busy,
                                    eclipse_time=eclipse_time, phase=_phase_of(eclipse_time, phases)))
    commands.sort(key=lambda c: c.start)
    return commands


def run_cameras(run: run_report.Run) -> List[str]:
    """The camera names that have shot commands in the run ("relay" for the relay commands)."""
    names = []
    for outcome in run.commands:
        if outcome.func_name in SHOT_COMMANDS:
            name = outcome.camera or "relay"
            if name not in names:
                names.append(name)
    return names


# --- Matching -----------------------------------------------------------------

def _normalise(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def cameras_for_body(body: ImageInfo, cameras: Sequence[str]) -> List[str]:
    """The camera names of the run that are this body: the names that contain its model (aliases included)."""
    model = _normalise(body.model)
    if not model:
        return []
    found = []
    for camera in cameras:
        name = _normalise(camera)
        if model in name or (name and name in model):
            found.append(camera)
    if not found:
        # "Canon EOS 80D" in the log, "80D" or "EOS 80D" in some EXIF; or the other way round
        words = [w for w in re.split(r"\W+", body.model.lower()) if any(ch.isdigit() for ch in w)]
        found = [c for c in cameras if words and all(w in c.lower() for w in words)]
    return found


def _corrected_times(images: Sequence[ImageInfo]) -> np.ndarray:
    """Capture times as seconds (naive camera clock read as UTC); a time to the second is taken as its middle."""
    return np.array([info.taken.replace(tzinfo=timezone.utc).timestamp() + (0.0 if info.has_subseconds else 0.5)
                     for info in images], dtype=float)


class _Windows:
    """The busy windows of the commands, to look up which command a moment falls in."""

    def __init__(self, commands: Sequence[ShotCommand], tolerance_s: float):
        self.commands = list(commands)
        self.starts = np.array([c.start for c in commands], dtype=float) - tolerance_s
        self.ends = np.array([c.end for c in commands], dtype=float) + tolerance_s
        self.end_max = np.maximum.accumulate(self.ends) if len(self.ends) else self.ends

    def covered(self, moments: np.ndarray) -> np.ndarray:
        """For each moment, whether it falls in a window."""
        if not len(self.starts):
            return np.zeros(len(moments), dtype=bool)
        index = np.searchsorted(self.starts, moments, side="right") - 1
        ok = index >= 0
        result = np.zeros(len(moments), dtype=bool)
        result[ok] = self.end_max[index[ok]] >= moments[ok]
        return result

    def command_at(self, moment: float) -> Optional[int]:
        """The command a moment falls in: of overlapping ones, the one that started last."""
        index = int(np.searchsorted(self.starts, moment, side="right")) - 1
        while index >= 0:
            if self.ends[index] >= moment:
                return index
            if self.end_max[index] < moment:
                return None
            index -= 1
        return None


@dataclass
class ClockFit:
    offset_s: float                 # camera clock minus computer clock
    matched: int
    total: int
    runner_up_s: Optional[float] = None   # another offset that matches nearly as many images
    runner_up_matched: int = 0

    @property
    def ambiguous(self) -> bool:
        return self.runner_up_s is not None and self.runner_up_matched >= 0.9 * self.matched


def estimate_clock_offset(times: np.ndarray, commands: Sequence[ShotCommand],
                          tolerance_s: float = DEFAULT_TOLERANCE_S) -> ClockFit:
    """The offset of the camera clock (camera minus computer) at which most images fall in a command.

    The candidates are the differences between the capture times and the command
    starts (the first frame of every command is close to its start), counted in
    bins of one second; the best bins are searched in steps of 0.05 s.  Of the
    offsets that match the same number of images, the one that puts the first
    frame of the commands closest to their start wins.
    """
    windows = _Windows(commands, tolerance_s)
    if not len(times) or not commands:
        return ClockFit(0.0, 0, len(times))
    starts = np.array([c.start for c in commands])
    sample = times if len(times) * len(starts) <= 4_000_000 else \
        np.random.default_rng(0).choice(times, max(1, 4_000_000 // len(starts)), replace=False)
    differences = np.floor((sample[:, None] - starts[None, :]).ravel())
    values, counts = np.unique(differences, return_counts=True)
    top = values[np.argsort(-counts)[:40]]

    def score(offset: float) -> Tuple[int, float]:
        moments = times - offset
        covered = windows.covered(moments)
        firsts: Dict[int, float] = {}
        for moment in moments[covered]:
            index = windows.command_at(moment)
            if index is not None:
                lag = moment - commands[index].start
                firsts[index] = min(firsts.get(index, lag), lag)
        lead = float(np.median(np.abs(list(firsts.values())))) if firsts else 1e9
        return int(covered.sum()), lead

    results = []
    for value in top:
        for offset in value - 1.0 + np.arange(0.0, 2.0 + 1e-9, 0.05):
            matched = int(windows.covered(times - offset).sum())
            results.append((matched, float(offset)))
    best_matched = max(m for m, _ in results)
    near_best = sorted({round(o, 3) for m, o in results if m == best_matched})
    scored = [(score(o), o) for o in near_best]
    (matched, _lead), offset = min(scored, key=lambda s: (-s[0][0], s[0][1]))
    others = [(m, o) for m, o in results if abs(o - offset) > 2 * tolerance_s + 1.0]
    fit = ClockFit(offset, matched, len(times))
    if others:
        runner_matched, runner_offset = max(others)
        fit.runner_up_s, fit.runner_up_matched = runner_offset, runner_matched
    return fit


def parse_offset(text: str) -> float:
    """Seconds from "12.5", "-3600" or "+02:00:03.5" (hh:mm:ss)."""
    text = text.strip()
    match = re.fullmatch(r"([+-]?)(\d+):(\d\d)(?::(\d\d(?:\.\d*)?))?", text)
    if match:
        seconds = int(match[2]) * 3600 + int(match[3]) * 60 + float(match[4] or 0)
        return -seconds if match[1] == "-" else seconds
    return float(text)


# --- The plan -----------------------------------------------------------------

@dataclass
class Placement:
    """Where one image goes, and why."""
    image: ImageInfo
    destination: Optional[Path] = None      # relative to the output folder
    command: Optional[ShotCommand] = None
    frame: int = 0                          # 1, 2, ... within its command
    frames: int = 0                         # frames of its command
    camera: str = ""
    clock_offset_s: Optional[float] = None
    reason: str = ""


@dataclass
class SortPlan:
    placements: List[Placement] = field(default_factory=list)
    fits: Dict[str, Tuple[List[str], ClockFit]] = field(default_factory=dict)   # body: (cameras, fit)
    warnings: List[str] = field(default_factory=list)

    @property
    def matched(self) -> List[Placement]:
        return [p for p in self.placements if p.command is not None]

    @property
    def unmatched(self) -> List[Placement]:
        return [p for p in self.placements if p.command is None]


_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def safe_name(text: str, limit: int = 60) -> str:
    """A folder or file name from a description: no characters Windows or macOS refuse, no trailing dots."""
    name = _UNSAFE.sub("_", text).strip().strip(".")
    name = re.sub(r"\s+", " ", name)
    return (name[:limit].rstrip(" .") or "_")


def reference_name(reference: str) -> str:
    """C2-00:00:04.0 as C2-00h00m04.0s, usable in a file name; "" for a command without a reference."""
    match = re.fullmatch(r"\s*([A-Za-z0-9_]+)\s*([+-])\s*(\d+):(\d+):(\d+(?:\.\d+)?)\s*", reference)
    if match is None:
        return ""
    ref, sign, h, m, s = match.groups()
    return f"{ref.upper()}{sign}{int(h):02d}h{int(m):02d}m{float(s):04.1f}s"


def _time_name(command: ShotCommand) -> str:
    """The time of the command (of the eclipse when known, else of the computer clock), as HHMMSS.s"""
    moment = command.eclipse_time
    if moment is None:
        moment = datetime.fromtimestamp(command.start, timezone.utc)
    return moment.strftime("%H%M%S.%f")[:8]


def plan_sorting(run: run_report.Run, images: Sequence[ImageInfo], cameras: Optional[Sequence[str]] = None,
                 clock_offset_s: Optional[float] = None, tolerance_s: float = DEFAULT_TOLERANCE_S) -> SortPlan:
    """Which command took each image, and where it goes.

    Args:
        - run: The run (from run_report.read_log)
        - images: The images, with their capture time (read_image_infos)
        - cameras: Camera names of the run the images are from; None to find out from the camera model in the images
        - clock_offset_s: Camera clock minus computer clock; None to find it from the images
        - tolerance_s: How far outside the busy time of a command an image may be
    """
    plan = SortPlan()
    names = run_cameras(run)
    if cameras:
        unknown = [c for c in cameras if c not in names]
        if unknown:
            plan.warnings.append(f"no shot commands in this run for {', '.join(unknown)}; "
                                 f"the cameras of the run are: {', '.join(names) or 'none'}")

    timed = [info for info in images if info.taken is not None]
    for info in images:
        if info.taken is None:
            plan.placements.append(Placement(info, Path(UNMATCHED) / info.path.name, reason="no capture time"))

    bodies: Dict[str, List[ImageInfo]] = defaultdict(list)
    for info in timed:
        bodies[info.body].append(info)

    for body, body_images in sorted(bodies.items()):
        if cameras:
            chosen = list(cameras)
        else:
            chosen = cameras_for_body(body_images[0], names) or list(names)
        commands = shot_commands(run, chosen)
        times = _corrected_times(body_images)
        if clock_offset_s is not None:
            windows = _Windows(commands, tolerance_s)
            fit = ClockFit(clock_offset_s, int(windows.covered(times - clock_offset_s).sum()), len(times))
        else:
            fit = estimate_clock_offset(times, commands, tolerance_s)
        plan.fits[body] = (chosen, fit)
        if fit.ambiguous:
            plan.warnings.append(
                f"{body}: a camera clock offset of {fit.runner_up_s:+.1f} s matches nearly as many images "
                f"({fit.runner_up_matched}) as {fit.offset_s:+.1f} s ({fit.matched}); check the result, "
                f"or give the offset with --clock-offset")
        if commands and fit.matched < 0.5 * len(times):
            plan.warnings.append(f"{body}: only {fit.matched} of {len(times)} images match a command of "
                                 f"{', '.join(chosen)}: is this the right log, run and camera?")

        windows = _Windows(commands, tolerance_s)
        per_command: Dict[int, List[Placement]] = defaultdict(list)
        for info, moment in zip(body_images, times - fit.offset_s):
            index = windows.command_at(float(moment))
            placement = Placement(info, clock_offset_s=fit.offset_s)
            if index is None:
                placement.reason = "outside the time of every command"
                placement.destination = Path(UNMATCHED) / info.path.name
                plan.placements.append(placement)
            else:
                per_command[index].append(placement)
        for index, placements in per_command.items():
            command = commands[index]
            placements.sort(key=lambda p: (p.image.taken, p.image.path.name))
            for frame, placement in enumerate(placements, start=1):
                placement.command, placement.frame, placement.frames = command, frame, len(placements)
                placement.camera = command.camera
                plan.placements.append(placement)

    _assign_destinations(plan)
    return plan


def _assign_destinations(plan: SortPlan) -> None:
    matched = plan.matched
    several_cameras = len({p.camera for p in matched}) > 1
    # RAW+JPEG pairs share a frame number: number the frames by capture moment
    for placement in matched:
        command = placement.command
        folder = Path(safe_name(placement.camera)) if several_cameras else Path()
        folder = folder / command.phase / safe_name(command.label)
        stem = "_".join(part for part in (_time_name(command), reference_name(command.outcome.reference)) if part)
        if command.func_name in GROUP_COMMANDS:
            folder = folder / f"{stem}_{command.func_name}"
            name = f"{placement.frame:03d}_{placement.image.path.name}"
        else:
            name = f"{stem}_{placement.image.path.name}"
        placement.destination = folder / name


# --- Doing it -----------------------------------------------------------------

def _unique(path: Path, taken: set) -> Path:
    candidate, n = path, 1
    # lexists: a dangling symbolic link (of an earlier --link sort) is a name in use too; copying onto it would
    # write through it
    while candidate in taken or os.path.lexists(candidate):
        candidate = path.with_name(f"{path.stem}_{n}{path.suffix}")
        n += 1
    taken.add(candidate)
    return candidate


def apply_plan(plan: SortPlan, out_dir: Path, mode: str = "copy", include_unmatched: bool = True,
               progress: Optional[Progress] = None) -> Path:
    """Copy, move or link the images to their place, and write sorting.csv.  Returns the path of sorting.csv.

    When progress raises, the images done so far stay sorted and sorting.csv lists them.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    taken: set = set()
    rows = []
    failures: list = []
    try:
        _place_all(plan, out_dir, mode, include_unmatched, progress, taken, rows, failures)
    finally:
        if failures:
            shown = failures[:20]
            more = f" (and {len(failures) - 20} more)" if len(failures) > 20 else ""
            plan.warnings.append(f"{len(failures)} image(s) could not be {_DONE.get(mode, 'copied')} and were "
                                 f"left where they are{more}: " + "; ".join(shown))
        manifest = out_dir / "sorting.csv"
        with open(manifest, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["source"])
            writer.writeheader()
            writer.writerows(rows)
    return manifest


_DONE = {"move": "moved", "link": "linked", "copy": "copied"}


def _place_all(plan: SortPlan, out_dir: Path, mode: str, include_unmatched: bool, progress: Optional[Progress],
               taken: set, rows: list, failures: list) -> None:
    verb = {"move": "Moving", "link": "Linking"}.get(mode, "Copying")
    for number, placement in enumerate(plan.placements):
        if progress is not None:
            progress(number, len(plan.placements), f"{verb} the images")
        target = None
        note = placement.reason
        if placement.destination is not None and (placement.command is not None or include_unmatched):
            target = _unique(out_dir / placement.destination, taken)
            source = placement.image.path
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                _place_one(source, target, mode)
            except (OSError, shutil.Error) as error:
                # One unreadable file (a bad sector on the card, a file without permission) must not stop the
                # others: it is left where it is, and listed in sorting.csv and the warnings
                target, note = _undo_partial(source, target, mode, error)
                failures.append(f"{source}: {error}")
        command = placement.command
        rows.append({
            "source": str(placement.image.path),
            "destination": str(target.relative_to(out_dir)) if target is not None else "",
            "camera_body": placement.image.body,
            "capture_time": placement.image.taken.isoformat(timespec="milliseconds") if placement.image.taken else "",
            "clock_offset_s": f"{placement.clock_offset_s:.2f}" if placement.clock_offset_s is not None else "",
            "camera": placement.camera,
            "command": command.func_name if command else "",
            "reference": command.outcome.reference if command else "",
            "planned_utc": command.outcome.planned.isoformat(timespec="milliseconds")
            if command and command.outcome.planned else "",
            "phase": command.phase if command else "",
            "label": command.label if command else "",
            "frame": f"{placement.frame}/{placement.frames}" if command else "",
            "note": note,
        })


def _place_one(source: Path, target: Path, mode: str) -> None:
    """Copy, move or link one image to a target that does not exist yet."""
    if mode == "move":
        shutil.move(str(source), target)
    elif mode == "link":
        try:
            os.link(source, target)
        except OSError:
            target.symlink_to(source.resolve())
    else:
        shutil.copy2(source, target)


def _undo_partial(source: Path, target: Path, mode: str, error: Exception) -> Tuple[Optional[Path], str]:
    """After a failed copy, move or link: (the target to list, the note).

    The original is never touched here.  A target is only removed when the
    original is still there in full, so the image is never lost: a half copy
    goes, a whole copy of which the original could not be removed (a card that
    is write-protected, in move mode) stays and is listed.
    """
    LOGGER.warning("Could not %s %s to %s: %s", mode, source, target, error)
    if not os.path.lexists(target):
        return None, f"failed: {error}"
    try:
        source_size = source.stat().st_size
    except OSError:
        # The original is gone: what was written is the only copy, keep it
        return target, f"the original is gone; check this copy: {error}"
    if target.is_file() and not target.is_symlink() and target.stat().st_size == source_size:
        if mode == "move":
            return target, f"copied, but the original could not be removed: {error}"
        return target, f"copied, but: {error}"
    try:
        target.unlink()
    except OSError as unlink_error:
        LOGGER.warning("Could not remove the partial %s: %s", target, unlink_error)
        return target, f"failed, partial file left here: {error}"
    return None, f"failed: {error}"


def format_summary(plan: SortPlan) -> str:
    """What the sorting will do, in a few lines."""
    lines = []
    for body, (cameras, fit) in plan.fits.items():
        lines.append(f"{body}: commands of {', '.join(cameras) or '-'}, camera clock "
                     f"{_describe_offset(fit.offset_s)} the computer clock; {fit.matched} of {fit.total} images matched")
    groups: Dict[Tuple[str, str], int] = defaultdict(int)
    for placement in plan.matched:
        groups[(placement.command.phase, str(placement.destination.parent))] += 1
    current = None
    for (phase, folder), count in sorted(groups.items()):
        if phase != current:
            lines.append(f"  {phase}")
            current = phase
        lines.append(f"    {folder}: {count}")
    if plan.unmatched:
        lines.append(f"  {UNMATCHED}: {len(plan.unmatched)}")
    lines += [f"Warning: {w}" for w in plan.warnings]
    return "\n".join(lines)


def _describe_offset(seconds: float) -> str:
    sign = "ahead of" if seconds >= 0 else "behind"
    s = abs(seconds)
    hours, rest = divmod(s, 3600)
    minutes, secs = divmod(rest, 60)
    text = (f"{int(hours)} h " if hours else "") + (f"{int(minutes)} min " if hours or minutes else "") + f"{secs:.1f} s"
    return f"{text} {sign}"


def pick_run(log: Optional[Path], run_index: Optional[int]) -> Tuple[Path, run_report.Run]:
    """The log file and the run to sort by: the last run of the newest log with one, unless told otherwise."""
    if log is None:
        logs = run_report.run_logs()
        if not logs:
            raise SystemExit(f"No log with a run in {run_report.LOG_DIR}: give one with --log")
        log = logs[0]
    runs = run_report.read_log(log)
    if not runs:
        raise SystemExit(f"{log} has no run (no line 'Starting observation with script ...')")
    if run_index is None:
        return log, runs[-1]
    if not 1 <= run_index <= len(runs):
        raise SystemExit(f"{log} has {len(runs)} runs; --run must be 1 to {len(runs)}")
    return log, runs[run_index - 1]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sew_sort",
        description="Sort the images of an eclipse run into folders by the script line that took them "
                    "(phase, description, and one folder per bracket, HDR series or burst), ready for stacking.")
    parser.add_argument("images", type=Path, help="folder with the images (copied from the card, subfolders included)")
    parser.add_argument("output", type=Path, nargs="?", help="folder to sort into (default: <images>/sorted)")
    parser.add_argument("--log", type=Path, help="log file of the run (default: the newest log with a run in "
                                                 f"{run_report.LOG_DIR})")
    parser.add_argument("--run", type=int, help="which run of the log, 1 for the first (default: the last)")
    parser.add_argument("--list-runs", action="store_true", help="list the runs of the log and exit")
    parser.add_argument("--camera", action="append", help="camera name in the script the images are from "
                                                          "(repeat for several; default: from the camera model)")
    parser.add_argument("--clock-offset", type=parse_offset,
                        help="camera clock minus computer clock, in seconds or [-]hh:mm:ss "
                             "(default: found from the images)")
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE_S,
                        help=f"seconds an image may be outside the busy time of a command (default {DEFAULT_TOLERANCE_S})")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--move", action="store_true", help="move the images instead of copying them")
    action.add_argument("--link", action="store_true", help="hard-link the images (symbolic link across disks)")
    parser.add_argument("--skip-unmatched", action="store_true", help="leave images that match no command where they are")
    parser.add_argument("--no-exiftool", action="store_true", help="use the built-in metadata reader")
    parser.add_argument("-n", "--dry-run", action="store_true", help="only say what would be done")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    log, run = pick_run(args.log, args.run)
    if args.list_runs:
        for i, r in enumerate(run_report.read_log(log), start=1):
            shots = sum(1 for c in r.commands if c.func_name in SHOT_COMMANDS)
            print(f"{i}: {r.started:%Y-%m-%d %H:%M:%S} UTC  {Path(r.script).name}  "
                  f"({shots} shot commands; {r.simulation or 'not simulated'})")
        return 0

    paths = find_images(args.images)
    if not paths:
        print(f"No images in {args.images}", file=sys.stderr)
        return 1
    output = args.output or (args.images / "sorted")
    paths = [p for p in paths if output.resolve() not in p.resolve().parents]
    print(f"Run: {Path(run.script).name}, loaded {run.started:%Y-%m-%d %H:%M:%S} UTC ({log})")
    if run.simulation:
        print(f"     simulation: {run.simulation}")
    infos = read_image_infos(paths, use_exiftool=not args.no_exiftool)
    plan = plan_sorting(run, infos, args.camera, args.clock_offset, args.tolerance)
    print(format_summary(plan))
    if args.dry_run:
        return 0
    mode = "move" if args.move else "link" if args.link else "copy"
    warned = len(plan.warnings)
    manifest = apply_plan(plan, output, mode, include_unmatched=not args.skip_unmatched)
    for warning in plan.warnings[warned:]:
        print(f"Warning: {warning}", file=sys.stderr)
    print(f"{len(plan.matched)} images sorted into {output} ({mode}); see {manifest}")
    return 0 if len(plan.warnings) == warned else 1


if __name__ == "__main__":
    sys.exit(main())
