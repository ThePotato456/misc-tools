"""Convert PNG images to JPG.

Usage:
    png2jpg image.png              # single file -> image.jpg
    png2jpg some_folder            # every .png in the folder
    png2jpg some_folder -r         # recurse into subfolders
    png2jpg a.png b.png -o out     # write JPGs into ./out
    png2jpg image.png -q 85        # JPEG quality (default 92)
    png2jpg image.png -b 000000    # background for transparent areas (default ffffff)

Drag and drop .png files or folders onto png2jpg.exe to convert them.
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


def parse_color(text: str) -> tuple[int, int, int]:
    h = text.lstrip("#")
    if len(h) != 6:
        raise argparse.ArgumentTypeError(f"expected a hex color like ffffff, not {text!r}")
    try:
        return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a hex color like ffffff, not {text!r}") from None


def convert(src: Path, out_dir: Path | None, overwrite: bool, quality: int, bg: tuple[int, int, int]) -> bool:
    dest = (out_dir or src.parent) / (src.stem + ".jpg")
    if dest.exists() and not overwrite:
        print(f"skip (exists): {dest}")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        # JPEG has no transparency: flatten onto the background color. Animated PNGs keep their first frame.
        if im.mode in ("RGBA", "LA", "P") or "transparency" in im.info:
            rgba = im.convert("RGBA")
            flat = Image.new("RGB", rgba.size, bg)
            flat.paste(rgba, mask=rgba.getchannel("A"))
        else:
            flat = im.convert("RGB")
        flat.save(dest, "JPEG", quality=quality, optimize=True)
    print(f"{src} -> {dest}")
    return True


def is_png(p: Path) -> bool:
    return p.suffix.lower() == ".png"


def collect(paths: list[str], recursive: bool) -> list[Path]:
    files = []
    for p in map(Path, paths):
        if p.is_dir():
            pattern = "**/*" if recursive else "*"
            files += [f for f in p.glob(pattern) if is_png(f) and f.is_file()]
        elif p.is_file():
            if is_png(p):
                files.append(p)
            else:
                print(f"skip (not .png): {p}", file=sys.stderr)
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
        description="Convert PNG images to JPG. Drop files or folders onto the exe to convert them."
    )
    ap.add_argument("paths", nargs="*", help="PNG files and/or folders")
    ap.add_argument("-o", "--out", type=Path, help="output folder (default: next to each source)")
    ap.add_argument("-r", "--recursive", action="store_true", help="search folders recursively")
    ap.add_argument("-f", "--force", action="store_true", help="overwrite existing JPGs")
    ap.add_argument("-q", "--quality", type=int, default=92, choices=range(1, 96), metavar="1-95",
                    help="JPEG quality (default 92)")
    ap.add_argument("-b", "--background", type=parse_color, default=(255, 255, 255), metavar="RRGGBB",
                    help="background for transparent areas (default ffffff)")
    ap.add_argument("-V", "--version", action="version", version=f"%(prog)s {read_version()}")
    args = ap.parse_args()

    if not args.paths:
        ap.print_help()
        return 2

    files = collect(args.paths, args.recursive)
    if not files:
        print("no .png files found", file=sys.stderr)
        return 1

    done = failed = 0
    for f in files:
        try:
            done += convert(f, args.out, args.force, args.quality, args.background)
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
