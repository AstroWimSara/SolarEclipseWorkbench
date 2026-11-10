"""Align the frames of an eclipse timelapse on the sun (Issue #70).

Even with a tracking mount, the sun wanders through the frames of a timelapse
of an eclipse: polar alignment, a mount that tracks at the sidereal rate, or no
mount at all.  This puts the centre of the sun in the middle of every frame and
crops the frames to the same size, so the moon is seen to move over a sun that
stands still.  A video is made from them with ffmpeg, when it is installed.

The centre of the sun is found with sun_finder: a circle fitted to the sun's own
limb, so a crescent is centred on the sun and not on its bright part.  During
totality there is no limb: the centre is interpolated in time between the last
frame before and the first frame after, and frames at the start or end without
a sun get the centre of the nearest frame that has one.

    sew_align sorted/1_C1-C2/partial out/ --video eclipse.mp4

Frames are read with Pillow (JPEG, PNG, TIFF), and raw files with rawpy (installed
with Solar Eclipse Workbench, except on Intel Macs, for which rawpy has no build).
ffmpeg comes with the imageio-ffmpeg package when it is not installed on the system.  The output frames have 8 bits per channel.
``alignment.csv`` lists the centre that was found or interpolated for every frame.
"""

import argparse
import csv
import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Sequence

import numpy as np
from PIL import Image

from solareclipseworkbench.image_sorter import IMAGE_EXTENSIONS, find_images, read_image_infos
from solareclipseworkbench.sun_finder import find_sun, sun_channel

LOGGER = logging.getLogger(__name__)

RAW_EXTENSIONS = IMAGE_EXTENSIONS - {".jpg", ".jpeg", ".tif", ".tiff", ".png", ".heic", ".heif", ".hif"}

#: Half the side of the crop, in radii of the sun: room for the inner corona
DEFAULT_MARGIN = 2.5


def load_frame(path: Path) -> np.ndarray:
    """An image as an 8-bit RGB array (height × width × 3)."""
    if path.suffix.lower() in RAW_EXTENSIONS:
        try:
            import rawpy
        except ImportError as error:
            raise RuntimeError(f"{path.name}: reading raw files needs rawpy, which is not available on this "
                               "computer (there is none for Intel Macs): convert the raw files to TIFF or JPEG "
                               "first") from error
        with rawpy.imread(str(path)) as raw:
            return raw.postprocess(output_bps=8, use_camera_wb=True, no_auto_bright=True)
    with Image.open(path) as image:
        if image.mode in ("I;16", "I;16B", "I;16L", "I"):
            data = np.asarray(image, dtype=np.float64)
            top = 65535.0 if image.mode.startswith("I;16") else max(1.0, float(data.max()))
            grey = np.clip(data / top * 255.0, 0, 255).astype(np.uint8)
            return np.stack([grey] * 3, axis=2)
        return np.asarray(image.convert("RGB"))


@dataclass
class Frame:
    path: Path
    taken: Optional[datetime]
    x: Optional[float] = None
    y: Optional[float] = None
    radius: Optional[float] = None
    found: bool = False
    width: int = 0
    height: int = 0


def locate(frames: Sequence[Frame], loader=load_frame,
           progress: Optional[Callable[[int, int, str], None]] = None) -> None:
    """Find the sun in every frame; a second pass with the radius known catches thin crescents.

    progress(done, total, what) is called before every frame, and may raise to stop.
    """
    for number, frame in enumerate(frames):
        if progress is not None:
            progress(number, len(frames), "Finding the sun")
        _find(frame, loader, None)
    radii = [f.radius for f in frames if f.found]
    if not radii:
        return
    hint = float(np.median(radii))
    again = [f for f in frames if not f.found or abs(f.radius - hint) > 0.08 * hint]
    for number, frame in enumerate(again):
        if progress is not None:
            progress(number, len(again), "Looking again with the size of the sun known")
        _find(frame, loader, hint)
    _fill_gaps(frames)


