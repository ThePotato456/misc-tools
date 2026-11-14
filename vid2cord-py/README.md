<div align="center">

<img src="assets/banner.png" alt="vid2cord banner" width="100%">

# 🎬 vid2cord

**Re-encode any video to fit Discord's upload size limit. Command line, or drag and drop.**

[![Version](https://img.shields.io/badge/version-0.1.0-blue)](CHANGELOG.md)
[![Release](https://img.shields.io/github/v/release/ThePotato456/misc-tools?label=release)](https://github.com/ThePotato456/misc-tools/releases/latest)
[![Platform](https://img.shields.io/badge/platform-Windows-0078D6?logo=windows&logoColor=white)](#install)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![ffmpeg](https://img.shields.io/badge/requires-ffmpeg%20%2B%20ffprobe-007808?logo=ffmpeg&logoColor=white)](https://ffmpeg.org/download.html)
[![Discord](https://img.shields.io/badge/target-Discord-5865F2?logo=discord&logoColor=white)](#features)

</div>

## Features

- Targets **20 MB** by default; pick any limit with `-s MB`.
- Two-pass H.264 + AAC at the highest bitrate that fits, and retries smaller if the result runs over.
- Lowers the resolution only when the bitrate is too low for a clean picture.
- Skips files that already fit. Output: `<name>_discord.mp4`.
- Reads `.mp4 .mov .mkv .webm .avi .m4v .flv .wmv .ts`.

## Requirements

`ffmpeg` and `ffprobe` on your `PATH` ([download](https://ffmpeg.org/download.html)).

## Use

- **Drag and drop**: drop video files and/or folders onto `vid2cord.exe`. Output lands next to the originals, and the window stays open so you can read the results.
- **Command line**: pass files and/or folders.

```
vid2cord video.mp4
vid2cord video.mp4 -s 10      # 10 MB limit
vid2cord folder -r            # recurse
vid2cord a.mp4 -o out         # output folder
```

## Options

| Flag | Meaning |
| --- | --- |
| `-s`, `--size MB` | Target size limit in MB (default 20) |
| `-r`, `--recursive` | Search folders recursively |
| `-o`, `--out DIR` | Output folder (default: next to each source) |
| `-f`, `--force` | Overwrite existing outputs |
| `-V`, `--version` | Print the version |
| `-h`, `--help` | Show help |

## Install

Download `vid2cord.exe` from the [latest release](https://github.com/ThePotato456/misc-tools/releases/latest). No installer and no Python needed.

## Build from source

You need Python 3.10+ and `make`.

```
make exe                       # installs dependencies, builds dist/vid2cord.exe
```

Or run the script directly:

```
pip install -r requirements.txt
python vid2cord.py --help
```

## Links

- [Changelog](CHANGELOG.md)
- [Latest release](https://github.com/ThePotato456/misc-tools/releases/latest)
- [Other tools in misc-tools](https://github.com/ThePotato456/misc-tools)

---

<div align="center">

Made by **ThePotato456**

</div>
