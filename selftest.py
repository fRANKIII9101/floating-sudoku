"""Self-tests for the floating sudoku widget.

Run:  python selftest.py

Needs a display (tkinter). Every GUI test redirects the auto-save file through
the SUDOKU_SAVE_PATH environment variable, so your real save slot is never
touched. Exits with a non-zero status if anything fails.
"""

import os
import sys
import tempfile
import time
import tkinter as tk
from tkinter import font as tkfont

import sudoku_core
import killer_core

FAILS = []


def check(name, cond, extra=""):
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"   {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------- logic layer
def test_generation():
    print("== 出题逻辑（无需界面）==")
    for diff in ("easy", "medium", "hard", "expert"):
        t = time.time()
        puzzle, solution = sudoku_core.make_puzzle(diff)
        dt = time.time() - t
        givens = sum(1 for row in puzzle for v in row if v)
        unique = sudoku_core.count_solutions([r[:] for r in puzzle], 2) == 1
        check(f"普通[{diff}] 唯一解", unique, f"提示数={givens} 耗时={dt:.2f}s")
        # the returned solution must actually satisfy the puzzle
        ok = all(puzzle[r][c] in (0, solution[r][c])
                 for r in range(9) for c in range(9))
        check(f"普通[{diff}] 解与题目自洽", ok)
        check(f"普通[{diff}] 求解 <2s", dt < 2.0, f"{dt:.2f}s")

    for diff in ("easy", "medium", "hard", "expert"):
        t = time.time()
        data = killer_core.make_killer(diff)
        dt = time.time() - t
        cages, sol = data["cages"], data["solution"]
        covered = {tuple(cell) for c in cages for cell in c["cells"]}
        check(f"杀手[{diff}] 覆盖全部 81 格", len(covered) == 81,
              f"cages={len(cages)} 耗时={dt:.2f}s")
        sums_ok, distinct_ok, conn_ok = True, True, True
        for c in cages:
            vals = [sol[r][cc] for (r, cc) in c["cells"]]
            if sum(vals) != c["sum"]:
                sums_ok = False
            if len(set(vals)) != len(vals):
                distinct_ok = False
            cells = set(tuple(x) for x in c["cells"])
            seen = {next(iter(cells))}
            frontier = [next(iter(cells))]
            while frontier:
                r, cc = frontier.pop()
                for nb in ((r - 1, cc), (r + 1, cc), (r, cc - 1), (r, cc + 1)):
                    if nb in cells and nb not in seen:
                        seen.add(nb)
                        frontier.append(nb)
            if seen != cells:
                conn_ok = False
        check(f"杀手[{diff}] cage 求和正确", sums_ok)
        check(f"杀手[{diff}] cage 内数字互异（杀手规则）", distinct_ok)
        check(f"杀手[{diff}] cage 连通", conn_ok)
        singletons = sum(1 for c in cages if len(c["cells"]) == 1)
        check(f"杀手[{diff}] 生成 <2s", dt < 2.0, f"{dt:.2f}s")
        check(f"杀手[{diff}] 没有单格 cage（否则'和'等于数字本身）",
              singletons == 0, f"单格={singletons}")

    # cage colouring must separate every pair of touching cages
    os.environ.setdefault("SUDOKU_SAVE_PATH", "-")
    import sudoku_floating as _sf
    bad_pairs, checked = 0, 0
    for _ in range(6):
        data = killer_core.make_killer("medium")
        colors = _sf.SudokuApp._make_cage_colors(None, data["cages"])
        owner = {}
        for i, cg in enumerate(data["cages"]):
            for (r, c) in cg["cells"]:
                owner[(r, c)] = i
        for i, cg in enumerate(data["cages"]):
            for (r, c) in cg["cells"]:
                for nb in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1),
                           (r - 1, c - 1), (r - 1, c + 1),
                           (r + 1, c - 1), (r + 1, c + 1)):
                    j = owner.get(nb)
                    if j is None or j == i:
                        continue
                    checked += 1
                    if colors[j] == colors[i]:
                        bad_pairs += 1
    check("相邻 cage 颜色一定不同（含斜角相接）", bad_pairs == 0,
          f"检查了 {checked} 对，撞色 {bad_pairs} 对")