def _find(frame: Frame, loader, radius_hint: Optional[float]) -> None:
    try:
        image = loader(frame.path)
    except (OSError, RuntimeError, ValueError) as error:
        LOGGER.warning("%s: %s", frame.path.name, error)
        return
    frame.height, frame.width = image.shape[:2]
    fix = find_sun(sun_channel(image), radius_hint=radius_hint)
    if fix is not None:
        frame.x, frame.y, frame.radius, frame.found = fix.x, fix.y, fix.radius, True
    elif radius_hint is not None and frame.found and abs(frame.radius - radius_hint) > 0.08 * radius_hint:
        frame.found = False         # a circle of the wrong size, and none of the right one


def _fill_gaps(frames: Sequence[Frame]) -> None:
    """Interpolate the centre in time (or in frame number) for the frames without a sun: totality, clouds."""
    known = [i for i, f in enumerate(frames) if f.found]
    if not known:
        return
    use_time = all(f.taken is not None for f in frames)

    def position(i: int) -> float:
        return frames[i].taken.timestamp() if use_time else float(i)

    xs = np.array([frames[i].x for i in known])
    ys = np.array([frames[i].y for i in known])
    at = np.array([position(i) for i in known])
    radius = float(np.median([frames[i].radius for i in known]))
    for i, frame in enumerate(frames):
        if frame.found:
            continue
        frame.x = float(np.interp(position(i), at, xs))      # the nearest known one outside the range
        frame.y = float(np.interp(position(i), at, ys))
        frame.radius = radius


def crop_centred(image: np.ndarray, cx: float, cy: float, half: int) -> np.ndarray:
    """A square of 2·half pixels around (cx, cy), bilinear to a fraction of a pixel; black outside the frame.

    Pixel (i, j) has its centre at x = i, y = j, as in sun_finder; (cx, cy) lands
    between the two middle pixels of the crop.
    """
    size = 2 * half
    xs = cx - half + 0.5 + np.arange(size)
    ys = cy - half + 0.5 + np.arange(size)
    x0 = np.floor(xs).astype(int)
    y0 = np.floor(ys).astype(int)
    fx = (xs - x0)[None, :, None]
    fy = (ys - y0)[:, None, None]
    h, w = image.shape[:2]
    img = image if image.ndim == 3 else image[..., None]
    # One pixel of black around the frame, so samples just outside it fade to black
    padded = np.zeros((h + 2, w + 2, img.shape[2]), dtype=np.float32)
    padded[1:-1, 1:-1] = img
    xi = np.clip(x0 + 1, 0, w + 1)
    xj = np.clip(x0 + 2, 0, w + 1)
    yi = np.clip(y0 + 1, 0, h + 1)
    yj = np.clip(y0 + 2, 0, h + 1)
    out = ((1 - fy) * ((1 - fx) * padded[np.ix_(yi, xi)] + fx * padded[np.ix_(yi, xj)])
           + fy * ((1 - fx) * padded[np.ix_(yj, xi)] + fx * padded[np.ix_(yj, xj)]))
    out = np.clip(np.rint(out), 0, 255).astype(np.uint8)
    return out if image.ndim == 3 else out[..., 0]


def order_frames(paths: Sequence[Path]) -> List[Frame]:
    """The frames in the order they were taken (capture time, then file name)."""
    infos = read_image_infos(list(paths))
    frames = [Frame(info.path, info.taken) for info in infos]
    frames.sort(key=lambda f: (f.taken is None, f.taken or datetime.min, f.path.name))
    return frames


