#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ballastconverter_gui.py – BallastConverter, graphical user interface for ballastconverter.py (negative -> positive following ColorNeg).

Start:   python ballastconverter_gui.py
EXE:     see build_windows.bat (PyInstaller, the ICC profiles are bundled in)

Needs only the Python standard library (tkinter) plus numpy and tifffile for ballastconverter.py.
"""
import os
import sys
import json
import queue
import threading
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter import font as tkfont

import numpy as np

try:
    import sv_ttk                     # modern "Sun Valley" theme (light/dark), optional
except ImportError:
    sv_ttk = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ballastconverter as cn

SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".ballastconverter.json")
OLD_SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".colorneg_gui.json")   # former name, is taken over
IN_CURVES = [("linear (linearly scanned TIFF)", "linear"), ("Gamma 2.2", "2.2"), ("Gamma 1.8", "1.8"),
             ("sRGB curve", "srgb"), ("L* curve", "lstar")]
PREVIEW_LONG_SIDE = 1600        # pixels of the long side for the preview computation
MIN_RECT = 40                   # minimum frame size in preview pixels (1600 px >= 1000 px for a 0.1 % percentile)
CANVAS_W, CANVAS_H = 560, 520
# Colors (design B, always dark)
BG        = "#121212"           # window background
CARD      = "#1c1c1c"           # fill of the theme's rounded card image (Card.TFrame)
CANVAS_BG = "#111111"           # preview area
FG_LABEL  = "#b8b8b8"
FG_MUTED  = "#8a8a8a"
FG_SEC    = "#7c7c7c"           # card headings
ACCENT    = "#57c8ff"


MANUAL = "Manual"
CURVE_TEXT = "Datasheet toe/shoulder curve"
CURVE_TEXT_NA = "Datasheet toe/shoulder curve (no data for this film)"


def spaced(text):
    """Section heading: capitals with thin spaces as letter spacing (Tk has no letter-spacing)."""
    return "\u200a".join(text.upper())


def film_names():
    return [MANUAL] + [f"{m}/{f}" for (m, f) in cn.FILMS]


def bundled_icc(want_output):
    """ICC files in the folder 'profiles' (next to the script or inside the EXE). want_output=True: working color spaces
    (class 'mntr'), otherwise scanner/input profiles. Returns a list of (path, info)."""
    d = cn.profiles_dir()
    out = []
    try:
        for f in sorted(os.listdir(d)):
            if not f.lower().endswith((".icc", ".icm")):
                continue
            path = os.path.join(d, f)
            try:
                info = cn.icc_info(path)
            except Exception:
                continue
            if (info["cls"] == "mntr") == want_output:
                out.append((path, info))
    except OSError:
        pass
    return out


def profile_label(path, info):
    return f'{info["desc"] or os.path.basename(path)}  [{os.path.basename(path)}]'


TIPS = {
    "in": "Scan of the negative as TIFF or 3f/fff, 16 bit recommended. After selection the image is loaded and "
          "converted as a preview on the right.",
    "out": "Target file of the conversion, always a 16-bit TIFF with embedded output profile. Suggested as "
           "<name>_positive.tif when the scan is chosen.",
    "film": "Film profile from the table of the ColorPerfect plugin plus own entries. Sets the three gammas. "
            "\"Manual\" unlocks the gamma fields for input; the last displayed values remain as the starting point.",
    "gamma": "Gamma per channel (R, G, B), the reciprocal of the slope of the film's characteristic curve. Determines "
             "the gradation of the positive; different values per channel compensate for the differing contrasts of the "
             "three color layers. Editable only with film \"Manual\".",
    "curve": "Applies the toe and shoulder of the film's characteristic curve from the manufacturer's datasheet on top "
             "of the three gammas. White and black point stay exactly where they are; only the shape in between "
             "changes, mostly in the deep shadows. Off = plain single-gamma model. Available only for films with "
             "curve data (currently Kodak/Portra 400 (2026)), not with \"Manual\".",
    "incurve": "How the scanner encoded the values. A scanner profile (ICC) linearizes per channel via the "
               "curves of the profile; for 3f/fff the profile recorded in the file is chosen automatically. "
               "\"linear\" for linearly scanned TIFFs.",
    "icc_in": "Choose a different scanner profile (.icc/.icm) from disk.",
    "outprof": "RGB working color space of the output (Adobe RGB, sRGB, ProPhoto RGB). The tone curve is read from "
               "the profile and the profile is embedded in the TIFF file.",
    "icc_out": "Choose a different RGB working color space profile (.icc/.icm) from disk.",
    "expo": "Exposure correction in stops: + brighter, − darker. −1 leaves one stop of headroom so that "
            "no highlights are clipped; then raise the white point in Photoshop.",
    "wp": "Share of the densest pixels in the green frame that is skipped when setting the white anchor "
          "(protection against dust and noise). These pixels end up above white and are clipped when there is "
          "no exposure headroom. Default 0.1 %.",
    "bp": "Share of the thinnest pixels in the green frame that is skipped when setting the black anchor. "
          "The thinnest point is set to neutral black per channel (removes the orange mask); these "
          "pixels end up below black. Default 0.1 %.",
    "run": "Converts the whole scan at full resolution and writes the output file. Only possible once a "
           "frame has been set on the preview.",
}


class Tooltip:
    """Hint text that appears below the widget after a short delay. Tooltip(text, w1, w2, ...)."""
    def __init__(self, text, *widgets, delay=600):
        self.text, self.delay = text, delay
        self.tip = self.after_id = None
        for w in widgets:
            w.bind("<Enter>", lambda e, w=w: self._schedule(w), add="+")
            w.bind("<Leave>", self._hide, add="+")
            w.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, widget):
        self._cancel()
        self.widget = widget
        self.after_id = widget.after(self.delay, self._show)

    def _cancel(self):
        if self.after_id:
            self.widget.after_cancel(self.after_id)
            self.after_id = None

    def _show(self):
        self.after_id = None
        if self.tip:
            return
        w = self.widget
        x = w.winfo_rootx() + 12
        y = w.winfo_rooty() + w.winfo_height() + 4
        self.tip = tk.Toplevel(w)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        ttk.Label(self.tip, text=self.text, justify="left", wraplength=400, padding=(8, 5),
                  relief="solid", borderwidth=1).pack()

    def _hide(self, _=None):
        self._cancel()
        if self.tip:
            self.tip.destroy()
            self.tip = None


def to_ppm(arr8):
    """uint8 HxWx3 -> PPM bytes (Tk can display PPM without an extra library)."""
    h, w = arr8.shape[:2]
    return b"P6 %d %d 255\n" % (w, h) + np.ascontiguousarray(arr8).tobytes()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BallastConverter")
        self.minsize(1100, 720)
        self.q = queue.Queue()
        self.worker = None
        self.cancel_flag = threading.Event()
        self.preview_photo = None
        self.prev_codes = None         # downscaled negative as codes (HxWx3 uint16), basis of the live preview
        self.loaded_path = None
        self.suggested_out = None      # output name the program suggested last (only that one gets replaced)
        self.pending_rect = None       # (path, W, H, rect) from the settings file, applied once the image is loaded
        self._preview_job = None
        self._build()
        self._log(f"BallastConverter {cn.version()}")
        self._load_settings()
        self._apply_theme()
        self._show_rect_text()
        self._poll_job = self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ Layout
    def _build(self):
        """Layout following design B: groups as slightly lighter cards on a dark background, plenty of whitespace."""
        self.configure(bg=BG)
        outer = ttk.Frame(self, style="Root.TFrame", padding=(28, 28, 28, 28))
        outer.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=0)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)
        left = ttk.Frame(outer, style="Root.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 24))
        left.columnconfigure(0, weight=1)
        rowpad = dict(pady=6)

        def card(row, title):
            c = ttk.Frame(left, style="Card.TFrame", padding=(20, 16, 20, 18))
            c.grid(row=row, column=0, sticky="ew", pady=(0, 16))
            c.columnconfigure(1, weight=1)
            ttk.Label(c, text=spaced(title), style="Sec.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
            return c

        LABEL_W = 15                                  # same label column in every card so the fields line up

        def label(parent, text, row, col=0):
            l = ttk.Label(parent, text=text, style="Card.TLabel", width=LABEL_W)
            l.grid(row=row, column=col, sticky="w", padx=(0, 12), **rowpad)
            return l

        # --- Files
        c = card(0, "Files")
        self.v_in = tk.StringVar()
        self.v_out = tk.StringVar()
        l_in = label(c, "Negative scan", 1)
        e_in = ttk.Entry(c, textvariable=self.v_in, width=40)
        e_in.grid(row=1, column=1, sticky="ew", **rowpad)
        for ev in ("<Return>", "<FocusOut>"):
            e_in.bind(ev, lambda *_: self._input_typed())
        b_in = ttk.Button(c, text="…", width=3, command=self._pick_in)
        b_in.grid(row=1, column=2, padx=(8, 0), **rowpad)
        Tooltip(TIPS["in"], l_in, e_in, b_in)
        l_out = label(c, "Output (TIFF)", 2)
        e_out = ttk.Entry(c, textvariable=self.v_out, width=40)
        e_out.grid(row=2, column=1, sticky="ew", **rowpad)
        b_out = ttk.Button(c, text="…", width=3, command=self._pick_out)
        b_out.grid(row=2, column=2, padx=(8, 0), **rowpad)
        Tooltip(TIPS["out"], l_out, e_out, b_out)

        # --- Film
        c = card(2, "Film")
        l_film = label(c, "Film", 1)
        self.v_film = tk.StringVar(value="Kodak/Portra 400 [4056] [5056] [6056]")
        self.cb_film = ttk.Combobox(c, textvariable=self.v_film, values=film_names(), state="readonly", width=36)
        self.cb_film.grid(row=1, column=1, columnspan=2, sticky="ew", **rowpad)
        self.cb_film.bind("<<ComboboxSelected>>", lambda *_: self._on_film_change())
        Tooltip(TIPS["film"], l_film, self.cb_film)
        self.l_gamma = label(c, "Gamma (RGB)", 2)
        self.gf = gf = ttk.Frame(c, style="Inner.TFrame")
        gf.grid(row=2, column=1, columnspan=2, sticky="w", **rowpad)
        self.v_gr, self.v_gg, self.v_gb = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.e_gammas = [ttk.Entry(gf, textvariable=v, width=7) for v in (self.v_gr, self.v_gg, self.v_gb)]
        for e in self.e_gammas:
            e.pack(side="left", padx=(0, 8))
        Tooltip(TIPS["gamma"], self.l_gamma, *self.e_gammas)
        self.v_curve = tk.BooleanVar(value=False)
        self.cb_curve = ttk.Checkbutton(c, text=CURVE_TEXT, variable=self.v_curve, command=self._schedule_preview)
        self.cb_curve.grid(row=3, column=0, columnspan=3, sticky="w", **rowpad)
        Tooltip(TIPS["curve"], self.cb_curve)

        # --- Profiles
        c = card(1, "Profiles")
        l_incurve = label(c, "Input profile", 1)
        self.in_curves = dict(IN_CURVES)             # display name -> curve for cn.convert ('linear', '2.2', 'icc:<path>')
        for path, info in bundled_icc(False):
            self.in_curves[profile_label(path, info)] = "icc:" + path
        self.meta_label = None                       # entry marked as the profile from the metadata
        self.v_incurve = tk.StringVar(value=IN_CURVES[0][0])
        self.cb_in = ttk.Combobox(c, textvariable=self.v_incurve, values=list(self.in_curves), state="readonly", width=36)
        self.cb_in.grid(row=1, column=1, sticky="ew", **rowpad)
        Tooltip(TIPS["incurve"], l_incurve, self.cb_in)
        b_icc_in = ttk.Button(c, text="…", width=3, command=self._pick_icc_in)
        b_icc_in.grid(row=1, column=2, padx=(8, 0), **rowpad)
        Tooltip(TIPS["icc_in"], b_icc_in)
        self.l_prof = ttk.Label(c, text="", style="Hint.TLabel", wraplength=440, justify="left")
        self.l_prof.grid(row=2, column=0, columnspan=3, sticky="w", pady=(0, 6))
        self.l_prof.grid_remove()                    # show the row only when there is a hint
        l_outprof = label(c, "Output profile", 3)
        self.out_profiles = {}                      # display name -> (path, info)
        for path, info in bundled_icc(True):
            self.out_profiles[profile_label(path, info)] = (path, info)
        self.v_outprof = tk.StringVar()
        self.cb_out = ttk.Combobox(c, textvariable=self.v_outprof, values=list(self.out_profiles), state="readonly", width=36)
        self.cb_out.grid(row=3, column=1, sticky="ew", **rowpad)
        self.cb_out.bind("<<ComboboxSelected>>", lambda *_: self._show_out_profile())
        Tooltip(TIPS["outprof"], l_outprof, self.cb_out)
        b_icc_out = ttk.Button(c, text="…", width=3, command=self._pick_out_profile)
        b_icc_out.grid(row=3, column=2, padx=(8, 0), **rowpad)
        Tooltip(TIPS["icc_out"], b_icc_out)
        self.l_outprof = ttk.Label(c, text="", style="Hint.TLabel", wraplength=440, justify="left")
        self.l_outprof.grid(row=4, column=0, columnspan=3, sticky="w", pady=(0, 6))
        self.l_outprof.grid_remove()                 # visible only on a warning or error
        default = [k for k in self.out_profiles if "AdobeRGB1998" in k] or list(self.out_profiles)
        if default:
            self.v_outprof.set(default[0])
        self._show_out_profile()

        # --- Conversion
        c = card(3, "Conversion")
        # Exposure in stops (+ = brighter); internally black = -exposure (plugin: Black 1 = one stop darker)
        self.v_expo = tk.StringVar(value="0")
        self.v_wp = tk.StringVar(value=f"{cn.P_BLACK * 100:g}")      # white point: percentile of the densest points, in %
        self.v_bp = tk.StringVar(value=f"{cn.P_BPOINT * 100:g}")     # black point: percentile of the thinnest points, in %
        l_expo = label(c, "Exposure", 1)
        uf = ttk.Frame(c, style="Inner.TFrame")
        uf.grid(row=1, column=1, columnspan=2, sticky="w", **rowpad)
        cb_expo = ttk.Combobox(uf, textvariable=self.v_expo, width=5, values=["+1", "+0.5", "0", "-0.5", "-1", "-1.5", "-2"])
        cb_expo.pack(side="left", padx=(0, 22))
        Tooltip(TIPS["expo"], l_expo, cb_expo)
        l_wp = ttk.Label(uf, text="White point", style="Card.TLabel")
        l_wp.pack(side="left", padx=(0, 10))
        e_wp = ttk.Entry(uf, textvariable=self.v_wp, width=5)
        e_wp.pack(side="left", padx=(0, 22))
        Tooltip(TIPS["wp"], l_wp, e_wp)
        l_bp = ttk.Label(uf, text="Black point", style="Card.TLabel")
        l_bp.pack(side="left", padx=(0, 10))
        e_bp = ttk.Entry(uf, textvariable=self.v_bp, width=5)
        e_bp.pack(side="left")
        Tooltip(TIPS["bp"], l_bp, e_bp)

        # Statistics region: set only via the frame on the preview (no numeric fields)
        self.v_scrop = [tk.StringVar() for _ in range(4)]

        # --- Action: Convert on the left, progress bar and status line next to it
        left.rowconfigure(4, weight=1)               # remaining space above the action row
        af = ttk.Frame(left, style="Root.TFrame")
        af.grid(row=5, column=0, sticky="ew")
        af.columnconfigure(1, weight=1)
        self.b_run = ttk.Button(af, text="Convert", style="Accent.TButton", command=self._start,
                                state="disabled", width=18)
        self.b_run.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 16), ipady=4)
        Tooltip(TIPS["run"], self.b_run)
        self.pb = ttk.Progressbar(af, mode="determinate", maximum=1000)
        self.pb.grid(row=0, column=1, sticky="ew", pady=(4, 6))
        self.pb.grid_remove()                        # only visible while a conversion runs
        self.l_status = ttk.Label(af, text="", style="Status.TLabel", anchor="w")
        self.l_status.configure(background=BG)       # the widget option overrides the style and carries the theme's grey
        self.l_status.grid(row=1, column=1, sticky="ew")
        self.log_lines = []

        # --- Preview (right, full height) as a card
        pf = ttk.Frame(outer, style="Card.TFrame", padding=(20, 16, 20, 20))
        pf.grid(row=0, column=1, sticky="nsew")
        pf.columnconfigure(0, weight=1)
        pf.rowconfigure(1, weight=1)
        hf = ttk.Frame(pf, style="Inner.TFrame")
        hf.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(hf, text=spaced("Preview"), style="Sec.TLabel").pack(side="left", padx=(0, 16))
        self.l_rect = ttk.Label(hf, text="Mark only the image, without the film rebate and perforation.", style="Hint.TLabel")
        self.l_rect.pack(side="left")
        for v in self.v_scrop:
            v.trace_add("write", lambda *_: self._show_rect_text())
        self.canvas = tk.Canvas(pf, width=CANVAS_W, height=CANVAS_H, bg=CANVAS_BG, cursor="crosshair",
                                highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.canvas.bind("<ButtonPress-1>", self._rect_press)
        self.canvas.bind("<B1-Motion>", self._rect_drag)
        self.canvas.bind("<ButtonRelease-1>", self._rect_release)
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.preview_arr = None
        self._resize_job = None
        self.prev_meta = None          # mapping preview -> original pixels
        self.rect_start = None
        self._on_film_change()
        for v in (self.v_expo, self.v_wp, self.v_bp, self.v_gr, self.v_gg, self.v_gb, self.v_incurve, self.v_outprof,
                  *self.v_scrop):
            v.trace_add("write", lambda *_: self._schedule_preview())

    # ------------------------------------------------------------------ Theme
    def _apply_theme(self):
        """Always dark. Card styles (design B) on the Sun Valley theme, fallback 'clam'."""
        if sv_ttk:
            sv_ttk.set_theme("dark")
        else:
            try:
                ttk.Style(self).theme_use("clam")
            except tk.TclError:
                pass
        st = ttk.Style(self)
        base = tkfont.nametofont("TkDefaultFont")
        # keep a reference: a named font that is garbage-collected disappears from Tk and the label falls back
        self.font_sec = base.copy()
        self.font_sec.configure(size=-11, weight="normal")           # 11 px like the mockup
        small = self.font_sec
        st.configure("Root.TFrame", background=BG)
        if not sv_ttk:                               # sv_ttk brings its own rounded Card.TFrame
            st.configure("Card.TFrame", background=CARD)
        st.configure("Inner.TFrame", background=CARD)
        st.configure("Card.TLabel", background=CARD, foreground=FG_LABEL)
        st.configure("Sec.TLabel", background=CARD, foreground=FG_SEC, font=small)
        st.configure("Hint.TLabel", background=CARD, foreground=FG_MUTED)
        st.configure("Status.TLabel", background=BG, foreground=FG_MUTED)
        if not sv_ttk:
            st.configure("Accent.TButton", background=ACCENT, foreground="#0b1a22")
        self.configure(bg=BG)
        self.canvas.configure(bg=CANVAS_BG)

    # ------------------------------------------------------------------ Helpers
    def _log(self, text):
        """Messages: the last line is shown below the progress bar, all of them stay in log_lines."""
        self.log_lines.append(text)
        last = text.strip().splitlines()[-1] if text.strip() else ""
        self.l_status.configure(text=last)

    def _pick_in(self):
        p = filedialog.askopenfilename(title="Negative scan", filetypes=[
            ("Scans", "*.tif *.tiff *.fff *.3f *.TIF *.TIFF *.FFF"), ("All files", "*.*")])
        if p:
            self.v_in.set(p)
            self._use_input(p)

    def _input_typed(self):
        """Path typed in by hand: load the file if it exists and is not loaded yet."""
        p = self.v_in.get().strip()
        if p and os.path.isfile(p) and p != self.loaded_path:
            self._use_input(p)

    def _use_input(self, p):
        """New scan chosen: suggest the output name (unless the user typed their own), detect the profile, load."""
        base, _ = os.path.splitext(p)
        suggestion = base + "_positive.tif"
        if not self.v_out.get().strip() or self.v_out.get().strip() == self.suggested_out:
            self.v_out.set(suggestion)
        self.suggested_out = suggestion
        self._detect_profile(p)
        self._load_preview(p)

    def _detect_profile(self, path):
        """3f/fff: read the profile name from the metadata and choose the matching ICC from 'profiles' or next to the scan."""
        self._mark_meta_profile(None)
        name, _ = cn.scan_input_profile(path)
        if not name:
            self._hint("No scanner profile recorded in the file (not a 3f/fff). "
                                       "Choose the input profile by hand: linear for linearly scanned TIFFs.")
            return
        icc = cn.find_icc_by_name(name, [cn.profiles_dir(), os.path.dirname(path)])
        if icc:
            self._select_in_curve("icc:" + icc)
            self._mark_meta_profile(self.v_incurve.get())
            self._hint("")
            self._log(f"Input profile from the 3f file: {name} -> {icc}")
        else:
            self._hint(f"Scanner profile according to the file: \"{name}\", but no file \"{name}.icc\" "
                                       "in the folder profiles or next to the scan. Please choose via \"…\".")
            self._log(f"Input profile according to the 3f file: {name} (ICC file not found)")

    def _hint(self, text, label=None):
        """Hint line below the input or output profile: with empty text the line is hidden entirely."""
        label = label or self.l_prof
        label.configure(text=text)
        if text:
            label.grid()
        else:
            label.grid_remove()

    META_SUFFIX = "  (from the file's metadata)"

    def _mark_meta_profile(self, label):
        """Appends to the entry 'label' the note that it comes from the scan's metadata (None: remove the mark)."""
        if self.meta_label:
            old = self.meta_label + self.META_SUFFIX
            if old in self.in_curves:
                self.in_curves = {(self.meta_label if k == old else k): v for k, v in self.in_curves.items()}
            if self.v_incurve.get() == old:
                self.v_incurve.set(self.meta_label)
        self.meta_label = label if label in self.in_curves else None
        if self.meta_label:
            new = self.meta_label + self.META_SUFFIX
            self.in_curves = {(new if k == self.meta_label else k): v for k, v in self.in_curves.items()}
            if self.v_incurve.get() == self.meta_label:
                self.v_incurve.set(new)
        self.cb_in["values"] = list(self.in_curves)

    def _pick_out(self):
        p = filedialog.asksaveasfilename(title="Output", defaultextension=".tif",
                                         filetypes=[("TIFF", "*.tif *.tiff")])
        if p:
            self.v_out.set(p)

    def _pick_icc_in(self):
        p = filedialog.askopenfilename(title="Scanner profile (ICC)", filetypes=[("ICC", "*.icc *.icm"), ("All", "*.*")])
        if p:
            self._select_in_curve("icc:" + p)

    def _select_in_curve(self, curve):
        """Select the curve ('linear', '2.2', 'icc:<path>') in the input field; unknown ICC files are added."""
        for key, val in self.in_curves.items():
            if val == curve or (val.startswith("icc:") and curve.startswith("icc:")
                                and os.path.normcase(val[4:]) == os.path.normcase(curve[4:])):
                self.v_incurve.set(key)
                return True
        if curve.startswith("icc:"):
            path = curve[4:]
            try:
                info = cn.icc_info(path)
            except Exception as e:
                messagebox.showerror("Profile", f"Profile cannot be read:\n{e}")
                return False
            key = profile_label(path, info)
            self.in_curves[key] = curve
            self.cb_in["values"] = list(self.in_curves)
            self.v_incurve.set(key)
            return True
        return False

    def _in_curve(self):
        return self.in_curves.get(self.v_incurve.get(), "linear")

    def _pick_out_profile(self):
        p = filedialog.askopenfilename(title="Output profile (RGB working color space)", filetypes=[("ICC", "*.icc *.icm"), ("All", "*.*")])
        if p:
            self._add_out_profile(p, select=True)

    def _add_out_profile(self, path, select=False):
        try:
            info = cn.icc_info(path)
        except Exception as e:
            messagebox.showerror("Profile", f"Profile cannot be read:\n{e}")
            return None
        key = profile_label(path, info)
        self.out_profiles[key] = (path, info)
        self.cb_out["values"] = list(self.out_profiles)
        if select:
            self.v_outprof.set(key)
            self._show_out_profile()
        return key

    def _out_profile_path(self):
        ent = self.out_profiles.get(self.v_outprof.get())
        return ent[0] if ent else None

    def _show_out_profile(self):
        ent = self.out_profiles.get(self.v_outprof.get())
        if not ent:
            self._hint("No output profile found. Please choose an RGB profile via \"…\".", self.l_outprof)
            return
        path, info = ent
        warn = ""
        if info["cls"] != "mntr":
            warn = "Warning: not an RGB working color space (class " + info["cls"].strip() + "), unsuitable as output profile."
        elif not info["matrix"]:
            warn = "Warning: profile without matrix, unsuitable as output profile."
        elif info["curve"].startswith("Curve not readable"):
            warn = "Warning: tone curve of the profile not readable."
        self._hint(warn, self.l_outprof)

    def _on_film_change(self):
        """Film profile: take the gammas from the table and hide the gamma row. 'Manual': show the row for
        editing; the last displayed values remain as the starting point."""
        self._update_curve_state()
        if self.v_film.get() == MANUAL:
            self.l_gamma.grid()
            self.gf.grid()
            self._schedule_preview()                # the gammas do not change here, but the curve setting may
            return
        try:
            g = cn.find_film(self.v_film.get())
            for v, x in zip((self.v_gr, self.v_gg, self.v_gb), g):
                v.set(f"{x:.3f}")
        except cn.ConversionError as e:
            self._log(str(e))
        self.l_gamma.grid_remove()
        self.gf.grid_remove()

    def _film_curve(self):
        """Curve file of the selected film, None for 'Manual' or films without curve data."""
        film = self.v_film.get()
        return None if film == MANUAL else cn.film_curve_path(film)

    def _update_curve_state(self):
        """The curve checkbox is only active for films with curve data; the tick itself is kept for later."""
        if self._film_curve():
            self.cb_curve.configure(text=CURVE_TEXT, state="normal")
        else:
            self.cb_curve.configure(text=CURVE_TEXT_NA, state="disabled")

    @staticmethod
    def _four(vs):
        vals = [v.get().strip() for v in vs]
        if not any(vals):
            return None
        if not all(vals):
            raise ValueError("Region: please give all four values or leave all of them empty")
        return [int(float(x)) for x in vals]

    @staticmethod
    def _num(var, name, empty=None):
        t = var.get().strip().replace(",", ".").replace("+", "")
        if not t:
            if empty is None:
                raise ValueError(f"{name}: please enter a value")
            return empty
        try:
            return float(t)
        except ValueError:
            raise ValueError(f"{name}: please enter a number")

    def _params(self, for_preview=False):
        """Reads all fields, validates them and returns the arguments for cn.convert."""
        inp = self.v_in.get().strip()
        out = self.v_out.get().strip()
        if not for_preview:
            if not inp or not os.path.isfile(inp):
                raise ValueError("Please choose an existing negative scan")
            if not out:
                raise ValueError("Please specify an output file")
            if os.path.normcase(os.path.abspath(inp)) == os.path.normcase(os.path.abspath(out)) or \
                    (os.path.exists(out) and os.path.samefile(inp, out)):
                raise ValueError("The output file must not be the scan itself (it would be overwritten)")
            if self.prev_codes is None:
                raise ValueError("Please wait until the scan is loaded")
            if not self._has_rect():
                raise ValueError("Please first drag a frame around the image on the preview")
        if self.v_film.get() == MANUAL:
            man = [v.get().strip() for v in (self.v_gr, self.v_gg, self.v_gb)]
            if not all(man):
                raise ValueError("Gammas: please enter all three values (or choose a film profile)")
            try:
                gammas = [float(x.replace(",", ".")) for x in man]
            except ValueError:
                raise ValueError("Gammas: please enter numbers, e.g. 1.70")
            if any(not (0.1 <= g <= 10.0) for g in gammas):
                raise ValueError("Gammas must be between 0.1 and 10")
            film = None
        else:
            gammas, film = None, self.v_film.get()
        gam = cn.resolve_gammas(film, gammas, log=self._log)
        p = dict(
            input_path=inp, output_path=out, gammas=gam,
            in_curve=self._in_curve(),
            out_curve="icc:" + (self._out_profile_path() or ""),
            p_black=self._num(self.v_wp, "White point") / 100.0, p_bpoint=self._num(self.v_bp, "Black point") / 100.0,
            black=-self._num(self.v_expo, "Exposure", empty=0.0) + 0.0,      # + 0.0: turns -0.0 into 0.0
            use_bpoint=True, bits=16,
            crop=None, stats_crop=self._four(self.v_scrop),
            embed_icc="auto",
            film_curve=self._film_curve() if self.v_curve.get() else None,
        )
        if not (0 < p["p_black"] <= 0.5 and 0 < p["p_bpoint"] <= 0.5):
            raise ValueError("White point and black point must be between 0 and 50 (percent)")
        if not self._out_profile_path():
            raise ValueError("Please choose an output profile")
        ic = p["in_curve"]
        if ic.startswith("icc:") and not os.path.isfile(ic[4:]):
            raise ValueError(f"Scanner profile not found: {ic[4:]}")
        return p, film, gammas

    # ------------------------------------------------------------------ Workflow
    def _start(self):
        if self.worker and self.worker.is_alive():
            self._log("A conversion is still running")
            return
        try:
            p, *_ = self._params()
        except (ValueError, cn.ConversionError) as e:
            messagebox.showerror("Input", str(e))
            return
        if os.path.exists(p["output_path"]):
            if not messagebox.askyesno("Overwrite?", f"{os.path.basename(p['output_path'])} already exists.\nReplace it?"):
                return
        self.cancel_flag.clear()
        self._set_busy(True)
        self.pb["value"] = 0
        self._log("Conversion started …")
        self.worker = threading.Thread(target=self._work, args=(p,), daemon=True)
        self.worker.start()

    def _work(self, p):
        try:
            info = cn.convert(log=lambda t: self.q.put(("log", t)),
                              progress=lambda f: self.q.put(("prog", f)),
                              cancel=self.cancel_flag.is_set, **p)
            if info is None:
                self.q.put(("log", "cancelled"))
            self.q.put(("done", info is not None))
        except cn.ConversionError as e:
            self.q.put(("error", str(e)))
        except BaseException as e:
            self.q.put(("log", traceback.format_exc()))
            self.q.put(("error", f"{type(e).__name__}: {e}"))

    # ------------------------------------------------------------------ Live preview
    def _load_preview(self, path):
        """Load the negative in the background, downscale to PREVIEW_LONG_SIDE and keep it as codes."""
        self.prev_codes = None
        self.preview_arr = None
        self.loaded_path = path
        self.canvas.delete("all")
        if not (self.pending_rect and self.pending_rect[0] == path):
            self.pending_rect = None
        for v in self.v_scrop:                       # the frame belongs to the previous image
            v.set("")
        self._update_run_state()
        self._log(f"loading {os.path.basename(path)} …")
        threading.Thread(target=self._load_work, args=(path,), daemon=True).start()

    def _load_work(self, path):
        try:
            img = cn.read_image(path)
            h, w = img.shape[0], img.shape[1]
            s = max(1, int(np.ceil(max(h, w) / PREVIEW_LONG_SIDE)))
            codes = cn.to_codes(np.asarray(img[::s, ::s]))
            del img
            self.q.put(("loaded", (path, codes, w, h, s)))
        except cn.ConversionError as e:
            self.q.put(("load_error", (path, str(e))))
        except BaseException as e:                   # SystemExit included: a silent thread death leaves the GUI stuck
            self.q.put(("load_error", (path, f"{type(e).__name__}: {e}")))

    def _preview_stats(self, rect):
        """Frame in original pixels -> (y0, y1, x0, x1) in preview pixels; start rounded up so the region never
        includes a row or column outside the drawn frame."""
        if not rect:
            return None
        x0, y0, x1, y1 = rect
        s = self.prev_meta["subsample"]
        up = lambda v: -(-max(v, 0) // s)
        return (up(y0), max(y1, 0) // s, up(x0), max(x1, 0) // s)

    def _schedule_preview(self):
        """Recompute the preview after a short pause (coalesces rapid input)."""
        if self.prev_codes is None:
            return
        if self._preview_job:
            self.after_cancel(self._preview_job)
        self._preview_job = self.after(250, self._update_preview)

    def _update_preview(self):
        self._preview_job = None
        if self.prev_codes is None:
            return
        try:
            p, *_ = self._params(for_preview=True)
        except (ValueError, cn.ConversionError):
            return                                  # incomplete input: keep the old preview
        stats = self._preview_stats(p["stats_crop"])
        try:
            arr, info = cn.convert_codes(self.prev_codes, p["gammas"], p["in_curve"], p["out_curve"],
                                         p["p_black"], p["p_bpoint"], p["black"], stats=stats, bits=8,
                                         film_curve=p["film_curve"])
        except Exception as e:
            self._log(f"Preview: {e}")
            return
        self.preview_arr = np.ascontiguousarray(arr)
        self._render_preview()

    def _poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self._log(val)
                elif kind == "prog":
                    self.pb["value"] = int(val * 1000)
                elif kind == "loaded":
                    path, codes, w, h, s = val
                    if path != self.loaded_path:
                        continue                    # a different file was chosen in the meantime
                    self.prev_codes = codes
                    self.prev_meta = dict(subsample=s, off=(0, 0), W=w, H=h)
                    self._log(f"loaded: {w}x{h}, preview {codes.shape[1]}x{codes.shape[0]}")
                    pr, self.pending_rect = self.pending_rect, None
                    if pr and pr[0] == path and pr[1] == w and pr[2] == h:
                        for v, x in zip(self.v_scrop, pr[3]):
                            v.set(x)                # saved frame for exactly this image
                    self._update_run_state()
                    self._update_preview()
                elif kind == "load_error":
                    path, msg = val
                    if path == self.loaded_path:
                        self.loaded_path = None     # so the same file can be tried again
                    self._log("ERROR: " + msg)
                    messagebox.showerror("Cannot load the scan", msg)
                elif kind == "error":
                    self._log("ERROR: " + val)
                    messagebox.showerror("Conversion failed", val)
                    self._set_busy(False)
                elif kind == "done":
                    self._set_busy(False)
                    if val:
                        self._log("done.")
        except queue.Empty:
            pass
        self._poll_job = self.after(100, self._poll)

    def _set_busy(self, busy):
        self.is_busy = busy
        self._update_run_state()
        if busy:
            self.pb.grid()
        else:
            self.pb.grid_remove()

    def _has_rect(self):
        return all(v.get().strip() for v in self.v_scrop)

    def _update_run_state(self):
        """Convert only when nothing is running, an image is loaded and a frame is set."""
        ok = not getattr(self, "is_busy", False) and self._has_rect() and self.prev_codes is not None
        self.b_run.configure(state="normal" if ok else "disabled")

    def _render_preview(self):
        """Fit the preview continuously into the canvas area (nearest neighbor, no upscaling)."""
        if self.preview_arr is None:
            return
        h, w = self.preview_arr.shape[:2]
        cw = max(self.canvas.winfo_width(), 50)
        ch = max(self.canvas.winfo_height(), 50)
        f = min(cw / w, ch / h, 1.0)
        dw, dh = max(int(w * f), 1), max(int(h * f), 1)
        ys = np.minimum((np.arange(dh) / f).astype(int), h - 1)
        xs = np.minimum((np.arange(dw) / f).astype(int), w - 1)
        arr = self.preview_arr[ys][:, xs]
        self.preview_photo = tk.PhotoImage(data=to_ppm(arr))
        ox, oy = (cw - dw) // 2, (ch - dh) // 2
        self.canvas.delete("all")
        self.canvas.create_image(ox, oy, image=self.preview_photo, anchor="nw")
        m = self.prev_meta or dict(subsample=1, off=(0, 0), W=w, H=h)
        m.update(scale=m["subsample"] / f, ox=ox, oy=oy, dw=dw, dh=dh)
        self.prev_meta = m
        self._draw_rects()

    def _on_canvas_resize(self, _ev):
        if self.preview_arr is None:
            return
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(120, self._render_preview)

    # ------------------------------------------------------------------ Rectangle on the preview
    def _to_canvas(self, X, Y):
        """Original pixels -> canvas coordinates."""
        m = self.prev_meta
        return m["ox"] + (X - m["off"][0]) / m["scale"], m["oy"] + (Y - m["off"][1]) / m["scale"]

    def _to_image(self, x, y):
        """Canvas -> original pixels, limited to the preview image."""
        m = self.prev_meta
        x = min(max(x, m["ox"]), m["ox"] + m["dw"])
        y = min(max(y, m["oy"]), m["oy"] + m["dh"])
        X = int(round(m["off"][0] + (x - m["ox"]) * m["scale"]))
        Y = int(round(m["off"][1] + (y - m["oy"]) * m["scale"]))
        return min(X, m["off"][0] + m["W"]), min(Y, m["off"][1] + m["H"])

    def _show_rect_text(self):
        if hasattr(self, "b_run"):
            self._update_run_state()

    def _draw_rects(self):
        self.canvas.delete("rect")
        if not self.prev_meta or "scale" not in self.prev_meta:
            return
        try:
            r = self._four(self.v_scrop)
        except ValueError:
            r = None
        if r:
            x0, y0 = self._to_canvas(r[0], r[1])
            x1, y1 = self._to_canvas(r[2], r[3])
            self.canvas.create_rectangle(x0, y0, x1, y1, outline="#39e639", width=2, tags="rect")

    def _rect_press(self, ev):
        if not self.prev_meta or "scale" not in self.prev_meta:
            return
        self.rect_start = (ev.x, ev.y)
        self.canvas.delete("drag")

    def _rect_drag(self, ev):
        if not self.rect_start:
            return
        self.canvas.delete("drag")
        self.canvas.create_rectangle(*self.rect_start, ev.x, ev.y, outline="#39e639", dash=(4, 3), width=2, tags="drag")

    def _rect_release(self, ev):
        if not self.rect_start:
            return
        (sx, sy), self.rect_start = self.rect_start, None
        self.canvas.delete("drag")
        if abs(ev.x - sx) < 4 or abs(ev.y - sy) < 4:
            return
        X0, Y0 = self._to_image(min(sx, ev.x), min(sy, ev.y))
        X1, Y1 = self._to_image(max(sx, ev.x), max(sy, ev.y))
        s = self.prev_meta["subsample"]
        if (X1 - X0) // s < MIN_RECT or (Y1 - Y0) // s < MIN_RECT:
            self._log(f"Frame too small: at least {MIN_RECT}x{MIN_RECT} preview pixels")
            return
        for v, x in zip(self.v_scrop, (X0, Y0, X1, Y1)):
            v.set(str(x))
        self._draw_rects()

    # ------------------------------------------------------------------ Settings
    def _settings(self):
        return dict(
            input=self.v_in.get(), output=self.v_out.get(), film=self.v_film.get(),
            gammas=[self.v_gr.get(), self.v_gg.get(), self.v_gb.get()], datasheet_curve=bool(self.v_curve.get()),
            in_curve=self._portable_icc(self._in_curve()), out_profile=self._portable_icc(self._out_profile_path() or ""),
            exposure=self.v_expo.get(), white_pct=self.v_wp.get(), black_pct=self.v_bp.get(),
            stats_crop=[v.get() for v in self.v_scrop],
            stats_image=dict(path=self.loaded_path or "", W=(self.prev_meta or {}).get("W", 0),
                             H=(self.prev_meta or {}).get("H", 0)),
        )

    @staticmethod
    def _portable_icc(value):
        """Bundled profiles are stored by name only: inside the one-file EXE their folder changes on every start."""
        prefix = "icc:" if value.startswith("icc:") else ""
        path = value[len(prefix):]
        if path and os.path.normcase(os.path.dirname(os.path.abspath(path))) == os.path.normcase(cn.profiles_dir()):
            return prefix + os.path.basename(path)
        return value

    def _load_settings(self):
        try:
            src = SETTINGS_FILE if os.path.isfile(SETTINGS_FILE) else OLD_SETTINGS_FILE
            s = json.load(open(src, encoding="utf-8"))
        except Exception:
            return
        try:
            self.v_in.set(s.get("input", "")); self.v_out.set(s.get("output", ""))
            if s.get("film") in film_names():
                self.v_film.set(s["film"])
            if self.v_film.get() == MANUAL:
                for v, x in zip((self.v_gr, self.v_gg, self.v_gb), s.get("gammas", ["", "", ""])): v.set(x)
            self.v_curve.set(bool(s.get("datasheet_curve", False)))
            ic = s.get("in_curve", "linear")
            if ic.startswith("icc:"):
                ic = "icc:" + cn.resolve_icc(ic[4:])
            if not ic.startswith("icc:") or os.path.isfile(ic[4:]):
                self._select_in_curve(ic)
            op = s.get("out_profile", "")
            op = cn.resolve_icc(op) if op else ""
            if op and os.path.isfile(op):
                keys = [k for k, (pth, _) in self.out_profiles.items() if os.path.normcase(pth) == os.path.normcase(op)]
                if keys:
                    self.v_outprof.set(keys[0]); self._show_out_profile()
                else:
                    self._add_out_profile(op, select=True)
            self.v_expo.set(s.get("exposure", "0"))
            self.v_wp.set(s.get("white_pct", f"{cn.P_BLACK * 100:g}")); self.v_bp.set(s.get("black_pct", f"{cn.P_BPOINT * 100:g}"))
            rect = s.get("stats_crop", [""] * 4)
            si = s.get("stats_image", {})
            if all(rect) and si.get("path") == self.v_in.get():
                self.pending_rect = (si["path"], si.get("W"), si.get("H"), rect)     # applied after loading
            self._on_film_change()
            if os.path.isfile(self.v_in.get()):
                stem = os.path.splitext(self.v_in.get())[0]
                # an output next to the scan that starts with its name counts as "suggested": a new scan replaces it
                self.suggested_out = self.v_out.get().strip() if self.v_out.get().strip().startswith(stem) else stem + "_positive.tif"
                self._detect_profile(self.v_in.get())
                self._load_preview(self.v_in.get())
        except Exception:
            pass

    def _on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("Conversion running", "A conversion is still running.\nStop it and quit? "
                                                             "The unfinished output file will be deleted."):
                return
            self.cancel_flag.set()
            self.worker.join(timeout=15)
        try:
            json.dump(self._settings(), open(SETTINGS_FILE, "w", encoding="utf-8"), indent=1)
        except Exception:
            pass
        if self._poll_job:
            self.after_cancel(self._poll_job)
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
