"""vid2mp4 GUI: convert videos to MP4 (H.264 + AAC) from a window. Drop files or folders on it, pick a quality, press Start.

Same engine as the command line tool (vid2mp4.exe). Requires ffmpeg and ffprobe on PATH.
Your choices are remembered between runs in a settings file (see vid2mp4_settings.py for where it lives).
"""

import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

import vid2mp4_core as core
import vid2mp4_settings as cfgfile

try:  # drag and drop from Explorer; the window still works without it
    from tkinterdnd2 import DND_FILES, TkinterDnD
    BaseTk = TkinterDnD.Tk
except Exception:  # noqa: BLE001
    DND_FILES, BaseTk = None, tk.Tk

QUALITIES = list(cfgfile.QUALITIES)
ENCODERS = {"gpu": "GPU (fast)", "cpu": "CPU (smaller files)"}
AFTER = {"nothing": "Do nothing", "open": "Open the output folder", "beep": "Play a sound"}
THEMES = {"system": "Match Windows", "light": "Light", "dark": "Dark"}
BAR = 14  # width of the per-file text bar
DEFAULT_SIZE = "940x780"
MIN_SIZE = (780, 700)

LIGHT = dict(bg="#f3f4f6", panel="#ffffff", field="#ffffff", fg="#1f2328", muted="#6b7280", border="#d0d5dd",
             accent="#2563eb", accent_fg="#ffffff", accent_hover="#1d4fd8", select="#dbeafe", select_fg="#1f2328",
             ok="#15803d", bad="#b91c1c", warn="#a16207", trough="#e5e7eb", head="#eceef2", button="#ffffff",
             button_hover="#eef2ff", disabled="#9ca3af")
DARK = dict(bg="#1b1d21", panel="#25282d", field="#202226", fg="#e4e6eb", muted="#8b919a", border="#3a3e45",
            accent="#4c8dff", accent_fg="#0b0d10", accent_hover="#6ea1ff", select="#2f4a7a", select_fg="#ffffff",
            ok="#5dc27a", bad="#ff6b66", warn="#e0b050", trough="#33373d", head="#2b2e34", button="#2d3138",
            button_hover="#383d45", disabled="#5b6068")


# ---- helpers ------------------------------------------------------------------------------------------------------
def text_bar(fraction: float) -> str:
    filled = round(max(0.0, min(1.0, fraction)) * BAR)
    return "█" * filled + "░" * (BAR - filled)


