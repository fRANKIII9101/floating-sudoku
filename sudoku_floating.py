"""Floating Sudoku — a small always-on-top, draggable, semi-transparent
sudoku widget built with tkinter.

Two modes:
  * 普通 (normal)  — standard sudoku with given digits
  * 杀手 (killer)  — killer sudoku: only cage outlines + sums are shown

Features:
  * undo / redo (Ctrl+Z / Ctrl+Y)
  * live highlight of the selected row / column / 3x3 box + same digits
  * pencil marks (Ctrl to toggle / Ctrl+digit; auto-candidates on demand)
  * Shift+click multiple cells to batch-add pencil marks
  * QWE/ASD/ZXC nine-grid keyboard input
  * all-green feedback when a digit is fully placed; digonal win animation
  * size presets (小/中/大) + fine adjust
  * transparency slider (down to 15%)
  * double-space hides; system-tray icon restores it
  * auto-save / resume

Run:  python sudoku_floating.py
"""

import json
import os
import queue
import sys
import threading
import time
import random

import tkinter as tk
from tkinter import font as tkfont

import sudoku_core
import killer_core

FONT_FAMILY = "Segoe UI"
CELL = 38            # px per cell at scale 1.0
BASE_VAL_PT = 17     # value font size at scale 1.0
BASE_SUM_PT = 8      # cage-sum font size at scale 1.0
BASE_CAND_PT = 8      # candidate (auto-pencil) font size at scale 1.0
SUM_PT_MIN = 8       # below this the two-digit cage sums stop fitting
CAND_PT_MIN = 7      # candidates have 9 slots to share, so they may go smaller
HL_PX = 2            # fixed highlight ring width — must NOT vary, or the
                     # inner content box shrinks and every placed child shifts
BG_COLOR = "#2b2b2b"  # window background (used by the win animation)

# Pastel palette for killer cages. The palette index is chosen by graph
# colouring (see _make_cage_colors) so that two cages that touch — even just
# at a corner — never get the same colour. A plain hue rotation made some
# neighbouring ids come out visually identical.
CAGE_PALETTE = [
    "#dbeafe", "#fce7f3", "#dcfce7", "#fef3c7", "#ede9fe",
    "#ffe4e6", "#ccfbf1", "#e2e8f0", "#fee2e2", "#e0f2fe",
    "#f3e8ff", "#ffedd5",
]
CAGE_LINE = "#546e7a"   # cage outline
EDGE_PX = 2             # cage outline thickness
PN_PAD = 1              # internal x-padding of the cage-sum label

VAL_FG_GIVEN = "#111111"
VAL_FG_USER = "#1565c0"
AUTO_FG = "#455a64"     # auto candidates (grey)
PENCIL_FG = "#7b1fa2"   # your own pencil marks (purple)
PEER_BG = "#cfe4fb"     # same row / column / 3x3 box tint
SEL_BG = "#ffe9a8"      # selected cell
CONFLICT_BG = "#ffd6d6"
CONFLICT_FG = "#cc0000"
FLASH_BG = "#b9f6ca"    # a digit completed nine-for-nine
FLASH_SEC = 0.85        # how long that green feedback stays up
VANISH_STEP_MS = 26     # per diagonal step of the win animation

# Q W E / A S D / Z X C -> 1..9, a 3x3 "nine-grid" keyboard layout
NINE_GRID_KEYS = {"q": 1, "w": 2, "e": 3, "a": 4, "s": 5, "d": 6,
                  "z": 7, "x": 8, "c": 9}

# Shift+1..9 arrive as "!", "@", ... — still pencil marks, not garbage input
SHIFT_DIGITS = {"exclam": 1, "at": 2, "numbersign": 3, "dollar": 4,
                "percent": 5, "asciicircum": 6, "ampersand": 7,
                "asterisk": 8, "parenleft": 9}

SIZE_PRESETS = [("小", 0.8), ("中", 1.0), ("大", 1.3)]
SIZE_STEP = 0.05
SCALE_MIN, SCALE_MAX = 0.7, 2.0

DIFFS = ["easy", "medium", "hard", "expert"]
DIFF_NAMES = {"easy": "简单", "medium": "中等", "hard": "困难", "expert": "专家"}
MODES = [("normal", "普通"), ("killer", "杀手")]
MODE_NAMES = dict(MODES)

# 杀手数独各难度预设的「给定数字」数量（作为提示）。
# 专家级不预置，保持纯笼题难度；简单/中等给几个数字降低入门门槛。
_KILLER_GIVENS = {"easy": 12, "medium": 8, "hard": 4, "expert": 0}


NAMED_COLORS = {"white": "#ffffff", "black": "#000000"}

CELL_BG_DEFAULT = "#ffffff"   # normal-mode cell background (hex: it gets blended)

def _to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in rgb)


def _parse_hex(h):
    h = NAMED_COLORS.get(h, h).lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _mix(a, b, t):
    """Blend colours `a` and `b`; t=0 -> a, t=1 -> b."""
    ra, rb = _parse_hex(a), _parse_hex(b)
    return _to_hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))


def default_save_path():
    """Where the auto-save lives. Override with the SUDOKU_SAVE_PATH env var
    (used by selftest.py so tests never touch the real save slot)."""
    override = os.environ.get("SUDOKU_SAVE_PATH")
    if override:
        return override
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
        else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "sudoku_save.json")


