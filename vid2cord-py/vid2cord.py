"""Re-encode a video so it fits Discord's upload size limit.

Usage:
    vid2cord video.mp4             # single file -> video_discord.mp4
    vid2cord some_folder           # every video in the folder
    vid2cord some_folder -r        # recurse into subfolders
    vid2cord video.mp4 -s 10       # target 10 MB instead of 20

Requires ffmpeg and ffprobe on PATH.

Drag and drop video files or folders onto vid2cord.exe to process them.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

def read_version() -> str:
    # VERSION sits next to the script, or inside the exe's bundle (PyInstaller --add-data).
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    try:
        return (base / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".flv", ".wmv", ".ts"}
SUFFIX = "_discord"
SAFETY = 0.93  # aim below the limit; container overhead and rate control drift
MAX_ATTEMPTS = 4
MIN_VIDEO_KBPS = 50


def find_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"{name} not found on PATH")
    return path


def probe_duration(ffprobe: str, src: Path) -> float:
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(src)],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        raise RuntimeError(f"cannot read duration: {out.stderr.strip() or 'unknown error'}")


def max_height(video_kbps: float) -> int | None:
    """Downscale when bitrate is too low to keep a big frame clean."""
    if video_kbps < 400:
        return 360
    if video_kbps < 1000:
        return 480
    if video_kbps < 2500:
        return 720
    return None


def encode(ffmpeg: str, src: Path, dest: Path, video_kbps: int, audio_kbps: int, workdir: Path) -> None:
    height = max_height(video_kbps)
    vf = ["-vf", f"scale=-2:min(ih\\,{height})"] if height else []
    base = [ffmpeg, "-hide_banner", "-loglevel", "error", "-stats", "-y", "-i", str(src),
            "-map", "0:v:0", *vf, "-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p",
            "-b:v", f"{video_kbps}k", "-passlogfile", str(workdir / "pass")]
    subprocess.run([*base, "-pass", "1", "-an", "-f", "null", os.devnull], check=True)
    subprocess.run([*base, "-pass", "2", "-map", "0:a:0?", "-c:a", "aac", "-b:a", f"{audio_kbps}k",
                    "-movflags", "+faststart", str(dest)], check=True)


def process(src: Path, out_dir: Path | None, overwrite: bool, size_mb: float) -> bool:
    """Re-encode one video to fit size_mb. Return True if a file was written."""
    dest = (out_dir or src.parent) / (src.stem + SUFFIX + ".mp4")
    limit = int(size_mb * 1024 * 1024)
    if dest.exists() and not overwrite:
        print(f"skip (exists): {dest}")
        return False
    if src.stat().st_size <= limit:
        print(f"skip (already fits): {src}")
        return False

    ffmpeg, ffprobe = find_tool("ffmpeg"), find_tool("ffprobe")
    duration = probe_duration(ffprobe, src)
    total_kbps = limit * 8 * SAFETY / duration / 1000
    audio_kbps = 128 if total_kbps >= 400 else 64
    video_kbps = int(total_kbps - audio_kbps)

    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if video_kbps < MIN_VIDEO_KBPS:
                raise RuntimeError(f"video too long ({duration:.0f}s) to fit {size_mb:g} MB")
            print(f"{src} (attempt {attempt}: {video_kbps}k video + {audio_kbps}k audio)")
            encode(ffmpeg, src, dest, video_kbps, audio_kbps, Path(tmp))
            size = dest.stat().st_size
            if size <= limit:
                print(f"{src} -> {dest} ({size / 1024 / 1024:.2f} MB)")
                return True
            video_kbps = int(video_kbps * limit / size * SAFETY)
    dest.unlink(missing_ok=True)
    raise RuntimeError(f"could not fit under {size_mb:g} MB after {MAX_ATTEMPTS} attempts")


def is_video(p: Path) -> bool:
    return p.suffix.lower() in VIDEO_EXTS


def collect(paths: list[str], recursive: bool) -> list[Path]:
    files = []
    for p in map(Path, paths):
        if p.is_dir():
            pattern = "**/*" if recursive else "*"
            files += [f for f in p.glob(pattern) if is_video(f) and f.is_file()]
        elif p.is_file():
            if is_video(p):
                files.append(p)
            else:
                print(f"skip (not a video): {p}", file=sys.stderr)
        else:
            print(f"not found: {p}", file=sys.stderr)
    return files


def owns_console() -> bool:
    """True if this process created its own console window (double-click or
    drag-and-drop), meaning the window closes as soon as we exit."""
    if sys.platform != "win32":
        return False
    import ctypes

    pids = (ctypes.c_uint * 2)()
    return ctypes.windll.kernel32.GetConsoleProcessList(pids, 2) <= 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Re-encode videos to fit Discord's file size limit. Drop files or folders onto the exe."
    )
    ap.add_argument("paths", nargs="*", help="video files and/or folders")
    ap.add_argument("-o", "--out", type=Path, help="output folder (default: next to each source)")
    ap.add_argument("-r", "--recursive", action="store_true", help="search folders recursively")
    ap.add_argument("-s", "--size", type=float, default=20, metavar="MB",
                    help="target size limit in MB (default: 20)")
    ap.add_argument("-f", "--force", action="store_true", help="overwrite existing outputs")
    ap.add_argument("-V", "--version", action="version", version=f"%(prog)s {read_version()}")
    args = ap.parse_args()

    if not args.paths:
        ap.print_help()
        return 2

    if args.size <= 0:
        ap.error("--size must be positive")

    files = collect(args.paths, args.recursive)
    if not files:
        print("no video files found", file=sys.stderr)
        return 1

    done = failed = 0
    for f in files:
        try:
            done += process(f, args.out, args.force, args.size)
        except Exception as e:
            failed += 1
            print(f"error: {f}: {e}", file=sys.stderr)

    print(f"processed {done}, failed {failed}, total {len(files)}")
    return 1 if failed else 0


if __name__ == "__main__":
    # Dropped files open a console that vanishes on exit; keep it up to read results.
    code = main()
    if owns_console():
        input("\nPress Enter to close...")
    sys.exit(code)
