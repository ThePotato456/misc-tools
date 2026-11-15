"""Quick video encoder: convert videos to MP4 (H.264 + AAC) with sensible defaults and presets.

Usage:
    vid2mp4 video.mkv                  # single file -> video.mp4
    vid2mp4 some_folder -r             # every video under a folder
    vid2mp4 video.mkv --preset mac     # macOS / QuickTime / iOS compatible output
    vid2mp4 video.mkv -p mac,small     # presets stack: Mac-compatible and small
    vid2mp4 video.mkv --crf 18 --speed slow --audio-bitrate 256
    vid2mp4 video.mkv --cpu            # x264 on the CPU instead of the GPU (smaller files, slower)

Streams that already fit the target are copied instead of re-encoded, so those conversions are fast and lossless.
Any option you pass overrides the preset. The GPU (NVENC, Quick Sync or AMF) is used when available.

Requires ffmpeg and ffprobe on PATH. The window version of this tool is vid2mp4-gui.

Drag and drop video files or folders onto vid2mp4.exe to process them.
"""

import argparse
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.table import Table
from rich.text import Text

import vid2mp4_core as core

console = Console(highlight=False)
STOP = threading.Event()  # set on Ctrl+C so worker threads kill their ffmpeg
UNICODE = (console.encoding or "").lower().startswith("utf")
OK, BAD, ARROW, ELLIPSIS = ("✓", "✗", "→", "…") if UNICODE else ("+", "x", "->", "~")


def parse_presets(text: str) -> dict:
    try:
        return core.resolve_presets(text.split(","))
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e))


def shorten(name: str, width: int = 38) -> str:
    return name if len(name) <= width else name[: width - 1] + ELLIPSIS