# ------------------------------------------------------------------ gui layer
def _click_at(root, widget):
    """Send a real Button-1 to whatever widget is under the given point."""
    widget.event_generate("<Button-1>")


def _clear_digit(app, d):
    for r in range(9):
        for c in range(9):
            if app.values[r][c] == d:
                app.values[r][c] = 0
def test_gui(tmp_save):
    os.environ["SUDOKU_SAVE_PATH"] = tmp_save
    import sudoku_floating as sf

    print()
    print("== 界面层（tkinter）==")
    root = tk.Tk()
    app = sf.SudokuApp(root)
    root.update_idletasks()

    # -- candidate font must follow the zoom level
    sub0 = app.cand_labels[(0, 0)][0]
    sizes = {}
    for sc in (1.0, 1.3, 0.8):
        app._set_scale(sc)
        sizes[sc] = int(sub0.cget("font").split()[-1])
    check("候选字号随缩放变化", sizes[1.0] != sizes[1.3] != sizes[0.8],
          f"{sizes}")
    check("候选字号 = 基准*缩放",
          sizes[1.0] == sf.BASE_CAND_PT
          and sizes[1.3] == int(sf.BASE_CAND_PT * 1.3),
          f"{sizes}")

    # -- overlay check: an empty value label must not cover the candidate grid
    app._set_scale(1.0)
    app._toggle_candidates()
    app._toggle_mode()                      # killer, empty grid
    for _ in range(3):
        root.update_idletasks()
        root.update()
    r, c = 0, 0
    vl = app.val_labels[(r, c)]
    # NB: winfo_width() is stale once a widget is un-placed (it keeps the last
    # size), so visibility — not size — is the meaningful assertion here. A
    # placed-but-empty label would be ~18x37 and mask the candidate grid.
    check("空格不显示数字标签（不遮挡候选）", not vl.winfo_ismapped(),
          f"ismapped={vl.winfo_ismapped()} 残留尺寸={vl.winfo_width()}x{vl.winfo_height()}")
    # pick an anchor cell whose cage has a two-digit sum — that is exactly the
    # case that used to get clipped inside one tiny slot
    pick = next((cg for cg in app.cages if cg["sum"] >= 10), app.cages[0])
    ar, ac = app.cage_anchor[pick["id"]]
    sl = app.sum_labels[(ar, ac)]
    # The sum strip is ~2px taller than one 3x3 slot row, so it completely
    # hides the top three candidate slots of its anchor cell (1/2/3 or 4/5/6,
    # depending on where the anchor sits) — not just the characters it prints.
    strip_bottom = sl.winfo_rooty() + sl.winfo_height()
    hits = []
    for d in range(1, 10):
        lb = app.cand_labels[(ar, ac)][d - 1]
        cy = lb.winfo_rooty() + lb.winfo_height() // 2
        if cy < strip_bottom:                   # behind the sum strip
            continue
        cx = lb.winfo_rootx() + lb.winfo_width() // 2
        hit = root.winfo_containing(cx, cy)
        hits.append(hit is lb or hit is app.sum_labels[(ar, ac)])
    check("未被 cage 和占用的候选槽全部可见", hits and all(hits), f"{hits}")

    # -- the sum label must be tall AND wide enough for the digits it prints.
    # This is the bug the user hit: the label was locked to one ~11px candidate
    # slot while the font alone needs 13px of line box, so "23" came out with
    # its top sliced off and only one glyph readable.
    txt = sl.cget("text")
    f_sum = tkfont.Font(font=sl.cget("font"))
    text_w, line_h = f_sum.measure(txt), f_sum.metrics("linespace")
    check("cage 求和数不被裁断（高度放得下标签自身需求）",
          sl.winfo_height() >= sl.winfo_reqheight() - 1
          and sl.winfo_height() <= app._inner,
          f"标签高={sl.winfo_height()} 需要={sl.winfo_reqheight()} "
          f"行盒={line_h} sumH={app._sum_h}")
    check("cage 求和数不被裁断（宽度放得下整串数字）",
          sl.winfo_width() >= text_w and sl.winfo_width() <= app._inner,
          f"「{txt}」标签宽={sl.winfo_width()} 文字宽={text_w}")
    check("求和数标签没有压住 3x3 候选格",
          app._sum_h >= 0 and app._sum_h < app._inner,
          f"sumH={app._sum_h} inner={app._inner}")

    # every size preset must keep the two-digit sum legible
    bad_scales = []
    for sc in (sf.SCALE_MIN, 0.8, 1.0, 1.3, sf.SCALE_MAX):
        app._set_scale(sc)
        root.update_idletasks()
        two = [cg for cg in app.cages if cg["sum"] >= 10] or app.cages
        cg = max(two, key=lambda x: x["sum"])
        r2, c2 = app.cage_anchor[cg["id"]]
        s2 = app.sum_labels[(r2, c2)]
        app._paint_cell(r2, c2, set(), set(), set(), set(), time.monotonic())
        root.update_idletasks()
        f2 = tkfont.Font(font=s2.cget("font"))
        if s2.winfo_height() < f2.metrics("linespace") \
                or s2.winfo_width() < f2.measure(s2.cget("text")):
            bad_scales.append((sc, cg["sum"], s2.winfo_width(),
                               f2.measure(s2.cget("text")),
                               s2.winfo_height(), f2.metrics("linespace")))
    app._set_scale(1.0)
    check("所有缩放下两位数求和都放得下", not bad_scales, f"{bad_scales}")
    check("最小缩放不低于容纳求和数的下限",
          sf.SCALE_MIN >= 0.7, f"SCALE_MIN={sf.SCALE_MIN}")

    # -- cage outlines are drawn only where two cages actually meet
    # -- outline: every seam between two different cages is drawn exactly once
    seams_ok = True
    for r in range(9):
        for c in range(9):
            plan_here = app.cage_edge_plan.get((r, c), ())
            if r + 1 < 9 and app.cage_of[(r, c)] != app.cage_of[(r + 1, c)]:
                drawn = ("top" in app.cage_edge_plan.get((r + 1, c), ())
                         or ("bottom" in plan_here and r == 8))
                seams_ok &= drawn
            if c + 1 < 9 and app.cage_of[(r, c)] != app.cage_of[(r, c + 1)]:
                drawn = ("left" in app.cage_edge_plan.get((r, c + 1), ())
                         or ("right" in plan_here and c == 8))
                seams_ok &= drawn
    check("每条 cage 分界线都被画出来（且不重复）", seams_ok)
    total = sum(len(v) for v in app.cage_edge_plan.values())
    check("描边总数在合理范围", 0 < total <= 81 * 4, f"{total}")

    # -- win detection, both modes
    app._toggle_mode()
    if app.mode != "normal":
        app._toggle_mode()
    app.new_game()
    app.values = [row[:] for row in app.solution]
    app._check_win()
    check("普通模式填满正确解 -> 判完成",
          "完成" in app.status_lbl.cget("text"))

    app._toggle_mode()                      # -> killer
    app.values = [row[:] for row in app.solution]
    app._check_win()
    check("杀手模式填满正确解 -> 判完成",
          "完成" in app.status_lbl.cget("text"),
          f"bad_cages={len(app._bad_cages())}")

    # -- save / reload round trip (killer cages survive JSON)
    app._save()
    root2 = tk.Tk()
    app2 = sf.SudokuApp(root2)
    root2.update_idletasks()
    ok = app2.mode == "killer" and len(app2.cages or []) == len(app.cages)
    check("杀手档重载后 mode/cages 一致", ok,
          f"{app2.mode} cages={len(app2.cages or [])}")
    anchor = app2.cage_anchor[app2.cages[0]["id"]]
    check("cage 锚点重载后仍是元组", isinstance(anchor, tuple), f"{anchor}")
    app2.values = [row[:] for row in app2.solution]
    app2._check_win()
    check("重载后填正确解 -> 判完成",
          "完成" in app2.status_lbl.cget("text"))
    root2.destroy()

    # -- givens are read-only in normal mode
    app._toggle_mode()                      # -> normal
    app.new_game()
    g = [(r, c) for r in range(9) for c in range(9) if app.given[r][c]][0]
    app._select(*g)
    before = app.values[g[0]][g[1]]
    app._input(before % 9 + 1)
    check("普通模式给定格不可修改",
          app.values[g[0]][g[1]] == before,
          f"{g} 保持 {before}")

    # -- no-op input must not pollute the undo stack
    e = [(r, c) for r in range(9) for c in range(9) if not app.given[r][c]][0]
    app._select(*e)
    app._input(3)
    n1 = len(app.undo_stack)
    app._input(0)
    n2 = len(app.undo_stack)
    app._input(0)
    n3 = len(app.undo_stack)
    check("空操作不写入撤销栈", n2 == n1 + 1 and n3 == n2,
          f"{n1} -> {n2} -> {n3}")

    # -- arrow keys map to the right direction (was rotated 90 degrees)
    for key, expect in [("Left", (4, 3)), ("Right", (4, 5)),
                        ("Up", (3, 4)), ("Down", (5, 4))]:
        app._select(4, 4)
        app._on_key(_FakeKey(key))
        check(f"方向键 {key} -> {expect}", app.selected == expect,
              f"实际 {app.selected}")
    app._select(0, 0)
    app._on_key(_FakeKey("Up"))
    check("方向键边界环绕", app.selected == (8, 0), f"{app.selected}")

    # -- typing / erasing
    app._select(*e)
    app._on_key(_FakeKey("7"))
    typed = app.values[e[0]][e[1]]
    app._on_key(_FakeKey("BackSpace"))
    check("键盘 1-9 填入 / Backspace 擦除",
          typed == 7 and app.values[e[0]][e[1]] == 0)

    # -- double-space hide timing
    fired = []
    app.can_restore = True
    real_hide = app._hide
    app._hide = lambda: fired.append(1)
    app._last_space = 0
    app._on_key(_FakeKey("space"))
    one = len(fired)
    app._on_key(_FakeKey("space"))
    two = len(fired)
    app._on_key(_FakeKey("space"))
    time.sleep(0.6)
    app._on_key(_FakeKey("space"))
    check("连按两下空格才隐藏（间隔>0.5s 不触发）",
          one == 0 and two == 1 and len(fired) == 1,
          f"{one} / {two} / {len(fired)}")
    app._hide = real_hide

    root.destroy()