def system_is_dark() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def keep_awake(on: bool) -> None:
    """Stop Windows from sleeping while a conversion runs. Applies to the calling thread."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.SetThreadExecutionState(0x80000001 if on else 0x80000000)  # CONTINUOUS | SYSTEM_REQUIRED
        except Exception:  # noqa: BLE001
            pass


def reveal(path: Path) -> None:
    """Show a file in Explorer / Finder / the file manager."""
    try:
        if sys.platform == "win32":
            subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
    except OSError:
        pass


def open_folder(path: Path) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])
    except OSError:
        pass


def clock(seconds: float) -> str:
    """Short remaining-time text: 45s, 3m05s, 1h12m."""
    s = int(max(0, seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60:02d}s"
    return f"{s // 3600}h{s % 3600 // 60:02d}m"


CODEC_NAMES = {"h264": "H.264", "hevc": "HEVC", "vp9": "VP9", "vp8": "VP8", "av1": "AV1", "mpeg4": "MPEG-4",
               "mpeg2video": "MPEG-2", "wmv3": "WMV", "vc1": "VC-1", "prores": "ProRes"}


def describe(info: dict) -> str:
    """One line about a source: 'HEVC 10-bit · 1920×802 · 1h45m'."""
    v = info.get("video")
    if not v:
        return "no video"
    parts = [CODEC_NAMES.get(v.get("codec_name", ""), (v.get("codec_name") or "?").upper())]
    bits = re.search(r"(\d+)(?:le|be)$", v.get("pix_fmt", "") or "")
    parts[0] += f" {bits.group(1)}-bit" if bits and bits.group(1) != "8" else ""
    if v.get("width") and v.get("height"):
        parts.append(f"{v['width']}×{v['height']}")
    if info.get("duration"):
        parts.append(clock(info["duration"]))
    return " · ".join(parts)


class Tip:
    """A small hover tooltip."""

    def __init__(self, app: "App", widget: tk.Widget, text: str) -> None:
        self.app, self.widget, self.text, self.win, self.job = app, widget, text, None, None
        widget.bind("<Enter>", self._arm, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _arm(self, _e=None) -> None:
        self._hide()
        self.job = self.widget.after(600, self._show)

    def _show(self) -> None:
        p = self.app.palette
        self.win = tk.Toplevel(self.widget)
        self.win.wm_overrideredirect(True)
        self.win.wm_geometry(f"+{self.widget.winfo_rootx() + 12}+{self.widget.winfo_rooty() + self.widget.winfo_height() + 6}")
        tk.Label(self.win, text=self.text, justify="left", bg=p["panel"], fg=p["fg"], relief="solid", bd=1,
                 padx=8, pady=5, wraplength=360).pack()

    def _hide(self, _e=None) -> None:
        if self.job:
            self.widget.after_cancel(self.job)
            self.job = None
        if self.win:
            self.win.destroy()
            self.win = None


class App(BaseTk):
    def __init__(self) -> None:
        super().__init__()
        self.settings = cfgfile.Settings().load()
        self.palette = LIGHT
        self.title(f"vid2mp4 {core.read_version()}")
        self.minsize(*MIN_SIZE)
        self.geometry(self._saved_geometry())

        self.files: dict[str, Path] = {}       # tree item id -> source path
        self.sizes: dict[str, int] = {}        # tree item id -> bytes
        self.rstate: dict[str, str] = {}        # tree item id -> waiting | running | done | skipped | failed | cancelled
        self.dests: dict[str, Path] = {}       # tree item id -> converted file
        self.errors: dict[str, str] = {}       # tree item id -> full error text
        self.fraction: dict[str, float] = {}   # tree item id -> 0..1 progress of the current run, for the overall bar
        self.events: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self.probe_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="probe")
        self.gpu: str | None = None
        self.gpu_ready = False
        self.run_started = 0.0
        self.run_total = 0
        self.last_out: Path | None = None
        self.sort_col, self.sort_rev = "", False
        self._save_job: str | None = None
        self._tips: list[Tip] = []

        self._build()
        self._build_menu()
        self._apply_theme()
        self._bind_keys()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll)
        if self.settings.warning:
            self.status.config(text=self.settings.warning)
        threading.Thread(target=self._detect_gpu, daemon=True).start()

    # ---- settings -----------------------------------------------------------------------------------------------
    def _saved_geometry(self) -> str:
        """The remembered window size and position, if it still fits on a screen; else the default size, centred."""
        m = re.fullmatch(r"(\d+)x(\d+)([+-]-?\d+)([+-]-?\d+)", self.settings["geometry"])
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        if m:
            w, h, x, y = int(m[1]), int(m[2]), int(m[3]), int(m[4])
            w, h = max(MIN_SIZE[0], min(w, sw)), max(MIN_SIZE[1], min(h, sh))
            x, y = max(0, min(x, sw - 120)), max(0, min(y, sh - 120))
            return f"{w}x{h}+{x}+{y}"
        w, h = (int(n) for n in DEFAULT_SIZE.split("x"))
        return f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}"

    def _collect(self) -> dict:
        """Current widget values in settings-file form."""
        enc = "cpu" if self.v_encoder.get() == ENCODERS["cpu"] else "gpu"
        after = next((k for k, label in AFTER.items() if label == self.v_after.get()), "nothing")
        try:
            jobs = max(1, int(self.v_jobs.get()))
        except ValueError:
            jobs = 1
        return dict(quality=self.v_quality.get(), mac=self.v_mac.get(), encoder=enc, crf=self.v_crf.get().strip(),
                    speed=self.v_speed.get().strip(), audio_bitrate=self.v_abr.get().strip(), out_dir=self.v_out.get().strip(),
                    overwrite=self.v_overwrite.get(), reencode=self.v_reencode.get(), jobs=jobs,
                    recursive=self.v_recursive.get(), after=after, advanced_open=self.advanced_open)

    def _changed(self, *_a) -> None:
        """Any option changed: refresh the summary and save soon (not on every keystroke)."""
        self._refresh_summary()
        if self._save_job:
            self.after_cancel(self._save_job)
        self._save_job = self.after(600, self.save_settings)

    def save_settings(self) -> None:
        self._save_job = None
        self.settings.update(self._collect())
        self.settings["theme"] = self.v_theme.get()
        try:
            if self.wm_state() == "normal":
                self.settings["geometry"] = self.geometry()
        except tk.TclError:
            pass
        self.settings.save()

    def reset_settings(self) -> None:
        if self._running():
            return
        if not messagebox.askyesno("vid2mp4", "Reset every option to its default?\nThe file list is not touched."):
            return
        keep = self.settings["geometry"]
        self.settings.reset()
        self.settings["geometry"] = keep
        self._load_vars()
        self._apply_theme()
        self.save_settings()
        self.status.config(text="Options reset to their defaults")

    # ---- layout -------------------------------------------------------------------------------------------------
    def _build(self) -> None:
        s = self.settings
        self.advanced_open = s["advanced_open"]
        self.v_quality = tk.StringVar()
        self.v_mac = tk.BooleanVar()
        self.v_encoder = tk.StringVar()
        self.v_crf, self.v_speed, self.v_abr = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.v_out = tk.StringVar()
        self.v_overwrite, self.v_reencode, self.v_recursive = tk.BooleanVar(), tk.BooleanVar(), tk.BooleanVar()
        self.v_jobs = tk.StringVar()
        self.v_after = tk.StringVar()
        self.v_theme = tk.StringVar(value=s["theme"])

        self.root = ttk.Frame(self, padding=(14, 12, 14, 12))
        self.root.pack(fill="both", expand=True)
        root = self.root

        # toolbar
        bar = ttk.Frame(root)
        bar.pack(fill="x")
        self.add_files_btn = ttk.Button(bar, text="＋  Add files…", command=self.add_files)
        self.add_folder_btn = ttk.Button(bar, text="＋  Add folder…", command=self.add_folder)
        self.remove_btn = ttk.Button(bar, text="Remove", command=self.remove_selected)
        self.clear_btn = ttk.Button(bar, text="Clear", command=self.clear)
        for b in (self.add_files_btn, self.add_folder_btn, self.remove_btn, self.clear_btn):
            b.pack(side="left", padx=(0, 6))
        self.recursive_cb = ttk.Checkbutton(bar, text="Include subfolders", variable=self.v_recursive)
        self.recursive_cb.pack(side="right")

        # file list
        box = ttk.Frame(root, style="Card.TFrame")
        cols = ("info", "size", "status")
        self.tree = ttk.Treeview(box, columns=("name", *cols), show="headings", selectmode="extended", height=5)
        for col, title, width, anchor, stretch in (("name", "File", 270, "w", True), ("info", "Source", 210, "w", False),
                                                   ("size", "Size", 76, "e", False), ("status", "Status", 330, "w", True)):
            self.tree.heading(col, text=title, anchor="w" if anchor == "w" else "e",
                              command=(lambda c=col: self._sort(c)) if col in ("name", "size") else "")
            self.tree.column(col, width=width, minwidth=60, anchor=anchor, stretch=stretch)
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(1, 0), pady=1)
        scroll.pack(side="right", fill="y", pady=1)
        self.tree.bind("<Delete>", lambda _e: self.remove_selected())
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._refresh_hint())
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Button-3>", self._on_right_click)
        self.empty = tk.Label(box, text="Drop videos or folders here\nor press  Add files…" if DND_FILES
                              else "Press  Add files…  or  Add folder…", font=("Segoe UI", 13), justify="center")
        self.empty.place(relx=0.5, rely=0.5, anchor="center")
        self.empty.bind("<Button-1>", lambda _e: self.add_files())

        self.hint = ttk.Label(root, style="Muted.TLabel")

        # options
        opts = ttk.LabelFrame(root, text=" Options ", padding=(10, 6, 10, 8))
        opts.columnconfigure(2, weight=1)
        g = dict(sticky="w", pady=4)

        ttk.Label(opts, text="Quality").grid(row=0, column=0, padx=(0, 10), **g)
        self.quality_cb = ttk.Combobox(opts, textvariable=self.v_quality, values=QUALITIES, state="readonly", width=14)
        self.quality_cb.grid(row=0, column=1, **g)
        self.summary = ttk.Label(opts, style="Muted.TLabel")
        self.summary.grid(row=0, column=2, columnspan=2, padx=12, **g)
        self.mac_cb = ttk.Checkbutton(opts, text="Mac / QuickTime / iOS compatible", variable=self.v_mac)
        self.mac_cb.grid(row=1, column=1, columnspan=3, **g)

        ttk.Label(opts, text="Encoder").grid(row=2, column=0, padx=(0, 10), **g)
        self.encoder_cb = ttk.Combobox(opts, textvariable=self.v_encoder, values=list(ENCODERS.values()),
                                       state="readonly", width=20)
        self.encoder_cb.grid(row=2, column=1, **g)
        self.encoder_note = ttk.Label(opts, text="checking for a GPU encoder…", style="Muted.TLabel")
        self.encoder_note.grid(row=2, column=2, columnspan=2, padx=12, **g)

        ttk.Label(opts, text="Output folder").grid(row=3, column=0, padx=(0, 10), **g)
        out_row = ttk.Frame(opts)
        out_row.grid(row=3, column=1, columnspan=3, sticky="ew", pady=4)
        out_row.columnconfigure(0, weight=1)
        self.out_entry = ttk.Entry(out_row, textvariable=self.v_out)
        self.out_entry.grid(row=0, column=0, sticky="ew")
        self.browse_btn = ttk.Button(out_row, text="Browse…", command=self.pick_output)
        self.browse_btn.grid(row=0, column=1, padx=(6, 0))
        self.open_btn = ttk.Button(out_row, text="Open", command=self.open_output, width=6)
        self.open_btn.grid(row=0, column=2, padx=(6, 0))
        ttk.Label(opts, text="Empty = next to each source", style="Muted.TLabel").grid(row=4, column=1, columnspan=3, sticky="w")

        flags = ttk.Frame(opts)
        flags.grid(row=5, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self.overwrite_cb = ttk.Checkbutton(flags, text="Overwrite existing", variable=self.v_overwrite)
        self.reencode_cb = ttk.Checkbutton(flags, text="Always re-encode (never copy streams)", variable=self.v_reencode)
        self.overwrite_cb.pack(side="left", padx=(0, 16))
        self.reencode_cb.pack(side="left", padx=(0, 16))
        ttk.Label(flags, text="Files at once").pack(side="left")
        self.jobs_sp = ttk.Spinbox(flags, from_=1, to=max(1, os.cpu_count() or 4), textvariable=self.v_jobs, width=4)
        self.jobs_sp.pack(side="left", padx=(6, 16))
        ttk.Label(flags, text="When finished").pack(side="left")
        self.after_cb = ttk.Combobox(flags, textvariable=self.v_after, values=list(AFTER.values()), state="readonly", width=22)
        self.after_cb.pack(side="left", padx=(6, 0))

        self.adv_btn = ttk.Button(opts, style="Link.TButton", command=self._toggle_advanced)
        self.adv_btn.grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.adv = ttk.Frame(opts)
        self.adv.grid(row=7, column=0, columnspan=4, sticky="w")
        ttk.Label(self.adv, text="CRF").pack(side="left")
        self.crf_sp = ttk.Spinbox(self.adv, from_=0, to=51, textvariable=self.v_crf, width=5)
        self.crf_sp.pack(side="left", padx=(6, 16))
        ttk.Label(self.adv, text="Speed").pack(side="left")
        self.speed_cb = ttk.Combobox(self.adv, textvariable=self.v_speed, values=[""] + core.SPEEDS, state="readonly", width=11)
        self.speed_cb.pack(side="left", padx=(6, 16))
        ttk.Label(self.adv, text="Audio kbps").pack(side="left")
        self.abr_sp = ttk.Spinbox(self.adv, from_=16, to=640, increment=16, textvariable=self.v_abr, width=6)
        self.abr_sp.pack(side="left", padx=(6, 16))
        ttk.Label(self.adv, text="Blank = use the Quality setting", style="Muted.TLabel").pack(side="left")

        # run
        run = ttk.Frame(root)
        self.bar = ttk.Progressbar(run, maximum=100)
        self.bar.pack(fill="x")
        row = ttk.Frame(run)
        row.pack(fill="x", pady=(8, 0))
        self.status = ttk.Label(row, text="Add some videos to begin")
        self.status.pack(side="left")
        self.start_btn = ttk.Button(row, text="Start", style="Accent.TButton", command=self.start, state="disabled", width=12)
        self.start_btn.pack(side="right")
        self.cancel_btn = ttk.Button(row, text="Cancel", command=self.cancel_run, state="disabled", width=10)
        self.cancel_btn.pack(side="right", padx=(0, 8))

        # Pack from the bottom up first so a short window squeezes the file list, never the controls.
        run.pack(side="bottom", fill="x", pady=(12, 0))
        opts.pack(side="bottom", fill="x", pady=(8, 0))
        self.hint.pack(side="bottom", anchor="w", pady=(4, 0))
        box.pack(side="top", fill="both", expand=True, pady=(10, 0))

        self._menu_tree = tk.Menu(self, tearoff=False)

        # remember the values, load them, then start watching for changes
        self._load_vars()
        for var in (self.v_quality, self.v_mac, self.v_encoder, self.v_crf, self.v_speed, self.v_abr, self.v_out,
                    self.v_overwrite, self.v_reencode, self.v_recursive, self.v_jobs, self.v_after):
            var.trace_add("write", self._changed)

        if DND_FILES:
            for widget in (self, self.tree, self.empty, self.hint):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)

        tips = {
            self.quality_cb: "Quality ladder from low (small, soft) to max (huge, near lossless).\nLower CRF = better and bigger.",
            self.mac_cb: "High profile H.264 and 48 kHz stereo AAC: plays in QuickTime, Safari, iOS and Finder previews.",
            self.encoder_cb: "GPU: NVENC / Quick Sync / AMF, much faster.\nCPU: x264, smaller files at the same quality.",
            self.reencode_cb: "Normally video and audio that already fit are copied: fast and lossless.\nTick this to force a full re-encode.",
            self.jobs_sp: "x264 already uses every core for one file, so more than 1 mainly helps with many small files.",
            self.crf_sp: "x264 constant rate factor, 0-51. Lower = better quality, bigger file. Overrides the Quality setting.",
            self.speed_cb: "Slower = smaller file for the same quality. On a GPU it picks the NVENC preset.",
            self.out_entry: "Where converted files go. Empty = next to each source.",
            self.overwrite_cb: "Replace an existing .mp4 of the same name instead of skipping the file.",
        }
        self._tips = [Tip(self, w, t) for w, t in tips.items()]
        self._refresh_summary()
        self._refresh_hint()

    def _load_vars(self) -> None:
        s = self.settings
        self.v_quality.set(s["quality"])
        self.v_mac.set(s["mac"])
        self.v_encoder.set(ENCODERS[s["encoder"]])
        self.v_crf.set(s["crf"])
        self.v_speed.set(s["speed"])
        self.v_abr.set(s["audio_bitrate"])
        self.v_out.set(s["out_dir"])
        self.v_overwrite.set(s["overwrite"])
        self.v_reencode.set(s["reencode"])
        self.v_recursive.set(s["recursive"])
        self.v_jobs.set(str(s["jobs"]))
        self.v_after.set(AFTER[s["after"]])
        self.v_theme.set(s["theme"])
        self.advanced_open = s["advanced_open"]
        self._show_advanced()

    def _toggle_advanced(self) -> None:
        self.advanced_open = not self.advanced_open
        self._show_advanced()
        self._changed()

    def _show_advanced(self) -> None:
        self.adv_btn.config(text=("▾  Advanced" if self.advanced_open else "▸  Advanced"))
        if self.advanced_open:
            self.adv.grid()
        else:
            self.adv.grid_remove()

    def _build_menu(self) -> None:
        bar = tk.Menu(self)
        self.menus = [bar]

        def add(label: str, items) -> tk.Menu:
            m = tk.Menu(bar, tearoff=False)
            self.menus.append(m)
            for item in items:
                if item is None:
                    m.add_separator()
                elif item[0] == "radio":
                    m.add_radiobutton(label=item[1], variable=item[2], value=item[3], command=item[4])
                else:
                    m.add_command(label=item[0], command=item[1], accelerator=item[2] if len(item) > 2 else "")
            bar.add_cascade(label=label, menu=m)
            return m

        add("File", [("Add files…", self.add_files, "Ctrl+O"), ("Add folder…", self.add_folder, "Ctrl+Shift+O"), None,
                     ("Remove selected", self.remove_selected, "Del"), ("Clear list", self.clear), None,
                     ("Exit", self._on_close, "Alt+F4")])
        add("View", [("radio", label, self.v_theme, key, self._theme_changed) for key, label in THEMES.items()])
        add("Tools", [("Open settings folder", lambda: open_folder(self.settings.path.parent)),
                      ("Reset options to defaults", self.reset_settings), None,
                      ("Check for GPU encoder again", self._redetect_gpu)])
        add("Help", [("About vid2mp4", self.about)])
        self.config(menu=bar)

    def _bind_keys(self) -> None:
        self.bind("<Control-o>", lambda _e: self.add_files())
        self.bind("<Control-O>", lambda _e: self.add_folder())
        self.bind("<Control-Return>", lambda _e: self.start() if str(self.start_btn["state"]) == "normal" else None)
        self.bind("<Escape>", lambda _e: self.cancel_run() if self._running() else None)
        self.tree.bind("<Control-a>", lambda _e: (self.tree.selection_set(self.tree.get_children()), "break")[1])

    # ---- look ---------------------------------------------------------------------------------------------------
    def _theme_changed(self) -> None:
        self._apply_theme()
        self.save_settings()

    def _apply_theme(self) -> None:
        mode = self.v_theme.get()
        dark = mode == "dark" or (mode == "system" and system_is_dark())
        p = self.palette = DARK if dark else LIGHT
        scale = max(1.0, self.winfo_fpixels("1i") / 96)

        if sys.platform == "win32":
            for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
                tkfont.nametofont(name).configure(family="Segoe UI", size=10)
        style = ttk.Style(self)
        style.theme_use("clam")
        self.configure(bg=p["bg"])
        style.configure(".", background=p["bg"], foreground=p["fg"], fieldbackground=p["field"], bordercolor=p["border"],
                        lightcolor=p["bg"], darkcolor=p["bg"], troughcolor=p["trough"], focuscolor=p["bg"],
                        insertcolor=p["fg"], selectbackground=p["select"], selectforeground=p["select_fg"])
        style.map(".", foreground=[("disabled", p["disabled"])])
        style.configure("Muted.TLabel", foreground=p["muted"])
        style.configure("Card.TFrame", background=p["border"])
        style.configure("TLabelframe", background=p["bg"], bordercolor=p["border"], lightcolor=p["border"], darkcolor=p["border"])
        style.configure("TLabelframe.Label", background=p["bg"], foreground=p["muted"])

        pad = (14, 6)
        style.configure("TButton", background=p["button"], foreground=p["fg"], bordercolor=p["border"], lightcolor=p["button"],
                        darkcolor=p["button"], padding=pad, relief="flat", focusthickness=0)
        style.map("TButton", background=[("disabled", p["bg"]), ("pressed", p["button_hover"]), ("active", p["button_hover"])],
                  bordercolor=[("focus", p["accent"])])
        style.configure("Accent.TButton", background=p["accent"], foreground=p["accent_fg"], bordercolor=p["accent"],
                        lightcolor=p["accent"], darkcolor=p["accent"], padding=(14, 7), font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton", background=[("disabled", p["trough"]), ("pressed", p["accent_hover"]), ("active", p["accent_hover"])],
                  foreground=[("disabled", p["disabled"])], bordercolor=[("disabled", p["trough"])],
                  lightcolor=[("disabled", p["trough"])], darkcolor=[("disabled", p["trough"])])
        style.configure("Link.TButton", background=p["bg"], foreground=p["accent"], bordercolor=p["bg"], lightcolor=p["bg"],
                        darkcolor=p["bg"], padding=(0, 2))
        style.map("Link.TButton", background=[("active", p["bg"])], foreground=[("active", p["accent_hover"])])

        for kind in ("TEntry", "TCombobox", "TSpinbox"):
            style.configure(kind, fieldbackground=p["field"], foreground=p["fg"], bordercolor=p["border"], lightcolor=p["field"],
                            darkcolor=p["field"], arrowcolor=p["fg"], insertcolor=p["fg"], padding=4)
            style.map(kind, bordercolor=[("focus", p["accent"])], fieldbackground=[("disabled", p["bg"]), ("readonly", p["field"])],
                      foreground=[("disabled", p["disabled"])], selectbackground=[("readonly", p["field"])],
                      selectforeground=[("readonly", p["fg"])])
        self.option_add("*TCombobox*Listbox.background", p["field"])
        self.option_add("*TCombobox*Listbox.foreground", p["fg"])
        self.option_add("*TCombobox*Listbox.selectBackground", p["accent"])
        self.option_add("*TCombobox*Listbox.selectForeground", p["accent_fg"])

        for kind in ("TCheckbutton", "TRadiobutton"):
            style.configure(kind, background=p["bg"], foreground=p["fg"], indicatorbackground=p["field"],
                            indicatorforeground=p["accent"], bordercolor=p["border"])
            style.map(kind, background=[("active", p["bg"])], indicatorbackground=[("selected", p["accent"]), ("disabled", p["bg"])],
                      indicatorforeground=[("selected", p["accent_fg"])], foreground=[("disabled", p["disabled"])])

        style.configure("Treeview", background=p["field"], fieldbackground=p["field"], foreground=p["fg"], borderwidth=0,
                        rowheight=int(28 * scale), relief="flat")
        style.map("Treeview", background=[("selected", p["select"])], foreground=[("selected", p["select_fg"])])
        style.configure("Treeview.Heading", background=p["head"], foreground=p["fg"], relief="flat", padding=(8, 6),
                        bordercolor=p["head"], lightcolor=p["head"], darkcolor=p["head"])
        style.map("Treeview.Heading", background=[("active", p["button_hover"])])
        for tag, color in (("done", p["ok"]), ("failed", p["bad"]), ("skipped", p["warn"]), ("running", p["accent"]),
                           ("cancelled", p["muted"])):
            self.tree.tag_configure(tag, foreground=color)
        self.tree.tag_configure("odd", background=p["panel"] if dark else "#f8f9fb")

        style.configure("Horizontal.TProgressbar", troughcolor=p["trough"], background=p["accent"], bordercolor=p["trough"],
                        lightcolor=p["accent"], darkcolor=p["accent"], thickness=int(10 * scale))
        style.configure("Vertical.TScrollbar", background=p["button"], troughcolor=p["field"], bordercolor=p["field"],
                        arrowcolor=p["muted"], lightcolor=p["button"], darkcolor=p["button"], gripcount=0)
        style.map("Vertical.TScrollbar", background=[("active", p["button_hover"])])

        self.empty.config(bg=p["field"], fg=p["muted"])
        for m in (*self.menus, self._menu_tree):
            m.config(bg=p["panel"], fg=p["fg"], activebackground=p["accent"], activeforeground=p["accent_fg"],
                     disabledforeground=p["disabled"], selectcolor=p["fg"], bd=0, relief="flat")
        self._dark_titlebar(dark)

    def _dark_titlebar(self, dark: bool) -> None:
        if sys.platform != "win32":
            return
        try:
            import ctypes

            self.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            value = ctypes.c_int(1 if dark else 0)
            for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (Windows 10 20H1+ / older builds)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
        except Exception:  # noqa: BLE001
            pass

    # ---- options ------------------------------------------------------------------------------------------------
    def _config(self) -> tuple[dict, str]:
        """(settings for the encode, problem text). The problem is "" when every option is valid."""
        names = (["mac"] if self.v_mac.get() else []) + ([self.v_quality.get()] if self.v_quality.get() != "default" else [])
        cfg = core.resolve_presets(names or ["default"])
        problem = ""
        crf, abr, speed = self.v_crf.get().strip(), self.v_abr.get().strip(), self.v_speed.get().strip()
        if crf:
            if crf.isdigit() and 0 <= int(crf) <= 51:
                cfg["crf"] = int(crf)
            else:
                problem = "CRF must be a whole number from 0 to 51"
        if abr:
            if abr.isdigit() and 16 <= int(abr) <= 640:
                cfg["audio_bitrate"] = int(abr)
            else:
                problem = problem or "Audio kbps must be a whole number from 16 to 640"
        if speed in core.SPEEDS:
            cfg["speed"] = speed
        return cfg, problem

    def _use_gpu(self) -> str | None:
        return self.gpu if self.v_encoder.get() == ENCODERS["gpu"] else None

    def _refresh_summary(self) -> None:
        cfg, problem = self._config()
        if problem:
            self.summary.config(text=problem, foreground=self.palette["bad"])
            return
        text = f"crf {cfg['crf']}, {cfg['speed']} speed, AAC {cfg['audio_bitrate']}k"
        if self.v_mac.get():
            text += ", High profile, 48 kHz stereo"
        self.summary.config(text=text, foreground=self.palette["muted"])

    def _detect_gpu(self) -> None:
        try:
            self.events.put(("gpu", core.detect_gpu_encoder(core.find_tool("ffmpeg")), None))
        except RuntimeError as e:
            self.events.put(("gpu", None, str(e)))

    def _redetect_gpu(self) -> None:
        self.gpu_ready = False
        self.encoder_note.config(text="checking for a GPU encoder…", foreground=self.palette["muted"])
        self._sync_buttons()
        threading.Thread(target=self._detect_gpu, daemon=True).start()

    def about(self) -> None:
        try:
            line = subprocess.run([core.find_tool("ffmpeg"), "-version"], capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=10, **core._SUBPROCESS).stdout.splitlines()[0]
        except Exception:  # noqa: BLE001
            line = "ffmpeg not found on PATH"
        messagebox.showinfo("About vid2mp4", f"vid2mp4 {core.read_version()}\nQuick video encoder: any video to MP4 (H.264 + AAC).\n\n"
                                             f"{line}\nEncoder: {self.gpu or 'x264 (CPU)'}\n\nSettings file:\n{self.settings.path}")

    # ---- file list ----------------------------------------------------------------------------------------------
    def _add(self, paths: list) -> None:
        files, problems = core.collect(paths, self.v_recursive.get())
        known = {p.resolve() for p in self.files.values()}
        added = 0
        for f in files:
            if f.resolve() in known:
                continue
            known.add(f.resolve())
            try:
                size = f.stat().st_size
            except OSError:
                continue
            iid = self.tree.insert("", "end", values=(f.name, "…", core.human_size(size), "Waiting"))
            self.files[iid], self.sizes[iid], self.rstate[iid] = f, size, "waiting"
            self.probe_pool.submit(self._probe_one, iid, f)
            added += 1
        if problems and not added:
            self.status.config(text=problems[0])
        elif added:
            self.status.config(text=f"Added {added} file(s)" if self.files and len(self.files) != added else f"{added} file(s) ready")
        elif files:
            self.status.config(text="Those files are already in the list")
        self._restripe()
        self._refresh_hint()
        self._sync_buttons()

    def _probe_one(self, iid: str, path: Path) -> None:
        try:
            text = describe(core.probe(core.find_tool("ffprobe"), path))
        except Exception:  # noqa: BLE001
            text = "unreadable?"
        self.events.put(("info", iid, text))

    def _restripe(self) -> None:
        for i, iid in enumerate(self.tree.get_children()):
            tags = [t for t in self.tree.item(iid, "tags") if t != "odd"]
            if i % 2:
                tags.append("odd")
            self.tree.item(iid, tags=tags)
        if self.files:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.5, anchor="center")

    def _refresh_hint(self) -> None:
        sel = self.tree.selection()
        if len(sel) == 1 and sel[0] in self.files:
            self.hint.config(text=str(self.files[sel[0]]))
        elif sel:
            self.hint.config(text=f"{len(sel)} selected · {core.human_size(sum(self.sizes[i] for i in sel if i in self.sizes))}")
        elif self.files:
            self.hint.config(text=f"{len(self.files)} file(s) · {core.human_size(sum(self.sizes.values()))}")
        else:
            self.hint.config(text="Reads " + " ".join(sorted(e.lstrip(".") for e in core.VIDEO_EXTS)))

    def _sort(self, col: str) -> None:
        if self._running():
            return
        self.sort_rev = not self.sort_rev if self.sort_col == col else False
        self.sort_col = col
        key = (lambda i: self.files[i].name.lower()) if col == "name" else (lambda i: self.sizes[i])
        for idx, iid in enumerate(sorted(self.files, key=key, reverse=self.sort_rev)):
            self.tree.move(iid, "", idx)
        for c, title in (("name", "File"), ("size", "Size")):
            arrow = (" ▼" if self.sort_rev else " ▲") if c == col else ""
            self.tree.heading(c, text=title + arrow)
        self._restripe()

    def _on_drop(self, event) -> None:
        self._add(list(self.tk.splitlist(event.data)))

    def _initialdir(self) -> str | None:
        d = self.settings["last_dir"]
        return d if d and Path(d).is_dir() else None

    def _remember_dir(self, path: str) -> None:
        self.settings["last_dir"] = str(Path(path).parent if Path(path).is_file() else path)

    def add_files(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(core.VIDEO_EXTS))
        picked = filedialog.askopenfilenames(title="Add videos", initialdir=self._initialdir(),
                                             filetypes=[("Video files", exts), ("All files", "*.*")])
        if picked:
            self._remember_dir(picked[0])
            self._add(list(picked))
            self.save_settings()

    def add_folder(self) -> None:
        picked = filedialog.askdirectory(title="Add a folder of videos", initialdir=self._initialdir())
        if picked:
            self._remember_dir(picked)
            self._add([picked])
            self.save_settings()

    def remove_selected(self) -> None:
        if self._running():
            return
        for iid in self.tree.selection():
            self._forget(iid)
            self.tree.delete(iid)
        self._restripe()
        self._refresh_hint()
        self._sync_buttons()

    def _forget(self, iid: str) -> None:
        for table in (self.files, self.sizes, self.rstate, self.dests, self.errors, self.fraction):
            table.pop(iid, None)

    def clear(self) -> None:
        if self._running():
            return
        for iid in list(self.files):
            self._forget(iid)
        self.tree.delete(*self.tree.get_children())
        self.bar["value"] = 0
        self.status.config(text="Add some videos to begin")
        self._restripe()
        self._refresh_hint()
        self._sync_buttons()

    def pick_output(self) -> None:
        picked = filedialog.askdirectory(title="Output folder", initialdir=self.v_out.get().strip() or self._initialdir())
        if picked:
            self.v_out.set(picked)

    def open_output(self) -> None:
        out = self.v_out.get().strip()
        if out and Path(out).expanduser().is_dir():
            open_folder(Path(out).expanduser())
        elif self.last_out:
            open_folder(self.last_out)
        else:
            self.status.config(text="Nothing to open yet: the output folder does not exist")

    # ---- row actions --------------------------------------------------------------------------------------------
    def _on_double_click(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        if not iid or iid not in self.files:
            return
        if self.rstate.get(iid) == "done" and iid in self.dests:
            reveal(self.dests[iid])
        elif self.rstate.get(iid) == "failed":
            messagebox.showerror("vid2mp4", f"{self.files[iid].name}\n\n{self.errors.get(iid, 'Failed')}")

    def _on_right_click(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        if iid and iid not in self.tree.selection():
            self.tree.selection_set(iid)
        sel = [i for i in self.tree.selection() if i in self.files]
        if not sel:
            return
        m, running = self._menu_tree, self._running()
        m.delete(0, "end")
        first = sel[0]
        if self.rstate.get(first) == "done" and first in self.dests:
            m.add_command(label="Show converted file in folder", command=lambda: reveal(self.dests[first]))
        m.add_command(label="Show source in folder", command=lambda: reveal(self.files[first]))
        m.add_command(label="Copy path", command=lambda: self._copy("\n".join(str(self.files[i]) for i in sel)))
        if self.rstate.get(first) == "failed":
            m.add_command(label="Copy error", command=lambda: self._copy(self.errors.get(first, "")))
        retry = [i for i in sel if self.rstate.get(i) in ("failed", "cancelled", "skipped")]
        if retry and not running:
            m.add_separator()
            m.add_command(label="Reset to Waiting", command=lambda: self._reset_rows(retry))
        m.add_separator()
        m.add_command(label="Remove", command=self.remove_selected, state="disabled" if running else "normal")
        m.tk_popup(event.x_root, event.y_root)

    def _copy(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)

    def _reset_rows(self, iids: list[str]) -> None:
        for iid in iids:
            self._set_status(iid, "waiting", "Waiting")
        self._sync_buttons()

    def _set_status(self, iid: str, state: str, text: str) -> None:
        self.rstate[iid] = state
        self.tree.set(iid, "status", text)
        tags = [t for t in self.tree.item(iid, "tags") if t not in ("done", "failed", "skipped", "running", "cancelled")]
        if state != "waiting":
            tags.append(state)
        self.tree.item(iid, tags=tags)

    # ---- running ------------------------------------------------------------------------------------------------
    def _running(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def _sync_buttons(self) -> None:
        running = self._running()
        ready = self.gpu_ready or self.v_encoder.get() == ENCODERS["cpu"]
        self.start_btn.config(state="normal" if self.files and not running and ready else "disabled")
        self.cancel_btn.config(state="normal" if running and not self.cancel.is_set() else "disabled")
        for b in (self.remove_btn, self.clear_btn):
            b.config(state="disabled" if running else "normal")
        locked = "disabled" if running else "normal"
        readonly = "disabled" if running else "readonly"
        for w in (self.quality_cb, self.encoder_cb, self.after_cb, self.speed_cb):
            w.config(state=readonly)
        for w in (self.mac_cb, self.overwrite_cb, self.reencode_cb, self.recursive_cb, self.jobs_sp, self.crf_sp,
                  self.abr_sp, self.out_entry, self.browse_btn):
            w.config(state=locked)

    def start(self) -> None:
        try:
            core.find_tool("ffmpeg"), core.find_tool("ffprobe")
        except RuntimeError as e:
            messagebox.showerror("vid2mp4", f"{e}.\nInstall ffmpeg and make sure it is on your PATH.")
            return
        cfg, problem = self._config()
        if problem:
            messagebox.showerror("vid2mp4", problem)
            if not self.advanced_open:
                self._toggle_advanced()
            return
        out = Path(self.v_out.get().strip()).expanduser() if self.v_out.get().strip() else None
        if out and out.exists() and not out.is_dir():
            messagebox.showerror("vid2mp4", f"The output folder is a file:\n{out}")
            return
        gpu, copy, overwrite = self._use_gpu(), not self.v_reencode.get(), self.v_overwrite.get()
        todo = [(i, p) for i, p in self.files.items() if self.rstate.get(i) in ("waiting", "failed", "cancelled")]
        if not todo:  # everything was already converted: do it all again (Overwrite decides what happens to old outputs)
            todo = list(self.files.items())
        try:
            jobs = max(1, min(int(self.v_jobs.get() or 1), len(todo)))
        except ValueError:
            jobs = 1
        self.fraction = {}
        for iid, _ in todo:
            self.fraction[iid] = 0.0
            self._set_status(iid, "waiting", "Waiting")
            self.errors.pop(iid, None)
            self.dests.pop(iid, None)
        self.bar["value"] = 0
        self.cancel.clear()
        self.run_started, self.run_total = time.monotonic(), len(todo)
        self.last_out = out
        self.status.config(text=f"Converting {len(todo)} file(s)…")
        self.save_settings()
        self.worker = threading.Thread(target=self._run_all, args=(todo, out, overwrite, cfg, copy, gpu, jobs), daemon=True)
        self.worker.start()
        self._sync_buttons()

    def _run_all(self, todo, out, overwrite, cfg, copy, gpu, jobs) -> None:
        keep_awake(True)

        def work(iid: str, src: Path) -> None:
            if self.cancel.is_set():
                self.events.put(("cancelled", iid, None))
                return
            try:
                res = core.convert(src, out, overwrite, cfg, copy, gpu,
                                   lambda done, total, speed: self.events.put(("progress", iid, (done, total, speed))),
                                   self.cancel)
                self.events.put(("done", iid, res))
            except core.Cancelled:
                self.events.put(("cancelled", iid, None))
            except Exception as e:  # noqa: BLE001
                self.events.put(("error", iid, str(e)))

        try:
            with ThreadPoolExecutor(max_workers=jobs) as pool:
                for iid, src in todo:
                    pool.submit(work, iid, src)
        finally:
            keep_awake(False)
            self.events.put(("finished", None, None))

    def cancel_run(self) -> None:
        if not self._running():
            return
        self.cancel.set()
        self.status.config(text="Cancelling…")
        self.cancel_btn.config(state="disabled")

    # ---- events from the worker threads -------------------------------------------------------------------------
    def _poll(self) -> None:
        try:
            for _ in range(300):
                kind, a, b = self.events.get_nowait()
                getattr(self, f"_on_{kind}")(a, b)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _update_bar(self) -> None:
        if not self.fraction:
            return
        # Weighted by file size, so a tiny file that finished or failed at once does not make a big one look nearly done.
        total = sum(self.sizes.get(i, 1) for i in self.fraction) or 1
        frac = sum(f * self.sizes.get(i, 1) for i, f in self.fraction.items()) / total
        self.bar["value"] = 100 * frac
        if not self._running() or self.cancel.is_set():
            return
        finished = sum(self.rstate.get(i) in ("done", "skipped", "failed", "cancelled") for i in self.fraction)
        text = f"Converting file {min(finished + 1, self.run_total)} of {self.run_total}  ·  {frac:.0%}"
        elapsed = time.monotonic() - self.run_started
        if frac > 0.02:
            text += f"  ·  about {clock(elapsed * (1 - frac) / frac)} left"
        self.status.config(text=text)

    def _on_gpu(self, name: str | None, error: str | None) -> None:
        self.gpu, self.gpu_ready = name, True
        p = self.palette
        if error:
            self.encoder_note.config(text=f"{error}: install ffmpeg", foreground=p["bad"])
        elif name:
            self.encoder_note.config(text=f"found {name}", foreground=p["ok"])
        else:
            self.encoder_note.config(text="no GPU encoder found, using CPU", foreground=p["warn"])
        self._sync_buttons()

    def _on_info(self, iid: str, text: str) -> None:
        if iid in self.files:
            self.tree.set(iid, "info", text)

    def _on_progress(self, iid: str, data) -> None:
        if iid not in self.files:
            return
        done, total, speed = data
        try:
            rate = float(speed.rstrip("x"))
        except ValueError:
            rate = 0.0
        if total:
            frac = min(1.0, done / total)
            self.fraction[iid] = frac
            eta = f"  ~{clock((total - done) / rate)} left" if rate > 0 and frac < 1 else ""
            self._set_status(iid, "running", f"{text_bar(frac)} {frac:4.0%}  {speed}{eta}")
        else:
            self._set_status(iid, "running", f"converting…  {speed}")
        self._update_bar()

    def _on_done(self, iid: str, res: core.Result) -> None:
        if iid not in self.files:
            return
        self.fraction[iid] = 1.0
        if res.status == "skipped":
            self._set_status(iid, "skipped", f"Skipped: {res.message}")
        else:
            self.dests[iid] = res.dest
            if self.last_out is None:
                self.last_out = res.dest.parent
            warn = "  (HDR: may look washed out)" if res.warnings else ""
            self._set_status(iid, "done", f"✓ {core.human_size(res.before)} → {core.human_size(res.after)} "
                                          f"({res.change:+.0f}%)  {core.human_time(res.elapsed)}{warn}")
        self._update_bar()

    def _on_error(self, iid: str, message: str) -> None:
        if iid in self.files:
            self.fraction[iid] = 1.0
            self.errors[iid] = message
            self._set_status(iid, "failed", f"✗ {message}".replace("\n", " "))
            self._update_bar()

    def _on_cancelled(self, iid: str, _data) -> None:
        if iid in self.files:
            self.fraction[iid] = 0.0
            self._set_status(iid, "cancelled", "Cancelled")
            self._update_bar()

    def _on_finished(self, _a, _b) -> None:
        counts = {k: sum(v == k for i, v in self.rstate.items() if i in self.fraction) for k in ("done", "skipped", "failed")}
        cancelled = self.cancel.is_set()
        took = clock(time.monotonic() - self.run_started)
        self.status.config(text=f"{'Cancelled' if cancelled else 'Finished'}: {counts['done']} converted, "
                                f"{counts['skipped']} skipped, {counts['failed']} failed  ·  {took}")
        if not cancelled:
            self.bar["value"] = 100
        self._sync_buttons()
        if cancelled or not counts["done"]:
            return
        after = self._collect()["after"]
        if after == "open" and self.last_out:
            open_folder(self.last_out)
        elif after == "beep":
            try:
                import winsound

                winsound.MessageBeep()
            except Exception:  # noqa: BLE001
                self.bell()

    def _on_close(self) -> None:
        if self._running():
            if not messagebox.askyesno("vid2mp4", "A conversion is running. Cancel it and quit?"):
                return
            self.cancel.set()
            self.worker.join(timeout=5)  # lets each ffmpeg be killed and its .part.mp4 removed
        if self._save_job:
            self.after_cancel(self._save_job)
        self.save_settings()
        self.probe_pool.shutdown(wait=False, cancel_futures=True)
        self.destroy()


def main() -> int:
    if sys.platform == "win32":  # crisp text on high-DPI screens
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