def write_frames(frames: Sequence[Frame], out_dir: Path, half: int, suffix: str = ".png",
                 loader=load_frame, progress: Optional[Callable[[int, int, str], None]] = None) -> List[Path]:
    """The aligned frames, numbered from 00001 in the order of frames, and alignment.csv."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    rows = []
    for number, frame in enumerate(frames, start=1):
        if progress is not None:
            progress(number - 1, len(frames), "Writing the aligned frames")
        target = out_dir / f"frame_{number:05d}{suffix}"
        row = {"frame": target.name, "source": str(frame.path),
               "capture_time": frame.taken.isoformat(timespec="milliseconds") if frame.taken else "",
               "x": "", "y": "", "radius": "", "centre": "no sun in any frame"}
        if frame.x is not None:
            image = loader(frame.path)
            Image.fromarray(crop_centred(image, frame.x, frame.y, half)).save(
                target, **({"quality": 95} if suffix in (".jpg", ".jpeg") else {}))
            written.append(target)
            row.update(x=f"{frame.x:.2f}", y=f"{frame.y:.2f}", radius=f"{frame.radius:.2f}",
                       centre="found" if frame.found else "interpolated")
        rows.append(row)
    with open(out_dir / "alignment.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["frame"])
        writer.writeheader()
        writer.writerows(rows)
    return written


def ffmpeg_path() -> Optional[str]:
    """ffmpeg on the PATH, else the one that comes with the imageio-ffmpeg package; None when there is neither."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return None


def make_video(frames_dir: Path, video: Path, fps: float, suffix: str = ".png") -> bool:
    """An H.264 video of the aligned frames with ffmpeg; False when there is no ffmpeg."""
    ffmpeg = ffmpeg_path()
    if ffmpeg is None:
        return False
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-framerate", str(fps),
                    "-i", str(frames_dir / f"frame_%05d{suffix}"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                    str(video)], check=True)
    return True


class AlignError(Exception):
    """Nothing to align: no images, or no sun in any of them."""


def align_folder(folder: Path, output: Path, size: Optional[int] = None, fmt: str = "png",
                 video: Optional[Path] = None, fps: float = 12.0, recursive: bool = True,
                 progress: Optional[Callable[[int, int, str], None]] = None,
                 report: Callable[[str], None] = print) -> List[Path]:
    """Align the frames in a folder into output (see the module); returns the frames written.

    report(text) is told what happens, a line at a time.  Raises AlignError when there is nothing to align on.
    """
    folder, output = Path(folder), Path(output)
    paths = find_images(folder, recursive=recursive)
    if output.resolve() != folder.resolve():
        paths = [p for p in paths if output.resolve() not in p.resolve().parents]
    if not paths:
        raise AlignError(f"No images in {folder}")
    frames = order_frames(paths)
    report(f"Finding the sun in {len(frames)} frames ...")
    locate(frames, progress=progress)
    found = [f for f in frames if f.found]
    if not found:
        raise AlignError("The sun was not found in any frame: nothing to align on")
    radius = float(np.median([f.radius for f in found]))
    half = size // 2 if size else int(round(DEFAULT_MARGIN * radius))
    report(f"Sun found in {len(found)} of {len(frames)} frames (radius {radius:.1f} px); "
           f"{len(frames) - len(found)} centred by interpolation.  Frames of {2 * half} × {2 * half} px")
    suffix = "." + fmt
    written = write_frames(frames, output, half, suffix, progress=progress)
    report(f"{len(written)} aligned frames in {output}")
    if video:
        if progress is not None:
            progress(0, 1, "Making the video")
        if make_video(output, Path(video), fps, suffix):
            report(f"Video: {video}")
        else:
            report("No ffmpeg found: no video made")
    return written


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sew_align",
        description="Align the frames of an eclipse timelapse on the centre of the sun, crop them to the same "
                    "size and optionally make a video (Issue #70).")
    parser.add_argument("frames", type=Path, help="folder with the frames (e.g. a folder made by sew_sort)")
    parser.add_argument("output", type=Path, help="folder for the aligned frames")
    parser.add_argument("--size", type=int, help="side of the aligned frames in pixels "
                                                 f"(default: {2 * DEFAULT_MARGIN:g} diameters of the sun)")
    parser.add_argument("--format", choices=("png", "jpg", "tif"), default="png", help="format of the frames")
    parser.add_argument("--video", type=Path, help="also make this video (needs ffmpeg)")
    parser.add_argument("--fps", type=float, default=12.0, help="frames per second of the video (default 12)")
    parser.add_argument("--no-recursive", action="store_true", help="leave out the subfolders")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    try:
        align_folder(args.frames, args.output, args.size, args.format, args.video, args.fps,
                     recursive=not args.no_recursive)
    except AlignError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