# ------------------------------------------------- round 7: interaction fixes
def test_interactions(tmp_save):
    os.environ["SUDOKU_SAVE_PATH"] = tmp_save
    import sudoku_floating as sf

    print()
    print("== 交互修复（选中 / 阴影 / 笔注 / 九宫 / 全绿 / 动画）==")
    root = tk.Tk()
    app = sf.SudokuApp(root)
    app.mode = "normal"
    app.new_game()
    for _ in range(3):
        root.update_idletasks()
        root.update()

    # -- 2. clicking ANY pixel of an empty cell must select it.
    # Tk only consults the bindtags of the widget actually hit — (widget,
    # widgetClass, toplevel, all) — and the parent frame is not among them,
    # so binding the frame alone never fired once candidates tiled the cell.
    misses = []
    for (r, c) in [(0, 0), (4, 4), (8, 8), (2, 7)]:
        f = app.cell_frames[(r, c)]
        for fx, fy in ((0.5, 0.5), (0.15, 0.15), (0.85, 0.85)):
            x = f.winfo_rootx() + int(f.winfo_width() * fx)
            y = f.winfo_rooty() + int(f.winfo_height() * fy)
            hit = root.winfo_containing(x, y)
            if hit is None:
                misses.append(((r, c), fx, fy, "point outside the window"))
                continue
            app.selected = None
            hit.event_generate("<Button-1>")
            root.update_idletasks()
            if app.selected != (r, c):
                misses.append(((r, c), fx, fy, str(hit)))
    check("点击空白格的任意位置都能选中", not misses, f"{misses[:3]}")

    # -- 1. live row / column / box shading
    app._select(4, 4)
    peer_bg = app.cell_frames[(4, 0)].cget("bg")
    box_bg = app.cell_frames[(3, 3)].cget("bg")
    far_bg = app.cell_frames[(0, 0)].cget("bg")
    check("同行同列 + 当前九宫格有阴影",
          peer_bg != far_bg and box_bg == peer_bg,
          f"同行={peer_bg} 宫={box_bg} 非同行={far_bg}")
    check("选中格自身用另一种底色",
          app.cell_frames[(4, 4)].cget("bg") != peer_bg,
          f"{app.cell_frames[(4, 4)].cget('bg')}")
    check("同列 = 同行 = 同宫 阴影一致",
          app.cell_frames[(0, 4)].cget("bg") == peer_bg)

    # -- 3a. Ctrl + digit -> pencil mark (no value written)
    e = [(r, c) for r in range(9) for c in range(9) if not app.given[r][c]][0]
    app._select(*e)
    app._on_key(_FakeKey("5", state=0x4))
    check("Ctrl+数字写入笔注而非落子",
          app.values[e[0]][e[1]] == 0 and app.pencils[e[0]][e[1]] == {5},
          f"值={app.values[e[0]][e[1]]} 笔注={app.pencils[e[0]][e[1]]}")
    app.undo()
    check("笔注可撤销", app.pencils[e[0]][e[1]] == set(),
          f"{app.pencils[e[0]][e[1]]}")

    app._apply_pencil([e], 7)
    shown = [(d, app.cand_labels[e][d - 1].cget("text"))
             for d in range(1, 10)
             if app.cand_labels[e][d - 1].cget("text")]
    check("笔注渲染为格内小字", shown == [(7, "7")], f"{shown}")
    app._apply_pencil([e], 7)

    was = app.pencil_mode
    app._on_key(_FakeKey("Control_L"))
    app._on_key_release(_FakeKey("Control_L"))
    check("单独按一下 Ctrl 切换笔注模式", app.pencil_mode != was,
          f"{was} -> {app.pencil_mode}")
    app._toggle_pencil_mode()

    # -- 3a'. Shift 多选 + Ctrl+数字 批量笔注
    a, b = (0, 0), (0, 1)
    app._select(*a)
    app._select(*b, shift=True)
    check("Shift+点击加入多选集合",
          app.selection == {a, b} and app.selected == b,
          f"{app.selection}")
    app._pencil_input(3)          # 等价于 Ctrl+数字 的作用对象
    check("Ctrl+数字 批量笔注写入所有选中格",
          app.pencils[a[0]][a[1]] == {3} and app.pencils[b[0]][b[1]] == {3})
    app._select(*a, shift=True)
    check("Shift 再点一次从集合移除该格",
          app.selection == {b}, f"{app.selection}")
    app._select(*b, shift=True)   # 移除后回到单选 b
    app._select(*a)               # 复位为单选 a（供后续用例）

    # -- 3a''. 点空白取消选择（专注思考）
    app._select(*a)
    app._suppress_deselect = False
    app._on_root_click(None)
    check("点空白取消选择", app.selected is None and app.selection == set())

    # -- 3b. QWE/ASD/ZXC nine-grid input
    app.nine_grid = False
    app._select(*e)
    app._on_key(_FakeKey("q"))
    check("九宫输入关闭时 Q 不生效", app.values[e[0]][e[1]] == 0)
    app.nine_grid = True
    ok9 = True
    for key, val in [("q", 1), ("w", 2), ("e", 3), ("a", 4), ("s", 5),
                     ("d", 6), ("z", 7), ("x", 8), ("c", 9)]:
        app._select(*e)
        app._on_key(_FakeKey(key))
        ok9 &= app.values[e[0]][e[1]] == val
        app._input(0)
    check("九宫输入 QWE/ASD/ZXC -> 1..9", ok9)
    app.values[e[0]][e[1]] = 3
    app._on_key(_FakeKey("z", state=0x4))          # Ctrl+Z must win over "z"
    check("Ctrl+Z 优先于九宫格的 Z", app.values[e[0]][e[1]] != 7,
          f"{app.values[e[0]][e[1]]}")
    app.nine_grid = False

    # -- 4a. nine-for-nine green feedback
    app.new_game()
    _clear_digit(app, 1)
    ones = [(r, c) for r in range(9) for c in range(9)
            if app.solution[r][c] == 1]
    for cell in ones[:-1]:
        app.values[cell[0]][cell[1]] = 1
    app._check_done_digits()
    check("某数字只填了 8 个 -> 不反馈", len(app.flash) == 0,
          f"{len(app.flash)}")
    app.values[ones[-1][0]][ones[-1][1]] = 1
    app._check_done_digits()
    app._render()
    bgs = {app.cell_frames[cell].cget("bg") for cell in ones}
    check("九格全填对 -> 触发全绿反馈", len(app.flash) == 9, f"{len(app.flash)}")
    check("全绿真的画到了格子上", bgs == {sf.FLASH_BG}, f"{bgs}")

    # -- 4b. win: diagonal wipe starting at r1c1
    app.new_game()
    app.values = [row[:] for row in app.solution]
    app._check_win()
    order = getattr(app, "_vanish_order", [])
    check("消失动画从 r1c1 开始", order[:1] == [(0, 0)], f"{order[:2]}")
    check("动画覆盖全部 81 格且不重复",
          len(order) == 81 and len(set(order)) == 81, f"{len(order)}")
    check("每条对角线内自上而下（朝左下角推进）",
          order[1:3] == [(0, 1), (1, 0)], f"{order[:4]}")
    app._stop_anim()
    check("动画可中止，棋盘不会卡在消失态", app.vanished == set())

    # -- 杀手简单/中等模式应预置若干给定数字作为提示
    for diff in ("easy", "medium", "hard", "expert"):
        app.difficulty = diff
        app.mode = "killer"
        app.new_game()
        expect = sf._KILLER_GIVENS[diff]
        given = sum(1 for r in range(9) for c in range(9)
                    if app.given[r][c])
        check(f"杀手[{diff}] 给定数字数 = {expect}", given == expect,
              f"实际 {given}")
        ok = all(not app.given[r][c]
                 or app.values[r][c] == app.solution[r][c]
                 for r in range(9) for c in range(9))
        check(f"杀手[{diff}] 给定数字与解一致", ok)
    app.mode = "normal"
    root.destroy()


class _FakeKey:
    def __init__(self, keysym, state=0):
        self.keysym = keysym
        self.state = state


def main():
    tmp = os.path.join(tempfile.gettempdir(), "sudoku_selftest_save.json")
    if os.path.exists(tmp):
        os.remove(tmp)
    try:
        test_generation()
        test_gui(tmp)
        test_interactions(tmp)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
        os.environ.pop("SUDOKU_SAVE_PATH", None)

    print()
    if FAILS:
        print(f"FAILED ({len(FAILS)}):")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