def process(src: Path, out_dir: Path | None, overwrite: bool, cfg: dict, copy: bool,
            gpu: str | None, progress: Progress) -> bool:
    """Convert one video to MP4 with a live progress row. Return True if a file was written."""
    task = None

    def on_progress(done: float, duration: float | None, speed: str) -> None:
        nonlocal task
        if task is None:
            task = progress.add_task("", total=duration, name=shorten(src.name), speed="")
        progress.update(task, completed=done, speed=speed)

    try:
        res = core.convert(src, out_dir, overwrite, cfg, copy, gpu, on_progress, STOP)
    finally:
        if task is not None:
            progress.remove_task(task)

    if res.status == "skipped":
        progress.console.print(Text(f"- skip {src.name} ({res.message})", style="yellow"))
        return False
    for warning in res.warnings:
        progress.console.print(Text(f"! {src.name}: {warning}", style="yellow"))
    line = Text()
    line.append(f"{OK} ", style="bold green")
    line.append(src.name, style="bold")
    line.append(f"  {core.human_size(res.before)} {ARROW} {core.human_size(res.after)} ", style="cyan")
    line.append(f"({res.change:+.0f}%)", style="green" if res.change <= 0 else "red")
    line.append(f"  {core.human_time(res.elapsed)}", style="magenta")
    line.append(f"  {', '.join(res.notes)}", style="dim")
    progress.console.print(line)
    return True


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
        description="Quick video encoder: convert videos to MP4 (H.264 + AAC). Drop files or folders onto the exe.",
        epilog="presets: default | mac (crf 20, High profile, AAC 48 kHz stereo) | low | small | medium | large | high | ultra | max "
               "(quality ladder, crf 32 down to 14). Stack with commas (mac,small); later ones win. "
               "Other options override the presets.",
    )
    ap.add_argument("paths", nargs="*", help="video files and/or folders")
    ap.add_argument("-p", "--preset", type=parse_presets, default=dict(core.BASE), metavar="NAME[,NAME]",
                    help="settings bundle: " + ", ".join(core.PRESETS) + " (default: default)")
    ap.add_argument("-o", "--out", type=Path, help="output folder (default: next to each source)")
    ap.add_argument("-r", "--recursive", action="store_true", help="search folders recursively")
    ap.add_argument("-q", "--crf", type=int, metavar="CRF", help="x264 quality, 0-51, lower is better")
    ap.add_argument("--speed", choices=core.SPEEDS, help="x264 speed preset: slower is smaller")
    ap.add_argument("--audio-bitrate", type=int, metavar="KBPS", help="AAC bitrate in kbps")
    ap.add_argument("--no-copy", action="store_true", help="always re-encode, never copy streams")
    ap.add_argument("-f", "--force", action="store_true", help="overwrite existing outputs")
    ap.add_argument("-j", "--jobs", type=int, default=1, metavar="N",
                    help="convert N files at once (0 = one per 4 CPU cores); x264 already uses all cores for one file, "
                         "so this mainly helps with many small files")
    ap.add_argument("--cpu", action="store_true",
                    help="encode on the CPU (x264) instead of the GPU: slower, but smaller files at the same quality "
                         "(default: GPU via NVENC, Quick Sync or AMF when available)")
    ap.add_argument("-V", "--version", action="version", version=f"%(prog)s {core.read_version()}")
    args = ap.parse_args()

    if not args.paths:
        ap.print_help()
        return 2

    cfg = dict(args.preset)
    for key, val in (("crf", args.crf), ("speed", args.speed), ("audio_bitrate", args.audio_bitrate)):
        if val is not None:
            cfg[key] = val
    if not 0 <= cfg["crf"] <= 51:
        ap.error("--crf must be between 0 and 51")
    if cfg["audio_bitrate"] <= 0:
        ap.error("--audio-bitrate must be positive")

    files, problems = core.collect(args.paths, args.recursive)
    for problem in problems:
        console.print(Text(problem, style="red" if problem.startswith("not found") else "yellow"))
    if not files:
        console.print(Text("no video files found", style="red"))
        return 1

    if args.jobs < 0:
        ap.error("--jobs must be 0 or more")
    jobs = min(args.jobs or max(1, (os.cpu_count() or 4) // 4), len(files))

    gpu = None
    if not args.cpu:
        try:
            gpu = core.detect_gpu_encoder(core.find_tool("ffmpeg"))
        except RuntimeError as e:
            console.print(Text(f"error: {e}", style="bold red"))
            return 1

    header = Text()
    header.append(f"vid2mp4 {core.read_version()}", style="bold cyan")
    header.append(f"  {len(files)} file{'s' if len(files) != 1 else ''}", style="bold")
    header.append(f"  encoder: {gpu or 'x264 (CPU)'}", style="green" if gpu else "yellow")
    if jobs > 1:
        header.append(f"  jobs: {jobs}", style="dim")
    if not gpu and not args.cpu:
        header.append("  (no GPU encoder found)", style="dim")
    console.print(header)
    console.print()

    done = failed = skipped = 0
    started = time.monotonic()
    columns = [
        SpinnerColumn(),
        TextColumn("[bold]{task.fields[name]}"),
        BarColumn(bar_width=None),
        TaskProgressColumn(),
        TextColumn("[cyan]{task.fields[speed]}"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
    ]
    with Progress(*columns, console=console, transient=True) as progress:
        overall = progress.add_task("", total=len(files), name="Total", speed="") if len(files) > 1 else None

        def run(f: Path) -> bool:
            try:
                return process(f, args.out, args.force, cfg, not args.no_copy, gpu, progress)
            finally:
                if overall is not None:
                    progress.advance(overall)

        pool = ThreadPoolExecutor(max_workers=jobs)
        try:
            futures = {pool.submit(run, f): f for f in files}
            for fut in as_completed(futures):
                f = futures[fut]
                try:
                    if fut.result():
                        done += 1
                    else:
                        skipped += 1
                except Exception as e:
                    failed += 1
                    progress.console.print(Text(f"{BAD} {f.name}: {e}", style="bold red"))
        except KeyboardInterrupt:
            STOP.set()
            pool.shutdown(wait=True, cancel_futures=True)
            progress.stop()
            console.print(Text("cancelled", style="bold yellow"))
            return 130
        pool.shutdown()

    console.print()
    summary = Table.grid(padding=(0, 2))
    summary.add_row(Text(f"{done} converted", style="bold green"),
                    Text(f"{skipped} skipped", style="yellow") if skipped else Text(""),
                    Text(f"{failed} failed", style="bold red") if failed else Text(""),
                    Text(f"in {core.human_time(time.monotonic() - started)}", style="magenta"))
    console.print(summary)
    return 1 if failed else 0


if __name__ == "__main__":
    # Dropped files open a console that vanishes on exit; keep it up to read results.
    code = main()
    if owns_console():
        input("\nPress Enter to close...")
    sys.exit(code)
