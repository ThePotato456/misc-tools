"""Persistent settings for vid2mp4, stored as JSON in the operating system's per-user config folder.

    Windows   %APPDATA%\\vid2mp4\\settings.json
    macOS     ~/Library/Application Support/vid2mp4/settings.json
    Linux     $XDG_CONFIG_HOME/vid2mp4/settings.json  (default ~/.config/vid2mp4/settings.json)

Set VID2MP4_CONFIG_DIR to use another folder (handy for tests or a portable setup).

The file is forgiving: unknown keys are kept, missing or invalid values fall back to their defaults, and a file that is
not valid JSON is moved aside to settings.json.bad instead of being lost. Writes are atomic (temp file + replace).
No Tk and no ffmpeg calls in here, so it can be tested and used by any front end.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

from vid2mp4_core import PRESETS, SPEEDS

APP_NAME = "vid2mp4"
FILE_NAME = "settings.json"
SCHEMA = 1


def config_dir() -> Path:
    """The folder that holds settings.json (not created here)."""
    override = os.environ.get("VID2MP4_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / APP_NAME


def settings_path() -> Path:
    return config_dir() / FILE_NAME


# ---- the schema: key -> (default, validator) ---------------------------------------------------------------------------
def _choice(*options: str) -> Callable[[Any], bool]:
    return lambda v: v in options


def _int_between(lo: int, hi: int) -> Callable[[Any], bool]:
    return lambda v: isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _text(v: Any) -> bool:
    return isinstance(v, str)


def _flag(v: Any) -> bool:
    return isinstance(v, bool)


def _optional_int(lo: int, hi: int) -> Callable[[Any], bool]:
    """A number in [lo, hi] written as text, or "" meaning "use the preset's value"."""
    def check(v: Any) -> bool:
        if not isinstance(v, str):
            return False
        if v == "":
            return True
        try:
            return lo <= int(v) <= hi
        except ValueError:
            return False
    return check


QUALITIES = tuple(name for name in PRESETS if name != "mac")  # the quality ladder; "mac" is its own checkbox

SPEC: dict[str, tuple[Any, Callable[[Any], bool]]] = {
    # conversion options
    "quality": ("default", _choice(*QUALITIES)),
    "mac": (False, _flag),                                 # Mac / QuickTime / iOS compatible
    "encoder": ("gpu", _choice("gpu", "cpu")),
    "crf": ("", _optional_int(0, 51)),                     # "" = the quality preset's value
    "speed": ("", lambda v: v == "" or v in SPEEDS),       # "" = the quality preset's value
    "audio_bitrate": ("", _optional_int(16, 640)),         # kbps, "" = the quality preset's value
    "out_dir": ("", _text),                                # "" = next to each source
    "overwrite": (False, _flag),
    "reencode": (False, _flag),                            # never copy streams
    "jobs": (1, _int_between(1, 64)),
    "recursive": (True, _flag),                            # include subfolders when adding a folder
    "after": ("nothing", _choice("nothing", "open", "beep")),
    # window
    "theme": ("system", _choice("system", "light", "dark")),
    "geometry": ("", _text),                               # e.g. "900x680+120+80"
    "advanced_open": (False, _flag),
    "last_dir": ("", _text),                               # last folder used in a file dialog
}


def defaults() -> dict[str, Any]:
    return {key: default for key, (default, _check) in SPEC.items()}


class Settings:
    """A dict-like view of settings.json. Use load() once, then item access, then save()."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else settings_path()
        self.data: dict[str, Any] = defaults()
        self.extra: dict[str, Any] = {}      # keys this version does not know, written back untouched
        self.warning = ""                    # set when the file had to be repaired or set aside

    # ---- reading ------------------------------------------------------------------------------------------------
    def load(self) -> "Settings":
        self.data, self.extra, self.warning = defaults(), {}, ""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self
        except (OSError, ValueError) as e:
            self._set_aside(f"could not read it ({e})")
            return self
        if not isinstance(raw, dict):
            self._set_aside("it does not hold a JSON object")
            return self
        invalid = []
        for key, value in raw.items():
            if key == "version":
                continue
            if key in SPEC:
                if SPEC[key][1](value):
                    self.data[key] = value
                else:
                    invalid.append(key)
            else:
                self.extra[key] = value
        if invalid:
            self.warning = f"ignored invalid values in {self.path.name}: {', '.join(invalid)}"
        return self

    def _set_aside(self, why: str) -> None:
        bad = self.path.with_name(self.path.name + ".bad")
        try:
            os.replace(self.path, bad)
            self.warning = f"{self.path.name} was unusable ({why}); it was kept as {bad.name} and defaults are in use"
        except OSError:
            self.warning = f"{self.path.name} was unusable ({why}); defaults are in use"

    # ---- access -------------------------------------------------------------------------------------------------
    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        if key not in SPEC:
            raise KeyError(key)
        # An invalid value is dropped rather than stored, so the file never holds something load() would reject.
        self.data[key] = value if SPEC[key][1](value) else SPEC[key][0]

    def update(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            self[key] = value

    def reset(self) -> None:
        self.data = defaults()

    # ---- writing ------------------------------------------------------------------------------------------------
    def save(self) -> bool:
        """Write the file atomically. Returns False (and sets .warning) when the folder is not writable."""
        payload = {"version": SCHEMA, **self.extra, **self.data}
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(tmp, self.path)
            return True
        except OSError as e:
            self.warning = f"could not save settings to {self.path}: {e}"
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return False
