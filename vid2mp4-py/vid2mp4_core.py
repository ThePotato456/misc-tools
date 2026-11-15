"""vid2mp4 engine, shared by the command line tool (vid2mp4.py) and the GUI (vid2mp4_gui.py).

No printing and no UI in here: callers hand in a progress callback and a cancel event and get a Result back.
Requires ffmpeg and ffprobe on PATH.
"""

import json
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


def read_version() -> str:
    # VERSION sits next to the script, or inside the exe's bundle (PyInstaller --add-data).
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    try:
        return (base / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".flv", ".wmv", ".ts", ".mts", ".m2ts", ".3gp", ".ogv"}

# Settings a preset can set. None means "not set": the source is kept as it is.
#   crf, speed         x264 quality and speed preset
#   audio_bitrate      AAC kbps
#   audio_rate         resample to this Hz (None keeps the source rate)
#   audio_channels     downmix to this many channels (None keeps the source layout)
#   profile            x264 profile (None lets x264 choose)
BASE = dict(crf=23, speed="medium", audio_bitrate=192, audio_rate=None, audio_channels=None, profile=None)

# Each preset lists only what it changes. Several can be stacked (--preset mac,small): later ones win.
PRESETS = {
    "default": {},
    "mac": dict(crf=20, audio_rate=48000, audio_channels=2, profile="high"),  # QuickTime / Safari / iOS
    # Quality ladder, worst to best: lower CRF is better and bigger, slower speeds squeeze the file smaller.
    "low": dict(crf=32, speed="fast", audio_bitrate=96),           # fastest and tiniest, visibly soft
    "small": dict(crf=28, speed="slow", audio_bitrate=128),        # small file that still looks fine
    "medium": dict(crf=23, speed="medium", audio_bitrate=192),     # same as default
    "large": dict(crf=20, speed="slow", audio_bitrate=224),        # clearly better than medium
    "high": dict(crf=18, speed="slow", audio_bitrate=256),         # visually clean
    "ultra": dict(crf=16, speed="slower", audio_bitrate=320),      # very clean
    "max": dict(crf=14, speed="slower", audio_bitrate=320),        # near transparent, biggest files
}
SPEEDS = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"]


def resolve_presets(names: list[str]) -> dict:
    """Settings for a stack of preset names; later ones win. Raises ValueError for an unknown name."""
    cfg = dict(BASE)
    for name in names:
        if name not in PRESETS:
            raise ValueError(f"unknown preset {name!r} (choose from: {', '.join(PRESETS)})")
        cfg.update(PRESETS[name])
    return cfg


INTERLACED = {"tt", "bb", "tb", "bt"}
HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}

# Windowed exes have no console: give child processes no stdin and no console window of their own.
_SUBPROCESS = {"stdin": subprocess.DEVNULL}
if sys.platform == "win32":
    _SUBPROCESS["creationflags"] = subprocess.CREATE_NO_WINDOW


def find_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"{name} not found on PATH")
    return path


def probe(ffprobe: str, src: Path) -> dict:
    """First video and first audio stream of src, as ffprobe reports them, plus the duration in seconds (or None)."""
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(src)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", **_SUBPROCESS,
    )
    if out.returncode != 0:
        lines = out.stderr.strip().splitlines()
        raise RuntimeError(f"cannot read file: {lines[-1] if lines else 'unknown error'}")
    data = json.loads(out.stdout)
    streams = data.get("streams", [])
    pick = lambda kind: next((s for s in streams if s.get("codec_type") == kind), None)  # noqa: E731
    video = pick("video")
    duration = None
    for raw in (data.get("format", {}).get("duration"), (video or {}).get("duration")):
        try:
            if raw and float(raw) > 0:
                duration = float(raw)
                break
        except ValueError:
            pass
    return {"video": video, "audio": pick("audio"), "subtitles": sum(s.get("codec_type") == "subtitle" for s in streams),
            "audio_tracks": sum(s.get("codec_type") == "audio" for s in streams), "duration": duration}


def can_copy_video(v: dict) -> bool:
    # 8-bit 4:2:0 H.264 only: High 10 and 4:4:4 H.264 do not play in QuickTime or most hardware decoders.
    return v.get("codec_name") == "h264" and v.get("pix_fmt") == "yuv420p"


