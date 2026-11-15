# Changelog

## v0.2.0 - 2026-11-14

- Fix: files whose tags contain non-Latin text (for example MKVs with many subtitle tracks) failed in the window with "the JSON object must be str ... not NoneType". ffprobe and ffmpeg output is now read as UTF-8.
- Window redesigned: light and dark themes (follows Windows by default, dark title bar), a Source column that shows codec, bit depth, resolution and length of each file, colour-coded status per file, size-weighted overall progress with time remaining, sortable columns, striped rows and an empty-state hint.
- Window: right-click menu (show in folder, copy path or error, reset to Waiting, remove), double-click a finished file to find it in Explorer or a failed one to read its error, shortcuts (Ctrl+O, Ctrl+Shift+O, Ctrl+Enter, Esc, Ctrl+A, Del), tooltips, and a menu bar (File, View, Tools, Help).
- Window: Advanced options (CRF, speed, audio kbps) like the command line, "When finished" (do nothing, open the output folder, play a sound), Start retries only failed and cancelled files, adding files while a run is going, and Windows is kept awake during a conversion.
- Settings are now remembered between runs in `%APPDATA%\vid2mp4\settings.json` (`~/Library/Application Support/vid2mp4` on macOS, `~/.config/vid2mp4` on Linux; `VID2MP4_CONFIG_DIR` overrides): every option, theme, window size and position, and the last folder used. A damaged file is kept as `settings.json.bad` and replaced by defaults. Tools > Open settings folder and Tools > Reset options to defaults manage it.

## v0.1.0 - 2026-11-14

- First version: quick video encoder to MP4 (H.264 + AAC) with ffmpeg. Stackable presets `default`, `mac` (High profile, CRF 20, AAC 48 kHz stereo) and a quality ladder `low`, `small`, `medium`, `large`, `high`, `ultra`, `max`, overridable with `--crf`, `--speed`, `--audio-bitrate`, `--no-copy`. Copies streams that already fit, rounds odd sizes, deinterlaces, warns on HDR. Files, folders, recursion, drag and drop. Needs ffmpeg and ffprobe on PATH.
- Window version `vid2mp4-gui.exe` (drag and drop, quality and encoder choice, per-file and overall progress, cancel) next to the command line `vid2mp4.exe`, both on one shared engine (`vid2mp4_core.py`).
- GPU encoding by default (NVENC, Quick Sync, AMF) with `--cpu` for x264, `--jobs` for parallel files, and live progress bars in the command line tool.
