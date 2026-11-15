<div align="center">

# 🎞️ vid2mp4

**Quick video encoder: convert any video to MP4 (H.264 + AAC), with a macOS-compatible preset. Window or command line, with GPU encoding and live progress.**

[![Version](https://img.shields.io/badge/version-0.2.0-blue)](CHANGELOG.md)
[![Release](https://img.shields.io/github/v/release/ThePotato456/misc-tools?label=release)](https://github.com/ThePotato456/misc-tools/releases/latest)
[![Platform](https://img.shields.io/badge/platform-Windows-0078D6?logo=windows&logoColor=white)](#install)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![ffmpeg](https://img.shields.io/badge/requires-ffmpeg%20%2B%20ffprobe-007808?logo=ffmpeg&logoColor=white)](https://ffmpeg.org/download.html)

</div>

## Features

- **Two programs, one engine**: `vid2mp4-gui.exe` (a window with drag and drop, per-file progress and options) and `vid2mp4.exe` (command line, with progress bars).
- **GPU encoding by default** (NVENC, Quick Sync or AMF, found automatically): much faster. `--cpu` (or the Encoder box in the window) uses x264 for smaller files. Falls back to the CPU when no GPU encoder works.
- A quick, general video encoder: any common video in, **MP4 (H.264 + AAC)** out, with `+faststart` for streaming.
- **Presets** for compatibility, quality and size (table below). They stack, e.g. `--preset mac,small`, and any other option overrides them.
- **Stream copy when possible**: video is copied if it is already 8-bit 4:2:0 H.264, audio if it is already AAC-LC (and, for `mac`, 48 kHz stereo). Those conversions are fast and lossless. `--no-copy` forces a re-encode.
- Handles the cases that usually break conversions: odd frame sizes are rounded to even, interlaced video is deinterlaced, HDR sources get a warning.
- Batch: files, folders, `-r` recursion. Reports every failure and a final tally.
- Output: `<name>.mp4` next to the source. A `.mp4` input needs `-o`, so it never overwrites itself.
- Only the first video and first audio stream are kept; extra audio tracks and subtitles are dropped, and the tool says so.
- Reads `.mp4 .mov .mkv .webm .avi .m4v .flv .wmv .ts .mts .m2ts .3gp .ogv`.

### Presets

| Preset | Video | Audio | Use it for |
| --- | --- | --- | --- |
| `default` | CRF 23, medium | AAC 192k, source layout | general use |
| `mac` | CRF 20, medium, High profile | AAC 192k, 48 kHz stereo | QuickTime, Safari, iOS, Finder previews |
| `low` | CRF 32, fast | AAC 96k | fastest and tiniest, visibly soft |
| `small` | CRF 28, slow | AAC 128k | small file that still looks fine |
| `medium` | CRF 23, medium | AAC 192k | same as `default` |
| `large` | CRF 20, slow | AAC 224k | clearly better than medium |
| `high` | CRF 18, slow | AAC 256k | visually clean |
| `ultra` | CRF 16, slower | AAC 320k | very clean |
| `max` | CRF 14, slower | AAC 320k | near transparent, biggest files |

Every preset outputs `yuv420p` H.264 with `+faststart` and keeps resolution and frame rate. A preset only changes what it lists, so they stack and the last one wins: `--preset mac,small` is 48 kHz stereo and High profile (from `mac`) at CRF 28, slow (from `small`). Lower CRF means better quality and a bigger file; slower speeds shrink the file at the cost of time.

## Requirements

`ffmpeg` and `ffprobe` on your `PATH` ([download](https://ffmpeg.org/download.html)).

## Use

- **Window**: run `vid2mp4-gui.exe`, drop videos or folders on it (or use Add files / Add folder), pick a quality, press Start. Cancel stops cleanly and leaves no partial files. The window remembers your options, theme, size and position between runs in a settings file (see [Settings](#settings)).
- **Drag and drop onto the exe**: drop video files and/or folders onto `vid2mp4.exe`. Output lands next to the originals, and the window stays open so you can read the results.
- **Command line**: pass files and/or folders.

```
vid2mp4 video.mkv
vid2mp4 video.mkv --preset mac
vid2mp4 video.mkv -p mac,small        # presets stack
vid2mp4 folder -r --preset mac        # every video under a folder
vid2mp4 a.mkv --crf 18 --speed slow   # higher quality, smaller file, slower
vid2mp4 a.mkv -o out                  # output folder
```

## Options

| Flag | Meaning |
| --- | --- |
| `-p`, `--preset NAME[,NAME]` | `default`, `mac`, `low`, `small`, `medium`, `large`, `high`, `ultra`, `max`; stack with commas |
| `-q`, `--crf N` | x264 quality, 0-51, lower is better (overrides the preset; default 23) |
| `--speed NAME` | x264 speed preset, `ultrafast` to `veryslow` (default `medium`) |
| `--audio-bitrate KBPS` | AAC bitrate (default 192) |
| `--no-copy` | Always re-encode, never copy streams |
| `-r`, `--recursive` | Search folders recursively |
| `-o`, `--out DIR` | Output folder (default: next to each source) |
| `-f`, `--force` | Overwrite existing outputs |
| `--cpu` | Encode with x264 on the CPU instead of the GPU: slower, smaller files at the same quality |
| `-j`, `--jobs N` | Convert N files at once (`0` = one per 4 cores). One file already uses every core, so this mainly helps with many small files |
| `-V`, `--version` | Print the version |
| `-h`, `--help` | Show help |

## Install

Download `vid2mp4-gui.exe` (window) and/or `vid2mp4.exe` (command line) from the [latest release](https://github.com/ThePotato456/misc-tools/releases/latest). No installer and no Python needed.

## Build from source

You need Python 3.10+ and `make`.

```
make exe                       # installs dependencies, builds dist/vid2mp4.exe and dist/vid2mp4-gui.exe
make exe-cli                   # only the command line exe
make exe-gui                   # only the window exe
```

Or run the script directly:

```
python vid2mp4.py --help         # command line
python vid2mp4_gui.py            # window
```

## Links

- [Changelog](CHANGELOG.md)
- [Latest release](https://github.com/ThePotato456/misc-tools/releases/latest)
- [Other tools in misc-tools](https://github.com/ThePotato456/misc-tools)

---

<div align="center">

Made by **ThePotato456**

</div>

## Settings

`vid2mp4-gui.exe` saves its options automatically as JSON in your per-user config folder:

| System | File |
| --- | --- |
| Windows | `%APPDATA%\vid2mp4\settings.json` |
| macOS | `~/Library/Application Support/vid2mp4/settings.json` |
| Linux | `$XDG_CONFIG_HOME/vid2mp4/settings.json` (default `~/.config/vid2mp4/`) |

Set `VID2MP4_CONFIG_DIR` to use another folder. It holds the quality, Mac option, encoder, CRF / speed / audio overrides, output folder, overwrite and re-encode switches, files at once, "when finished" action, theme, window size and position, and the last folder you browsed. **Tools > Open settings folder** finds it and **Tools > Reset options to defaults** clears it; deleting the file does the same. A file that cannot be read is kept as `settings.json.bad` and defaults are used. The command line tool does not read this file.