def can_copy_audio(a: dict, cfg: dict) -> bool:
    if a.get("codec_name") != "aac" or a.get("profile", "LC") != "LC":
        return False
    if cfg["audio_rate"] and int(a.get("sample_rate", 0)) != cfg["audio_rate"]:
        return False
    if cfg["audio_channels"] and int(a.get("channels", 0)) != cfg["audio_channels"]:
        return False
    return True


GPU_ENCODERS = ("h264_nvenc", "h264_qsv", "h264_amf")  # NVIDIA, Intel, AMD
# x264 speed preset -> NVENC preset (p1 fastest .. p7 slowest)
NVENC_PRESETS = {"ultrafast": "p1", "superfast": "p1", "veryfast": "p2", "faster": "p3", "fast": "p4",
                 "medium": "p5", "slow": "p6", "slower": "p7", "veryslow": "p7"}


def detect_gpu_encoder(ffmpeg: str) -> str | None:
    """First hardware H.264 encoder this ffmpeg build lists AND can actually open, or None."""
    listed = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, encoding="utf-8", errors="replace", **_SUBPROCESS).stdout
    for enc in GPU_ENCODERS:
        if enc not in listed:
            continue
        test = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.1",
             "-c:v", enc, "-f", "null", "-"],
            capture_output=True, **_SUBPROCESS,
        )
        if test.returncode == 0:
            return enc
    return None


def gpu_video_args(enc: str, cfg: dict) -> list[str]:
    q = str(cfg["crf"])
    if enc == "h264_nvenc":
        return ["-c:v", enc, "-preset", NVENC_PRESETS[cfg["speed"]], "-rc", "vbr", "-cq", q, "-b:v", "0"]
    if enc == "h264_qsv":
        return ["-c:v", enc, "-global_quality", q]
    return ["-c:v", enc, "-rc", "cqp", "-qp_i", q, "-qp_p", q]  # h264_amf


def build_command(ffmpeg: str, src: Path, info: dict, cfg: dict, copy: bool,
                  gpu: str | None = None) -> tuple[list[str], list[str]]:
    """Return (ffmpeg command, notes about what it does). Progress is machine-readable on stdout (-progress)."""
    v, a = info["video"], info["audio"]
    notes = []
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1", "-y", "-threads", "0",
           "-i", str(src), "-map", "0:v:0"]
    if a:
        cmd += ["-map", "0:a:0"]

    if copy and can_copy_video(v):
        cmd += ["-c:v", "copy"]
        notes.append("video copied")
    else:
        filters = []
        if v.get("field_order") in INTERLACED:
            filters.append("yadif")
            notes.append("deinterlaced")
        if int(v.get("width", 0)) % 2 or int(v.get("height", 0)) % 2:
            filters.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")  # yuv420p needs even dimensions
            notes.append("size rounded to even")
        if gpu:
            cmd += gpu_video_args(gpu, cfg)
        else:
            cmd += ["-c:v", "libx264", "-preset", cfg["speed"], "-crf", str(cfg["crf"])]
        cmd += ["-pix_fmt", "yuv420p"]
        if cfg["profile"]:
            cmd += ["-profile:v", cfg["profile"]]
        if filters:
            cmd += ["-vf", ",".join(filters)]
        notes.append(f"H.264 {gpu} crf {cfg['crf']}" if gpu else f"H.264 crf {cfg['crf']}")

    if a:
        if copy and can_copy_audio(a, cfg):
            cmd += ["-c:a", "copy"]
            notes.append("audio copied")
        else:
            cmd += ["-c:a", "aac", "-b:a", f"{cfg['audio_bitrate']}k"]
            if cfg["audio_rate"]:
                cmd += ["-ar", str(cfg["audio_rate"])]
            if cfg["audio_channels"]:
                cmd += ["-ac", str(cfg["audio_channels"])]
            notes.append(f"audio AAC {cfg['audio_bitrate']}k")
    return cmd, notes


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def human_time(s: float) -> str:
    m, s = divmod(int(s), 60)
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s" if m else f"{s}s"


