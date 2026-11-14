"""Convert WebP images to PNG.

Usage:
    webp2png image.webp            # single file -> image.png
    webp2png some_folder           # every .webp in the folder
    webp2png some_folder -r        # recurse into subfolders
    webp2png a.webp b.webp -o out  # write PNGs into ./out

Drag and drop .webp files or folders onto webp2png.exe to convert them.
"""

import argparse
import sys
from pathlib import Path

from PIL import Image

def read_version() -> str:
    # VERSION sits next to the script, or inside the exe's bundle (PyInstaller --add-data).
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    try:
        return (base / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def convert(src: Path, out_dir: Path | None, overwrite: bool) -> bool:
    dest = (out_dir or src.parent) / (src.stem + ".png")
    if dest.exists() and not overwrite:
        print(f"skip (exists): {dest}")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        # Animated WebP: PNG keeps only the first frame.
        mode = "RGBA" if im.mode in ("RGBA", "LA", "P") or "transparency" in im.info else "RGB"
        im.convert(mode).save(dest, "PNG")
    print(f"{src} -> {dest}")
    return True


def is_webp(p: Path) -> bool:
    return p.suffix.lower() == ".webp"


def collect(paths: list[str], recursive: bool) -> list[Path]:
    files = []
    for p in map(Path, paths):
        if p.is_dir():
            pattern = "**/*" if recursive else "*"
            files += [f for f in p.glob(pattern) if is_webp(f) and f.is_file()]
        elif p.is_file():
            if is_webp(p):
                files.append(p)
            else:
                print(f"skip (not .webp): {p}", file=sys.stderr)
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
        description="Convert WebP images to PNG. Drop files or folders onto the exe to convert them."
    )
    ap.add_argument("paths", nargs="*", help="WebP files and/or folders")
    ap.add_argument("-o", "--out", type=Path, help="output folder (default: next to each source)")
    ap.add_argument("-r", "--recursive", action="store_true", help="search folders recursively")
    ap.add_argument("-f", "--force", action="store_true", help="overwrite existing PNGs")
    ap.add_argument("-V", "--version", action="version", version=f"%(prog)s {read_version()}")
    args = ap.parse_args()

    if not args.paths:
        ap.print_help()
        return 2

    files = collect(args.paths, args.recursive)
    if not files:
        print("no .webp files found", file=sys.stderr)
        return 1

    done = failed = 0
    for f in files:
        try:
            done += convert(f, args.out, args.force)
        except Exception as e:
            failed += 1
            print(f"error: {f}: {e}", file=sys.stderr)

    print(f"converted {done}, failed {failed}, total {len(files)}")
    return 1 if failed else 0


if __name__ == "__main__":
    # Dropped files open a console that vanishes on exit; keep it up to read results.
    code = main()
    if owns_console():
        input("\nPress Enter to close...")
    sys.exit(code)