class SudokuApp:
    def __init__(self, root):
        self.root = root
        self.root.title("数独")
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.96)
        self.root.overrideredirect(True)
        self.root.configure(bg="#2b2b2b")

        self.mode = "normal"
        self.difficulty = "medium"
        self.topmost = True
        self.selected = None
        self.alpha = tk.DoubleVar(value=96)

        self.scale = 1.0
        # cell geometry cache — filled by _relayout(), but seeded here because
        # _restore_or_new() may render before _relayout() ever runs.
        self._cell = CELL
        self._inner = CELL - 2 * HL_PX
        self._slot = self._inner // 3
        # cage-sum strip geometry — seeded here because _restore_or_new() may
        # render before _relayout() ever runs (same reason as the cell cache)
        self._sum_h = 0
        self._sum_w = 6
        self._sum_pad = 4          # the sum label's own padx contribution
        self._sum_band = False
        self._last_space = 0
        self.undo_stack = []
        self.redo_stack = []

        self.font_val = (FONT_FAMILY, BASE_VAL_PT)
        self.font_sum = (FONT_FAMILY, BASE_SUM_PT)
        self.font_cand = (FONT_FAMILY, BASE_CAND_PT)
        self.show_candidates = False
        self.cand_labels = {}
        self.cage_edges = {}
        self.cage_edge_plan = {}
        self.done_digits = set()  # digits already given the green "9/9" flash
        # your own pencil marks (a set of digits per cell), independent of the
        # "候选" auto-pencil toggle
        self.pencils = [[set() for _ in range(9)] for _ in range(9)]
        self.pencil_mode = False     # Shift toggles this on/off
        self.nine_grid = False       # QWE/ASD/ZXC -> 1..9 typing
        self.vanished = set()        # cells already wiped by the win animation
        self.flash = {}              # (r, c) -> deadline; green "digit done"
        self._flash_job = None
        self._anim_job = None
        self._ctrl_down = False
        self._ctrl_used = False
        self.selection = set()
        self._suppress_deselect = False

        self.tray = None
        self.tray_ok = False
        self.hotkey_label = None
        # tkinter is not thread-safe: the tray / hotkey threads must not touch
        # widgets directly, so they post callables here and the Tk thread drains
        # the queue from a timer.
        self._ui_queue = queue.Queue()

        self.save_path = default_save_path()

        self._build_header()
        self._build_controls()
        self._build_grid()
        self._build_pad()
        self._build_status()
        self._mark_buttons()

        self.root.bind("<Key>", self._on_key)
        self.root.bind("<KeyRelease>", self._on_key_release)
        # An overrideredirect window is not given keyboard focus by the window
        # manager, so typing 1-9 / arrows / double-space would go nowhere.
        # Take focus explicitly, and re-take it whenever the user clicks us.
        self.root.bind("<Button-1>", self._on_root_click, add="+")

        self._restore_or_new()
        self._relayout()
        self._render()
        self._update_size_label()
        self._center()
        self.root.focus_force()

        self.tray_ok = self._setup_tray()
        self._setup_hotkey()
        self.can_restore = bool(self.tray_ok or self.hotkey_label)
        self._update_status_hint()
        self.root.after(80, self._pump_ui)

    # ---------- cross-thread bridge ----------
    def _ui_post(self, fn):
        """Queue `fn` to run on the Tk thread."""
        self._ui_queue.put(fn)

    def _pump_ui(self):
        while True:
            try:
                fn = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:
                pass
        self.root.after(80, self._pump_ui)

    # ---------- construction ----------
    def _build_header(self):
        hdr = tk.Frame(self.root, bg="#1f1f1f", height=26)
        hdr.pack(fill="x")
        hdr.bind("<ButtonPress-1>", self._start_drag)
        hdr.bind("<B1-Motion>", self._do_drag)

        tk.Label(hdr, text="数独", fg="white", bg="#1f1f1f",
                 font=("Segoe UI", 10, "bold")).pack(side="left", padx=8)
        tk.Button(hdr, text="×", width=2, bg="#aa3333", fg="white", bd=0,
                  font=("Segoe UI", 9, "bold"),
                  command=self._quit).pack(side="right", padx=4)

    def _build_controls(self):
        opts = dict(bg="#333333", fg="white", bd=0, font=("Segoe UI", 9))
        row1 = tk.Frame(self.root, bg="#2b2b2b")
        row1.pack(fill="x", padx=6, pady=(4, 0))
        self.mode_btn = tk.Button(row1, text="模式:普通", width=9,
                                  command=self._toggle_mode, **opts)
        self.mode_btn.pack(side="left", padx=2)
        self.diff_btn = tk.Button(row1, text="难度:中等", width=9,
                                  command=self._cycle_diff, **opts)
        self.diff_btn.pack(side="left", padx=2)
        tk.Button(row1, text="新局", width=5, command=self.new_game,
                  **opts).pack(side="left", padx=2)
        tk.Button(row1, text="撤销", width=5, command=self.undo,
                  **opts).pack(side="left", padx=2)
        tk.Button(row1, text="重做", width=5, command=self.redo,
                  **opts).pack(side="left", padx=2)
        self.cand_btn = tk.Button(row1, text="候选", width=5,
                                  command=self._toggle_candidates, **opts)
        self.cand_btn.pack(side="left", padx=2)

        row2 = tk.Frame(self.root, bg="#2b2b2b")
        row2.pack(fill="x", padx=6, pady=(2, 0))
        tk.Label(row2, text="透明", bg="#2b2b2b", fg="#aaaaaa",
                 font=("Segoe UI", 9)).pack(side="left", padx=(2, 4))
        tk.Scale(row2, from_=15, to=100, orient="horizontal",
                 variable=self.alpha, command=self._on_alpha, showvalue=0,
                 length=110, bg="#2b2b2b", fg="white", troughcolor="#444444",
                 highlightthickness=0, sliderlength=12, bd=0).pack(side="left")
        self.alpha_lbl = tk.Label(row2, text="96%", bg="#2b2b2b", fg="#aaaaaa",
                                  font=("Segoe UI", 9))
        self.alpha_lbl.pack(side="left", padx=(4, 0))
        tk.Button(row2, text="置顶", width=5, command=self._toggle_top,
                  **opts).pack(side="right", padx=2)

        row3 = tk.Frame(self.root, bg="#2b2b2b")
        row3.pack(fill="x", padx=6, pady=(2, 0))
        tk.Label(row3, text="大小", bg="#2b2b2b", fg="#aaaaaa",
                 font=("Segoe UI", 9)).pack(side="left", padx=(2, 4))
        for name, sc in SIZE_PRESETS:
            tk.Button(row3, text=name, width=3,
                      command=lambda s=sc: self._set_scale(s),
                      **opts).pack(side="left", padx=1)
        tk.Button(row3, text="－", width=2, command=lambda: self._nudge(-SIZE_STEP),
                  **opts).pack(side="left", padx=(6, 1))
        tk.Button(row3, text="＋", width=2, command=lambda: self._nudge(SIZE_STEP),
                  **opts).pack(side="left", padx=1)
        self.size_lbl = tk.Label(row3, text="100%", bg="#2b2b2b", fg="#aaaaaa",
                                 font=("Segoe UI", 9))
        self.size_lbl.pack(side="left", padx=(6, 0))
        self.nine_btn = tk.Button(row3, text="九宫", width=4,
                                  command=self._toggle_nine_grid, **opts)
        self.nine_btn.pack(side="right", padx=2)
        self.pencil_btn = tk.Button(row3, text="笔注", width=4,
                                    command=self._toggle_pencil_mode, **opts)
        self.pencil_btn.pack(side="right", padx=2)

    def _build_grid(self):
        """Each cell = one frame holding exactly one value label that FILLS the
        frame, plus an optional cage-sum label in the corner (killer mode).

        Important: never stack extra opaque widgets inside a cell — an empty
        white label sitting on top of the digit would chop it into slivers.
        """
        self.cell_frames = {}
        self.val_labels = {}
        self.sum_labels = {}
        grid = tk.Frame(self.root, bg="#000000")
        grid.pack(padx=6, pady=4)
        self.grid = grid
        for br in range(3):
            for bc in range(3):
                box = tk.Frame(grid, bg="#666666", bd=1, relief="ridge")
                box.grid(row=br, column=bc, padx=1, pady=1)
                for i in range(3):
                    for j in range(3):
                        r, c = br * 3 + i, bc * 3 + j
                        f = tk.Frame(box, width=CELL, height=CELL, bg="white",
                                     highlightthickness=1,
                                     highlightbackground="#c8c8c8",
                                     cursor="hand2")
                        f.grid(row=i, column=j)
                        f.pack_propagate(False)
                        # candidates (bottom layer, filled 3x3)
                        cand = []
                        for d in range(1, 10):
                            sub = tk.Label(f, text="", font=self.font_cand,
                                           bg="white", fg=AUTO_FG)
                            col = (d - 1) % 3
                            row = (d - 1) // 3
                            # absolute integer-pixel placement (no rel* args, or
                            # they would override the absolute ones and inflate
                            # the label); _relayout() re-does this on resize.
                            x0, x1 = (col * CELL) // 3, ((col + 1) * CELL) // 3
                            y0, y1 = (row * CELL) // 3, ((row + 1) * CELL) // 3
                            sub.place(x=x0, y=y0, width=x1 - x0, height=y1 - y0)
                            cand.append(sub)
                        # value label — NOT placed here on purpose: a tkinter
                        # label keeps a real size even when its text is empty
                        # (measured ~6x37 px), so an "empty" one sitting on top
                        # of the cell silently masks the candidate digits.
                        # _render() places it only while the cell holds a digit.
                        vl = tk.Label(f, text="", font=self.font_val,
                                      bg="white", fg="#111111")
                        # cage-sum label — same rule: placed by _render() only
                        # for killer cage anchors, and sized to exactly one
                        # candidate slot so it never covers a neighbouring one.
                        sl = tk.Label(f, text="", font=self.font_sum,
                                      bg="white", fg="#333333",
                                      anchor="nw", padx=PN_PAD)
                        # Cage outline: one thin strip per cell edge. Only the
                        # edges that separate two different cages are mapped,
                        # so the players can always see where a cage ends.
                        # A cell only draws TOP / LEFT (plus the outer border of
                        # the last row / column) because the test is symmetric:
                        # whenever X differs from its lower neighbour, that
                        # neighbour draws its own TOP strip for the same seam.
                        edges = {}
                        for side in ("top", "left", "bottom", "right"):
                            strip = tk.Frame(f, bg=CAGE_LINE)
                            edges[side] = strip

                        # Clicks land on whichever child is topmost under the
                        # cursor, and Tk only consults THAT widget's bindtags —
                        # which are (widget, widgetClass, toplevel, all). The
                        # parent frame is NOT in that list, so a bind on the
                        # frame alone never fires once the candidate labels
                        # tile the cell: every click silently did nothing.
                        # Hence every child gets its own handler.
                        for wgt in [f] + cand + [vl, sl] + list(edges.values()):
                            wgt.bind("<Button-1>",
                                     lambda e, rr=r, cc=c:
                                     self._select(rr, cc,
                                                  shift=bool(e.state & 0x1)))
                        self.cell_frames[(r, c)] = f
                        self.val_labels[(r, c)] = vl
                        self.sum_labels[(r, c)] = sl
                        self.cand_labels[(r, c)] = cand
                        self.cage_edges[(r, c)] = edges

    def _build_pad(self):
        pad = tk.Frame(self.root, bg="#2b2b2b")
        pad.pack(padx=6, pady=(2, 2))
        self.pad_buttons = []
        for n in range(1, 10):
            b = tk.Button(pad, text=str(n), width=3, height=1,
                          font=("Segoe UI", 12), bg="#3a3a3a", fg="white",
                          bd=0, command=lambda v=n: self._input(v))
            b.grid(row=0, column=n - 1, padx=1)
            self.pad_buttons.append(b)
        tk.Button(pad, text="擦除", height=1, font=("Segoe UI", 10),
                  bg="#554433", fg="white", bd=0,
                  command=self._erase_selection).grid(
            row=1, column=0, columnspan=4, padx=1, pady=2, sticky="ew")
        tk.Button(pad, text="显示答案", height=1, font=("Segoe UI", 10),
                  bg="#334455", fg="white", bd=0,
                  command=self._solve_current).grid(
            row=1, column=4, columnspan=5, padx=1, pady=2, sticky="ew")
        self.pad_row2 = pad

    def _build_status(self):
        self.status_lbl = tk.Label(self.root, text="点格输入 · Ctrl 笔注 · Shift 多选 · 点空白取消 · Ctrl+Z 撤销",
                                   bg="#2b2b2b", fg="#aaaaaa",
                                   font=("Segoe UI", 9))
        self.status_lbl.pack(pady=(0, 4))

    # ---------- game setup ----------
    def new_game(self):
        if self.mode == "normal":
            puzzle, solution = sudoku_core.make_puzzle(self.difficulty)
            self.solution = solution
            self.values = [row[:] for row in puzzle]
            self.given = [[puzzle[r][c] != 0 for c in range(9)] for r in range(9)]
            self.cages = None
            self.cage_edge_plan = {}
        else:
            data = killer_core.make_killer(self.difficulty)
            self.solution = data["solution"]
            self.values = [[0] * 9 for _ in range(9)]
            self.given = [[False] * 9 for _ in range(9)]
            self.cages = data["cages"]
            self.cage_of = data["cage_of"]
            self.cage_sum = {c["id"]: c["sum"] for c in self.cages}
            self.cage_anchor = {c["id"]: c["anchor"] for c in self.cages}
            self.cage_colors = self._make_cage_colors(self.cages)
            self._compute_cage_edges()
            # 杀手简单/中等模式：预置若干给定数字作为提示（专家级不预置）
            n = _KILLER_GIVENS.get(self.difficulty, 0)
            if n:
                pool = [(r, c) for r in range(9) for c in range(9)]
                random.shuffle(pool)
                for (r, c) in pool[:n]:
                    self.given[r][c] = True
                    self.values[r][c] = self.solution[r][c]
        self.selected = None
        self.selection = set()
        self.pencils = [[set() for _ in range(9)] for _ in range(9)]
        self.vanished.clear()
        self.flash.clear()
        self.done_digits = set()
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._stop_flash()
        self._stop_anim()
        self._render()
        self._save()
        self.status_lbl.config(
            text=f"{MODE_NAMES[self.mode]} · 难度：{DIFF_NAMES[self.difficulty]}　已出题")

    def _make_cage_colors(self, cages):
        """Colour the cages by greedy GRAPH colouring.

        The old version derived a hue from the cage index
        (h = i * 0.618 mod 1), which scatters hues in a way that puts *some*
        neighbouring ids almost on top of each other — e.g. cage 0 vs cage 21
        came out as #F2A9A9 / #F2A9B2, i.e. unreadable as two different cages,
        and the player then sums the wrong group of cells. Building the actual
        adjacency (touching counts, including corners) and taking colours from
        a fixed pastel palette guarantees visually distinct neighbours.
        """
        n = len(cages)
        owner = {}
        for i, cg in enumerate(cages):
            for cell in cg["cells"]:
                owner[tuple(cell)] = i
        adj = [set() for _ in range(n)]
        for i, cg in enumerate(cages):
            for cell in cg["cells"]:
                r, c = cell[0], cell[1]
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        if dr == 0 and dc == 0:
                            continue
                        j = owner.get((r + dr, c + dc))
                        if j is not None and j != i:
                            adj[i].add(j)

        # most-constrained-first: colour the cages with the most neighbours
        colors = [None] * n
        used = [0] * len(CAGE_PALETTE)
        for i in sorted(range(n), key=lambda k: (-len(adj[k]), k)):
            banned = {colors[j] for j in adj[i] if colors[j] is not None}
            best = None
            for k in range(len(CAGE_PALETTE)):
                if k in banned:
                    continue
                # pick the least-used allowed colour so the palette spreads out
                # instead of everything landing on entry #0
                if best is None or used[k] < used[best]:
                    best = k
            if best is None:                      # >12 mutually touching cages
                best = i % len(CAGE_PALETTE)
            colors[i] = best
            used[best] += 1
        return [CAGE_PALETTE[k] for k in colors]

    def _cage_color_of(self, r, c):
        if self.mode != "killer":
            return CELL_BG_DEFAULT
        return self.cage_colors[self.cage_of[(r, c)]]

    # ---------- persistence ----------
    def _save(self):
        if not hasattr(self, "values"):
            return
        data = {
            "mode": self.mode,
            "difficulty": self.difficulty,
            "given": self.given,
            "values": self.values,
            "solution": self.solution,
            "pencils": self._pencils_as_list(),
        }
        if self.mode == "killer" and self.cages is not None:
            data["cages"] = self.cages
        try:
            with open(self.save_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except OSError:
            pass

    def _restore_or_new(self):
        if self._load():
            self._render()
            self.status_lbl.config(
                text=f"{MODE_NAMES[self.mode]} · 难度：{DIFF_NAMES[self.difficulty]}　已恢复上次进度")
        else:
            self.new_game()

    def _load(self):
        try:
            with open(self.save_path, "r", encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            return False
        try:
            self.mode = d["mode"]
            self.difficulty = d["difficulty"]
            self.given = d["given"]
            self.values = d["values"]
            self.solution = d["solution"]
            if self.mode == "killer":
                # JSON turns tuples into lists; coerce cells/anchor back so that
                # set.update(cage["cells"]) and (r, c) membership checks work.
                self.cages = []
                for c in d["cages"]:
                    self.cages.append({
                        "id": c["id"],
                        "cells": [tuple(x) for x in c["cells"]],
                        "sum": c["sum"],
                        "anchor": tuple(c["anchor"]),
                    })
                self.cage_of = {}
                for c in self.cages:
                    for (r, cc) in c["cells"]:
                        self.cage_of[(r, cc)] = c["id"]
                self.cage_sum = {c["id"]: c["sum"] for c in self.cages}
                self.cage_anchor = {c["id"]: c["anchor"] for c in self.cages}
                self.cage_colors = self._make_cage_colors(self.cages)
                self._compute_cage_edges()
            else:
                self.cages = None
                self.cage_edge_plan = {}
            self.selection = set()
            self._load_pencils(d.get("pencils"))
            self.mode_btn.config(text="模式:" + MODE_NAMES[self.mode])
            self.diff_btn.config(text="难度:" + DIFF_NAMES[self.difficulty])
            return True
        except (KeyError, TypeError, ValueError):
            return False

    def _pencils_as_list(self):
        return [[sorted(s) for s in row] for row in self.pencils]

    def _load_pencils(self, raw):
        blank = [[set() for _ in range(9)] for _ in range(9)]
        if not raw or len(raw) != 9:
            self.pencils = blank
            return
        for r in range(9):
            if len(raw[r]) != 9:
                self.pencils = blank
                return
            for c in range(9):
                try:
                    blank[r][c] = {int(d) for d in raw[r][c] if 1 <= int(d) <= 9}
                except (TypeError, ValueError):
                    blank[r][c] = set()
        self.pencils = blank

    def _compute_cage_edges(self):
        """Which cells draw which side of the cage outline.

        Each cell draws its TOP / LEFT strip when the cell on the other side
        belongs to a different cage (plus the last row / column closing the
        outer rectangle). The adjacency test is symmetric, so the neighbour
        never needs to draw a duplicate strip for the same seam.
        """
        plan = {}
        if self.mode == "killer" and self.cages:
            for r in range(9):
                for c in range(9):
                    here = self.cage_of[(r, c)]
                    sides = set()
                    if r == 0 or self.cage_of[(r - 1, c)] != here:
                        sides.add("top")
                    if c == 0 or self.cage_of[(r, c - 1)] != here:
                        sides.add("left")
                    if r == 8:
                        sides.add("bottom")
                    if c == 8:
                        sides.add("right")
                    plan[(r, c)] = sides
        self.cage_edge_plan = plan

    # ---------- validation ----------
    def _find_conflicts(self):
        conf = set()
        for r in range(9):
            for c in range(9):
                v = self.values[r][c]
                if v == 0:
                    continue
                for k in range(9):
                    if k != c and self.values[r][k] == v:
                        conf.add((r, c)); conf.add((r, k))
                    if k != r and self.values[k][c] == v:
                        conf.add((r, c)); conf.add((k, c))
                br, bc = (r // 3) * 3, (c // 3) * 3
                for i in range(br, br + 3):
                    for j in range(bc, bc + 3):
                        if (i, j) != (r, c) and self.values[i][j] == v:
                            conf.add((r, c)); conf.add((i, j))
        return conf

    def _bad_cages(self):
        bad = set()
        if self.mode != "killer":
            return bad
        for cage in self.cages:
            vals = [self.values[r][c] for (r, c) in cage["cells"]]
            filled = [x for x in vals if x != 0]
            if len(filled) != len(set(filled)):
                bad.update(cage["cells"]); continue
            if len(filled) == len(cage["cells"]) and sum(filled) != cage["sum"]:
                bad.update(cage["cells"])
        return bad

    # ---------- auto candidates ----------
    def _candidates_for(self, r, c):
        """Digits 1-9 not present in the cell's row, column or box."""
        used = set()
        for k in range(9):
            if self.values[r][k]:
                used.add(self.values[r][k])
            if self.values[k][c]:
                used.add(self.values[k][c])
        br, bc = (r // 3) * 3, (c // 3) * 3
        for i in range(br, br + 3):
            for j in range(bc, bc + 3):
                if self.values[i][j]:
                    used.add(self.values[i][j])
        return {d for d in range(1, 10) if d not in used}

    def _toggle_candidates(self):
        self.show_candidates = not self.show_candidates
        self.cand_btn.config(
            bg="#2e7d32" if self.show_candidates else "#333333")
        self._render()

    def _toggle_pencil_mode(self):
        self.pencil_mode = not self.pencil_mode
        self.pencil_btn.config(
            bg="#6a1b9a" if self.pencil_mode else "#333333")
        self._update_status_hint()

    def _toggle_nine_grid(self):
        self.nine_grid = not self.nine_grid
        self.nine_btn.config(bg="#00695c" if self.nine_grid else "#333333")
        self._update_status_hint()

    # ---------- rendering ----------
    def _purge_flash(self, now=None):
        now = time.monotonic() if now is None else now
        dead = [k for k, t in self.flash.items() if t <= now]
        for k in dead:
            del self.flash[k]
        return bool(dead)

    def _render(self):
        now = time.monotonic()
        self._purge_flash(now)
        conflicts = self._find_conflicts()
        cage_bad = self._bad_cages()

        peers = set()
        same = set()
        if self.selected is not None:
            r0, c0 = self.selected
            sv = self.values[r0][c0]
            for k in range(9):
                peers.add((r0, k))
                peers.add((k, c0))
            br, bc = (r0 // 3) * 3, (c0 // 3) * 3
            for i in range(br, br + 3):
                for j in range(bc, bc + 3):
                    peers.add((i, j))
            if sv:
                same = {(r, c) for r in range(9) for c in range(9)
                        if self.values[r][c] == sv}

        ctx = (conflicts, cage_bad, peers, same, now)
        for r in range(9):
            for c in range(9):
                self._paint_cell(r, c, *ctx)

    def _render_cell(self, r, c):
        now = time.monotonic()
        self._purge_flash(now)
        self._paint_cell(r, c, self._find_conflicts(), self._bad_cages(),
                         *self._peer_sets(), now)

    def _peer_sets(self):
        if self.selected is None:
            return set(), set()
        r0, c0 = self.selected
        peers = {(r0, k) for k in range(9)} | {(k, c0) for k in range(9)}
        br, bc = (r0 // 3) * 3, (c0 // 3) * 3
        peers |= {(i, j) for i in range(br, br + 3) for j in range(bc, bc + 3)}
        sv = self.values[r0][c0]
        same = ({(r, c) for r in range(9) for c in range(9)
                 if self.values[r][c] == sv} if sv else set())
        return peers, same

    def _paint_cell(self, r, c, conflicts, cage_bad, peers, same, now):
        f = self.cell_frames[(r, c)]
        vl = self.val_labels[(r, c)]
        sl = self.sum_labels[(r, c)]
        cand = self.cand_labels[(r, c)]
        edges = self.cage_edges[(r, c)]
        v = self.values[r][c]

        # ---- cells already wiped by the win animation ----
        if (r, c) in self.vanished:
            f.config(bg=BG_COLOR, highlightbackground=BG_COLOR,
                     highlightthickness=HL_PX)
            if vl.winfo_ismapped():
                vl.place_forget()
            if sl.winfo_ismapped():
                sl.place_forget()
            for strip in edges.values():
                if strip.winfo_ismapped():
                    strip.place_forget()
            for sub in cand:
                sub.config(text="", bg=BG_COLOR)
            return

        bad = (r, c) in conflicts or (r, c) in cage_bad
        base = self._cage_color_of(r, c)
        flashing = (r, c) in self.flash

        if bad:
            bg = CONFLICT_BG
        elif flashing:
            bg = FLASH_BG
        elif self.selected == (r, c):
            bg = SEL_BG
        elif (r, c) in peers:
            # tint instead of a hard fill, otherwise the killer cage colours
            # would be wiped out inside the peer band
            bg = _mix(base, PEER_BG, 0.65)
        else:
            bg = base

        if v:
            fg = VAL_FG_GIVEN if self.given[r][c] else VAL_FG_USER
            if bad:
                fg = CONFLICT_FG
        else:
            fg = VAL_FG_GIVEN

        if bad:
            hb = CONFLICT_FG
        elif flashing:
            hb = "#00c853"
        elif self.selected == (r, c):
            hb = "#ff9800"
        elif (r, c) in self.selection:
            hb = "#9ccc65"
        elif (r, c) in same:
            hb = VAL_FG_USER
        elif (r, c) in peers:
            hb = "#7fb0ea"
        else:
            hb = "#c8c8c8"

        # width is constant on purpose: changing it would resize the inner
        # content box and shift every placed child by a pixel or two.
        f.config(bg=bg, highlightbackground=hb, highlightthickness=HL_PX)

        if v:
            vl.config(text=str(v), bg=bg, fg=fg)
            vl.place(relx=0.5, rely=0.5, anchor="center")
        else:
            vl.place_forget()

        plan = self.cage_edge_plan.get((r, c), ())
        # The strips must sit above the candidate labels (or those would paint
        # them over). The sum gets the full top strip (see below), so only the
        # 3x3 candidate grid has to stay clear of them.
        inner = self._inner
        if "top" in plan:
            edges["top"].place(x=0, y=0, width=inner, height=EDGE_PX)
        else:
            edges["top"].place_forget()
        if "left" in plan:
            edges["left"].place(x=0, y=0, width=EDGE_PX, height=inner)
        else:
            edges["left"].place_forget()
        if "bottom" in plan:
            edges["bottom"].place(x=0, y=inner - EDGE_PX,
                                  width=inner, height=EDGE_PX)
        else:
            edges["bottom"].place_forget()
        if "right" in plan:
            edges["right"].place(x=inner - EDGE_PX, y=0,
                                 width=EDGE_PX, height=inner)
        else:
            edges["right"].place_forget()

        # ---- cage sum ----
        # A killer cage sum gets its OWN strip along the top of the cell — it
        # does NOT share the 3x3 candidate grid. Stacking them (the label said
        # height = one ~11px slot while the 11px font needed ~15px) meant the
        # digits of "13" got their top halves sliced off by the label edge, and
        # the layout was re-derived in two places (here and the candidate loop)
        # which is exactly how they drifted apart.
        sum_h = self._sum_h
        used_slots = 0
        if self.mode == "killer":
            cid = self.cage_of.get((r, c))
            if cid is not None and self.cage_anchor[cid] == (r, c):
                txt = str(self.cage_sum[cid])
                sl.config(text=txt, bg=bg)
                # anchor="nw" + a 1px pad (set at build time) keeps the digits
                # inside the strip; the strip itself is sized from the font.
                sl.place(x=0, y=0,
                         width=min(len(txt) * self._sum_w + self._sum_pad,
                                   inner),
                         height=max(sum_h, EDGE_PX))
                used_slots = min(len(txt), 3)
            else:
                sl.place_forget()
        else:
            sl.place_forget()

        # ---- candidates / pencil marks ----
        # grey = auto candidates from the "候选" toggle, purple = your own
        # pencil marks; your marks win the colour when both want a slot.
        marks = {}
        if v == 0:
            if self.show_candidates:
                marks = {d: AUTO_FG for d in self._candidates_for(r, c)}
            for d in self.pencils[r][c]:
                marks[d] = PENCIL_FG
        skip_top = used_slots if self._sum_band else 0
        for d in range(1, 10):
            sub = cand[d - 1]
            row = (d - 1) // 3
            col = (d - 1) % 3
            hidden = row == 0 and col < skip_top   # that slot belongs to the sum
            if d in marks and not hidden:
                sub.config(text=str(d), bg=bg, fg=marks[d])
            else:
                sub.config(text="", bg=bg)

    # ---------- green feedback + win animation ----------
    def _check_done_digits(self):
        """Flash green every cell of a digit that just went 9-for-9 correct."""
        now = time.monotonic()
        hit = False
        for d in range(1, 10):
            cells = [(r, c) for r in range(9) for c in range(9)
                     if self.values[r][c] == d]
            complete = (len(cells) == 9
                        and all(self.solution[r][c] == d for (r, c) in cells))
            if complete and d not in self.done_digits:
                self.done_digits.add(d)
                for cell in cells:
                    self.flash[cell] = now + FLASH_SEC
                hit = True
            elif not complete:
                self.done_digits.discard(d)
        if hit:
            self._schedule_flash_cleanup()

    def _schedule_flash_cleanup(self):
        if self._flash_job is not None:
            return
        nxt = int((min(self.flash.values()) - time.monotonic()) * 1000) + 40
        self._flash_job = self.root.after(max(40, nxt), self._tick_flash)

    def _tick_flash(self):
        self._flash_job = None
        self._render()
        if self.flash:
            self._schedule_flash_cleanup()

    def _stop_flash(self):
        if self._flash_job is not None:
            try:
                self.root.after_cancel(self._flash_job)
            except Exception:
                pass
            self._flash_job = None
        self.flash.clear()

    def _start_vanish(self):
        """Wipe the board diagonal by diagonal, starting at r1c1 and sweeping
        down towards the lower-left edge of each diagonal."""
        order = []
        for k in range(17):                       # anti-diagonals r + c = k
            for r in range(max(0, k - 8), min(9, k + 1)):
                order.append((r, k - r))
        self._vanish_order = order
        self._vanish_i = 0
        self.vanished = set()
        self.selected = None
        self._step_vanish()

    def _step_vanish(self):
        self._anim_job = None
        if self._vanish_i >= len(self._vanish_order):
            self._finish_vanish()
            return
        cell = self._vanish_order[self._vanish_i]
        self._vanish_i += 1
        self.vanished.add(cell)
        self._render_cell(*cell)
        self._anim_job = self.root.after(VANISH_STEP_MS, self._step_vanish)

    def _finish_vanish(self):
        self._anim_job = None
        self.vanished = set()
        self._render()
        self.status_lbl.config(text="完成！点「新局」再来一局")

    def _stop_anim(self):
        if self._anim_job is not None:
            try:
                self.root.after_cancel(self._anim_job)
            except Exception:
                pass
            self._anim_job = None
        self.vanished = set()

    def _select(self, r, c, shift=False):
        self._suppress_deselect = True
        if shift:
            if (r, c) in self.selection:
                self.selection.discard((r, c))
            else:
                self.selection.add((r, c))
        else:
            self.selection = {(r, c)}
        self.selected = (r, c)
        self._render()
        self._update_select_status()

    def _update_select_status(self):
        if len(self.selection) > 1:
            self.status_lbl.config(
                text=f"已选 {len(self.selection)} 格 · "
                      f"Ctrl+数字 批量加小笔记 · 点空白取消选择")
        else:
            self._update_status_hint()

    def _input(self, v):
        if self.selected is None:
            self.status_lbl.config(text="请先点击一个格子")
            return
        targets = self.selection if self.selection else {self.selected}
        r0, c0 = self.selected
        if self.given[r0][c0]:
            self.status_lbl.config(text="该格为题目给定，不可修改")
            return

        if self.pencil_mode and v != 0:
            self._apply_pencil(targets, v)
            return

        new = v
        if self.values[r0][c0] == new:
            return  # no change → don't pollute the undo stack

        self._push_undo()
        self.values[r0][c0] = new
        if new:
            self.pencils[r0][c0].clear()   # filling a digit clears its marks
        self._check_done_digits()
        self._render()
        self._check_win()
        self._save()

    def _apply_pencil(self, targets, d):
        """Toggle pencil mark `d` on every cell in `targets` (batch aware)."""
        self._push_undo()
        for (r, c) in targets:
            marks = self.pencils[r][c]
            if d in marks:
                marks.discard(d)
            else:
                marks.add(d)
        self._render()
        self._save()
        if len(targets) > 1:
            self.status_lbl.config(text=f"已为 {len(targets)} 格 切换小笔记 {d}")

    def _pencil_input(self, d):
        if self.selected is None:
            self.status_lbl.config(text="请先点击一个格子")
            return
        targets = self.selection if self.selection else {self.selected}
        self._apply_pencil(targets, d)

    def _erase_selection(self):
        if self.selected is None:
            self.status_lbl.config(text="请先点击一个格子")
            return
        targets = self.selection if self.selection else {self.selected}
        doable = [(r, c) for (r, c) in targets
                  if not self.given[r][c] and self.values[r][c] != 0]
        if not doable:
            return
        self._push_undo()
        for (r, c) in doable:
            self.values[r][c] = 0
        self._check_done_digits()
        self._render()
        self._save()

    # (pencil toggling now goes through _apply_pencil, which handles a batch
    #  of selected cells in one undo step)

    def _check_win(self):
        if any(self.values[r][c] == 0 for r in range(9) for c in range(9)):
            return
        if self._find_conflicts():
            self.status_lbl.config(text="已填满，但还有冲突，检查一下")
            return
        if self.mode == "killer" and self._bad_cages():
            self.status_lbl.config(text="已填满，但某些 cage 的和或数字不对")
            return
        self.status_lbl.config(text="完成！")
        self._start_vanish()

    def _solve_current(self):
        self._push_undo()
        self.values = [row[:] for row in self.solution]
        self.pencils = [[set() for _ in range(9)] for _ in range(9)]
        self._check_done_digits()
        self._render()
        self._save()
        self.status_lbl.config(text="已显示完整答案")

    # ---------- undo / redo ----------
    def _snapshot(self):
        return ([row[:] for row in self.values],
                [[set(s) for s in row] for row in self.pencils])

    def _apply_snapshot(self, snap):
        self.values = [row[:] for row in snap[0]]
        if len(snap) > 1 and snap[1] and len(snap[1]) == 9:
            self.pencils = [[set(s) for s in row] for row in snap[1]]
        else:
            self.pencils = [[set() for _ in range(9)] for _ in range(9)]

    def _push_undo(self):
        self.undo_stack.append(self._snapshot())
        if len(self.undo_stack) > 300:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def undo(self):
        if not self.undo_stack:
            self.status_lbl.config(text="没有可撤销的步骤")
            return
        self.redo_stack.append(self._snapshot())
        self._apply_snapshot(self.undo_stack.pop())
        self._stop_anim()
        self._check_done_digits()
        self._render()
        self._save()

    def redo(self):
        if not self.redo_stack:
            self.status_lbl.config(text="没有可重做的步骤")
            return
        self.undo_stack.append(self._snapshot())
        self._apply_snapshot(self.redo_stack.pop())
        self._check_done_digits()
        self._render()
        self._save()

    # ---------- controls ----------
    def _toggle_mode(self):
        self.mode = "killer" if self.mode == "normal" else "normal"
        self.mode_btn.config(text="模式:" + MODE_NAMES[self.mode])
        self.new_game()

    def _cycle_diff(self):
        i = (DIFFS.index(self.difficulty) + 1) % len(DIFFS)
        self.difficulty = DIFFS[i]
        self.diff_btn.config(text="难度:" + DIFF_NAMES[self.difficulty])
        self.new_game()

    def _toggle_top(self):
        self.topmost = not self.topmost
        self.root.attributes("-topmost", self.topmost)

    def _on_alpha(self, val):
        pct = int(float(val))
        self.root.attributes("-alpha", pct / 100)
        self.alpha_lbl.config(text=f"{pct}%")

    def _on_key(self, e):
        ks = e.keysym
        ctrl = bool(e.state & 0x4)
        shift = bool(e.state & 0x1)

        # Ctrl is the pencil-mode modifier: tap it to toggle (handled on the
        # key-release below); hold it and hit a digit to drop a pencil mark.
        if ks in ("Control_L", "Control_R"):
            self._ctrl_down = True
            self._ctrl_used = False
            return
        # Shift is now a mouse-only multi-select modifier; ignore on keyboard.
        if ks in ("Shift_L", "Shift_R"):
            return

        if ctrl:
            self._ctrl_used = True
        if ctrl and ks in ("z", "Z"):
            self.undo(); return
        if ctrl and ks in ("y", "Y"):
            self.redo(); return

        digit = None
        if ks.isdigit() and ks != "0":
            digit = int(ks)
        elif self.nine_grid and not ctrl and not shift:
            digit = NINE_GRID_KEYS.get(ks.lower())

        if digit is not None:
            if ctrl:
                self._pencil_input(digit)
            else:
                self._input(digit)
            return
        if ks == "BackSpace" or ks == "Delete" or ks == "0":
            self._erase_selection(); return
        if ks == "Left":
            self._move(0, -1); return
        if ks == "Right":
            self._move(0, 1); return
        if ks == "Up":
            self._move(-1, 0); return
        if ks == "Down":
            self._move(1, 0); return
        if ks == "space":
            now = time.time()
            if now - self._last_space < 0.5:
                self._hide()
                self._last_space = 0
            else:
                self._last_space = now

    def _on_key_release(self, e):
        if e.keysym in ("Control_L", "Control_R"):
            down = self._ctrl_down
            self._ctrl_down = False
            # released without typing anything -> treat it as a mode toggle
            if down and not self._ctrl_used:
                self._toggle_pencil_mode()

    def _move(self, dr, dc):
        if self.selected is None:
            self._select(0, 0)
            return
        r, c = self.selected
        r = (r + dr) % 9
        c = (c + dc) % 9
        self._select(r, c)

    # ---------- click-to-deselect (blank area) ----------
    def _on_root_click(self, e):
        self.root.focus_force()
        if self._suppress_deselect:
            self._suppress_deselect = False
            return
        if self.selected is not None or getattr(self, "selection", None):
            self.selected = None
            self.selection = set()
            self._render()
            self._update_status_hint()

    def _mark_interactive_click(self):
        self._suppress_deselect = True

    def _mark_buttons(self):
        """Mark toolbar / pad widgets as 'interactive' so a click on them does
        not count as a blank-area click that clears the selection."""
        def walk(w):
            for ch in w.winfo_children():
                if isinstance(ch, (tk.Button, tk.Scale)):
                    ch.bind("<Button-1>",
                            lambda e: self._mark_interactive_click(), add="+")
                walk(ch)
        walk(self.root)

    # ---------- window drag / size ----------
    def _start_drag(self, e):
        self._drag_x, self._drag_y = e.x, e.y

    def _do_drag(self, e):
        x = self.root.winfo_x() + e.x - self._drag_x
        y = self.root.winfo_y() + e.y - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    def _set_scale(self, s):
        self.scale = max(SCALE_MIN, min(SCALE_MAX, round(s, 3)))
        self._relayout()
        self._render()
        self._update_size_label()

    def _nudge(self, d):
        self._set_scale(round(self.scale + d, 3))

    def _update_size_label(self):
        self.size_lbl.config(text=f"{int(round(self.scale * 100))}%")

    def _relayout(self):
        """Resize cells + fonts only (no text/color changes)."""
        cell = max(22, int(CELL * self.scale))
        # children placed inside a frame are positioned relative to its inner
        # box, i.e. after the highlight ring — so the usable area is cell-2*HL
        inner = max(12, cell - 2 * HL_PX)
        self._cell = cell
        self._inner = inner
        self._slot = inner // 3
        self.font_val = (FONT_FAMILY, max(10, int(BASE_VAL_PT * self.scale)))
        self.font_sum = (FONT_FAMILY, max(SUM_PT_MIN,
                                         int(BASE_SUM_PT * self.scale)))
        self.font_cand = (FONT_FAMILY, max(CAND_PT_MIN,
                                           int(BASE_CAND_PT * self.scale)))
        self._measure_sum_font()
        # `_sum_band` (set by _measure_sum_font) decides whether the 3x3
        # candidate grid has to start below the cage-sum strip instead of
        # behind it. Never let the strip eat more than half the cell.
        top = self._sum_h if self._sum_band else 0
        for (r, c), f in self.cell_frames.items():
            f.config(width=cell, height=cell)
            self.val_labels[(r, c)].config(font=self.font_val)
            self.sum_labels[(r, c)].config(font=self.font_sum)
            # integer-pixel placement: avoids sub-pixel positions that make the
            # small candidate glyphs pick up heavy ClearType colour fringing
            for di, sub in enumerate(self.cand_labels[(r, c)]):
                col, row = di % 3, di // 3
                x0, x1 = (col * inner) // 3, ((col + 1) * inner) // 3
                y0 = top + ((row * (inner - top)) // 3)
                y1 = top + (((row + 1) * (inner - top)) // 3)
                sub.config(font=self.font_cand)
                sub.place(x=x0, y=y0, width=x1 - x0, height=y1 - y0)
        pad_font = ("Segoe UI", max(10, int(12 * self.scale)))
        for b in self.pad_buttons:
            b.config(font=pad_font)

    # ---------- visibility / tray / hotkey ----------
    def _measure_sum_font(self):
        """Geometry for the cage-sum strip, derived from the measured label.

        Measured facts that drove this (Segoe UI, 100% zoom, Windows):
            font size 8 -> ascent 11, descent 2, linespace 13
            tk.Label(font size 8, padx=1) -> reqheight 19, i.e. 6px of the
            label's own vertical border/padding on top of the line box.
        Sizing the strip to the 3x3 candidate slot (11px) therefore sliced the
        tops off two-digit sums, and deriving the width per slot from the
        TWO-digit measurement clipped "23" down to one visible glyph. Both
        numbers now come from the real label.

        (Repeatedly-used `tkfont.Font` objects are cached by Tkinter, so this is
        cheap even though _relayout runs on every size change.)
        """
        sl = self.sum_labels[(0, 0)]
        try:
            sl.config(font=self.font_sum)          # measure at the new size
            need_h = sl.winfo_reqheight() + 3      # 3px safety margin
            f = tkfont.Font(font=self.font_sum)
            need_w = f.measure("88") // 2 + 1      # per-character width
        except Exception:
            need_h = int(BASE_SUM_PT * self.scale * 2.4)
            need_w = int(BASE_SUM_PT * self.scale * 0.8)
        inner = self._inner
        self._sum_h = min(need_h, max(8, (inner * 2) // 3))
        self._sum_w = max(5, need_w)
        self._sum_pad = 2 * PN_PAD
        self._sum_band = self._sum_h < self._slot

    def _hide(self):
        if not getattr(self, "can_restore", False):
            self.status_lbl.config(text="隐藏不可用：恢复入口未就绪")
            return
        self.root.withdraw()

    def _show(self):
        self.root.deiconify()
        self.root.attributes("-topmost", self.topmost)

    def _toggle_hide(self):
        if self.root.winfo_viewable():
            self._hide()
        else:
            self._show()

    def _quit(self):
        if self.tray is not None:
            try:
                self.tray.stop()
            except Exception:
                pass
        self.root.destroy()

    def _update_status_hint(self):
        restore = []
        if self.tray_ok:
            restore.append("托盘图标")
        if self.hotkey_label:
            restore.append(self.hotkey_label)
        hint = "双击空格隐藏"
        if restore:
            hint += "，" + " / ".join(restore) + " 恢复"
        flags = []
        if self.pencil_mode:
            flags.append("笔注开")
        if self.nine_grid:
            flags.append("九宫输入开")
        if flags:
            hint = "｜".join(flags) + "　" + hint
        self.status_lbl.config(text=hint)

    def _setup_tray(self):
        self.tray = None
        try:
            import pystray
            from PIL import Image, ImageDraw
        except Exception:
            return False
        try:
            img = Image.new("RGB", (64, 64), "#2b2b2b")
            d = ImageDraw.Draw(img)
            d.rectangle([6, 6, 57, 57], outline="#cfd8dc", width=3)
            d.line([6, 23, 57, 23], fill="#cfd8dc", width=2)
            d.line([6, 40, 57, 40], fill="#cfd8dc", width=2)
            d.line([23, 6, 23, 57], fill="#cfd8dc", width=2)
            d.line([40, 6, 40, 57], fill="#cfd8dc", width=2)

            def on_toggle(icon, item):
                self._ui_post(self._toggle_hide)

            def on_show(icon, item):
                self._ui_post(self._show)

            def on_quit(icon, item):
                self._ui_post(self._quit)

            menu = pystray.Menu(
                pystray.MenuItem("显示 / 隐藏", on_toggle, default=True),
                pystray.MenuItem("显示", on_show),
                pystray.MenuItem("退出", on_quit),
            )
            self.tray = pystray.Icon("sudoku", img, "悬浮数独", menu)

            def run():
                try:
                    self.tray.run()
                except Exception:
                    pass

            threading.Thread(target=run, daemon=True).start()
            return True
        except Exception:
            self.tray = None
            return False

    def _setup_hotkey(self):
        self.hotkey_label = None
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
        except Exception:
            return

        MOD_ALT, MOD_CTRL, MOD_SHIFT = 0x0001, 0x0002, 0x0004
        NOREPEAT = 0x4000          # don't spam WM_HOTKEY while the key is held
        combos = [("Ctrl+Alt+S", MOD_CTRL | MOD_ALT | NOREPEAT, ord("S")),
                  ("Ctrl+Alt+D", MOD_CTRL | MOD_ALT | NOREPEAT, ord("D")),
                  ("Ctrl+Shift+S", MOD_CTRL | MOD_SHIFT | NOREPEAT, ord("S"))]
        ready = threading.Event()
        result = {}

        def loop():
            # RegisterHotKey delivers WM_HOTKEY to the message queue of the
            # thread that registered it, so registration and the pump below
            # must live on the SAME (this) thread — registering from the main
            # thread would mean the message is never drained and the shortcut
            # silently does nothing.
            for name, mod, vk in combos:
                if user32.RegisterHotKey(None, 1, mod, vk):
                    result["label"] = name
                    break
            ready.set()
            if "label" not in result:
                return
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == 0x0312:          # WM_HOTKEY
                    self._ui_post(self._toggle_hide)
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

        threading.Thread(target=loop, daemon=True).start()
        ready.wait(1.0)
        self.hotkey_label = result.get("label")

    def _center(self):
        self.root.update_idletasks()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"+{x}+{y}")

        # Keep keyboard focus on the window so the double-space hide and global
        # shortcuts work even after clicking a toolbar button (otherwise Space
        # would "click" the focused button instead of reaching <Key>).
        def _nofocus(w):
            try:
                if isinstance(w, tk.Button):
                    w.configure(takefocus=False)
            except Exception:
                pass
            for ch in w.winfo_children():
                _nofocus(ch)
        _nofocus(self.root)


if __name__ == "__main__":
    root = tk.Tk()
    SudokuApp(root)
    root.mainloop()