class Cancelled(Exception):
    """The cancel event was set while converting."""


@dataclass
class Result:
    src: Path
    status: str                      # "done" or "skipped"
    dest: Path | None = None
    message: str = ""                # why it was skipped
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    before: int = 0                  # source size in bytes
    after: int = 0                   # output size in bytes
    elapsed: float = 0.0

    @property
    def change(self) -> float:
        """Output size relative to the source in percent: negative = smaller."""
        return (self.after / self.before - 1) * 100 if self.before else 0.0


PROGRESS_LINE = re.compile(r"^[A-Za-z_0-9]+=")

# on_progress(seconds_done, duration_or_None, speed_text) is called about twice a second, and once at the start.
ProgressCallback = Callable[[float, "float | None", str], None]


def convert(src: Path, out_dir: Path | None, overwrite: bool, cfg: dict, copy: bool, gpu: str | None = None,
            on_progress: ProgressCallback | None = None, cancel: threading.Event | None = None) -> Result:
    """Convert one video to MP4. Raises RuntimeError on failure and Cancelled if `cancel` gets set."""
    dest = (out_dir or src.parent) / (src.stem + ".mp4")
    if dest.resolve() == src.resolve():
        return Result(src, "skipped", message="output would overwrite the source (pick an output folder)")
    if dest.exists() and not overwrite:
        return Result(src, "skipped", dest, message="output already exists")

    ffmpeg, ffprobe = find_tool("ffmpeg"), find_tool("ffprobe")
    info = probe(ffprobe, src)
    if not info["video"]:
        raise RuntimeError("no video stream")
    warnings = []
    if info["video"].get("color_transfer") in HDR_TRANSFERS:
        warnings.append("HDR source: converting to 8-bit SDR without tone mapping will look washed out")

    cmd, notes = build_command(ffmpeg, src, info, cfg, copy, gpu)
    if info["audio_tracks"] > 1:
        notes.append(f"dropped {info['audio_tracks'] - 1} extra audio track(s)")
    if info["subtitles"]:
        notes.append(f"dropped {info['subtitles']} subtitle track(s)")

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.stem + ".part.mp4")
    duration = info["duration"]
    started = time.monotonic()
    if on_progress:
        on_progress(0.0, duration, "")
    proc = subprocess.Popen([*cmd, "-movflags", "+faststart", str(tmp)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", **_SUBPROCESS)
    errors: list[str] = []
    speed = ""
    try:
        for line in proc.stdout:
            line = line.strip()
            if cancel is not None and cancel.is_set():
                raise Cancelled
            if not PROGRESS_LINE.match(line):
                if line:
                    errors.append(line)  # ffmpeg error text
                continue
            key, _, val = line.partition("=")
            if key in ("out_time_us", "out_time_ms") and val.isdigit():
                done = int(val) / 1_000_000
                if on_progress:
                    on_progress(min(done, duration) if duration else done, duration, speed)
            elif key == "speed" and val not in ("", "N/A"):
                speed = val
        if proc.wait() != 0:
            raise RuntimeError(errors[-1] if errors else f"ffmpeg exited with code {proc.returncode}")
        tmp.replace(dest)
    except BaseException:
        proc.kill()
        proc.wait()
        tmp.unlink(missing_ok=True)
        raise
    return Result(src, "done", dest, notes=notes, warnings=warnings, before=src.stat().st_size,
                  after=dest.stat().st_size, elapsed=time.monotonic() - started)


def is_video(p: Path) -> bool:
    return p.suffix.lower() in VIDEO_EXTS


def collect(paths: list[str | Path], recursive: bool) -> tuple[list[Path], list[str]]:
    """Video files under the given files and folders, plus problems worth telling the user about."""
    files, problems = [], []
    for p in map(Path, paths):
        if p.is_dir():
            pattern = "**/*" if recursive else "*"
            files += sorted(f for f in p.glob(pattern) if is_video(f) and f.is_file())
        elif p.is_file():
            if is_video(p):
                files.append(p)
            else:
                problems.append(f"skip (not a video): {p}")
        else:
            problems.append(f"not found: {p}")
    return files, problems
