"""Killer Sudoku generation: a full valid solution plus a random partition of
the 9x9 grid into connected cages, each annotated with the sum of its cells'
solution values.

No GUI dependencies. `make_killer(difficulty)` returns:
    {
        "solution": 9x9 list of ints (the underlying valid grid),
        "cages":    list of {"id", "cells":[(r,c)...], "sum":int, "anchor":(r,c)},
        "cage_of":  {(r,c): cage_id},
    }

The puzzle is played with NO given digits — only the cage outlines and their
sums are shown. Any full grid that satisfies standard sudoku rules plus the
cage sums (and cage-internal digit distinctness) is a valid solution.
"""

import random

from sudoku_core import generate_full

# Target cage-size range (inclusive) per difficulty. Smaller cages are more
# constraining, hence harder.
_CAGE_SIZES = {
    "easy": (4, 6),
    "medium": (3, 5),
    "hard": (2, 4),
    "expert": (2, 3),
}


def _neighbors(r, c):
    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nr, nc = r + dr, c + dc
        if 0 <= nr < 9 and 0 <= nc < 9:
            yield nr, nc


def _is_connected(cells):
    """True when the cell set is 4-connected (a cage may not be split)."""
    s = set(cells)
    if len(s) <= 1:
        return True
    seen = {next(iter(s))}
    stack = list(seen)
    while stack:
        cur = stack.pop()
        for nb in _neighbors(*cur):
            if nb in s and nb not in seen:
                seen.add(nb)
                stack.append(nb)
    return len(seen) == len(s)


def _absorb_singletons(solution, cages, cage_of, max_size):
    """Merge 1-cell cages into a neighbour.

    A single-cell cage is technically legal, but its "sum" is just the digit
    itself, so players read it as a broken cage / a wrong sum. Two strategies:
      1. hand the cell over to an adjacent cage;
      2. if no neighbour can take it (all full, or the digit would repeat),
         steal one cell back from a neighbouring cage so the pair can grow.
    Both keep every cage connected and every cage's digits distinct, otherwise
    the cage could never be filled legally.
    """
    for pass_no in range(8):
        allow_thin_source = pass_no >= 5      # last resort: rob a 2-cell cage
        by_id = {cg["id"]: cg for cg in cages}
        singles = [cg for cg in cages if len(cg["cells"]) == 1]
        if not singles:
            break
        merged_any = False
        for cage in singles:
            (r, c) = cage["cells"][0]
            options = []
            for nb in _neighbors(r, c):
                nid = cage_of.get(nb)
                if nid is None or nid == cage["id"]:
                    continue
                other = by_id.get(nid)
                if other is None or len(other["cells"]) >= max_size:
                    continue
                vals = {solution[a][b] for (a, b) in other["cells"]}
                if solution[r][c] in vals:
                    continue  # would break cage-internal distinctness
                options.append((len(other["cells"]), nid))
            if options:
                options.sort()                # give it to the smallest cage
                target = by_id[options[0][1]]
                target["cells"] = target["cells"] + cage["cells"]
                for cell in cage["cells"]:
                    cage_of[cell] = target["id"]
                cages.remove(cage)
                merged_any = True
                continue

            # ---- strategy 2: take a cell from a neighbouring cage ----
            for nb in _neighbors(r, c):
                nid = cage_of.get(nb)
                if nid is None or nid == cage["id"]:
                    continue
                other = by_id.get(nid)
                if other is None:
                    continue
                if len(other["cells"]) < 3 and not allow_thin_source:
                    continue                  # would only move the singleton
                if solution[nb[0]][nb[1]] == solution[r][c]:
                    continue                  # duplicate digit in the new cage
                rest = [x for x in other["cells"] if x != nb]
                if not _is_connected(rest):
                    continue                  # would tear the donor in two
                other["cells"] = rest
                cage["cells"] = cage["cells"] + [nb]
                cage_of[nb] = cage["id"]
                merged_any = True
                break
        if not merged_any:
            break

    # ids/sums/anchors are recomputed from scratch: merges made them stale
    out = []
    for i, cg in enumerate(cages):
        cg["id"] = i
        cg["sum"] = sum(solution[a][b] for (a, b) in cg["cells"])
        cg["anchor"] = min(cg["cells"], key=lambda x: (x[0], x[1]))
        out.append(cg)
    return out


def _generate_cages(solution, difficulty):
    lo, hi = _CAGE_SIZES.get(difficulty, (3, 5))
    assigned = [[False] * 9 for _ in range(9)]
    cages = []

    seeds = list(range(81))
    random.shuffle(seeds)
    cid = 0
    for idx in seeds:
        r, c = divmod(idx, 9)
        if assigned[r][c]:
            continue
        target = random.randint(lo, hi)
        cage_cells = [(r, c)]
        cage_vals = {solution[r][c]}
        assigned[r][c] = True
        frontier = [nb for nb in _neighbors(r, c) if not assigned[nb[0]][nb[1]]]
        while len(cage_cells) < target and frontier:
            random.shuffle(frontier)
            picked = None
            for i, (fr, fc) in enumerate(frontier):
                # Killer-sudoku core rule: digits inside a cage must be distinct.
                # Skip a neighbour whose solution value already appears in this
                # cage, otherwise the cage could never be completed legally.
                if solution[fr][fc] in cage_vals:
                    continue
                picked = (fr, fc)
                frontier.pop(i)
                break
            if picked is None:
                break  # every remaining neighbour would break distinctness
            assigned[picked[0]][picked[1]] = True
            cage_cells.append(picked)
            cage_vals.add(solution[picked[0]][picked[1]])
            for nb in _neighbors(*picked):
                if not assigned[nb[0]][nb[1]]:
                    frontier.append(nb)
        s = sum(solution[rr][cc] for rr, cc in cage_cells)
        anchor = min(cage_cells, key=lambda x: (x[0], x[1]))
        cages.append({"id": cid, "cells": cage_cells, "sum": s, "anchor": anchor})
        cid += 1

    cage_of = {}
    for cage in cages:
        for cell in cage["cells"]:
            cage_of[cell] = cage["id"]
    cages = _absorb_singletons(solution, cages, cage_of, hi + 1)
    cage_of = {}
    for cage in cages:
        for cell in cage["cells"]:
            cage_of[cell] = cage["id"]
    return cages, cage_of


def make_killer(difficulty="medium"):
    """Generate a killer sudoku puzzle definition (see module docstring)."""
    solution = generate_full()
    cages, cage_of = _generate_cages(solution, difficulty)
    return {"solution": solution, "cages": cages, "cage_of": cage_of, "size": len(cages)}


if __name__ == "__main__":
    import time

    # Self-check: cages must cover all 81 cells, be connected, and sums must
    # match the underlying solution.
    for d in ("easy", "medium", "hard", "expert"):
        t = time.time()
        data = make_killer(d)
        sol = data["solution"]
        cages = data["cages"]
        cage_of = data["cage_of"]

        cover = all((r, c) in cage_of for r in range(9) for c in range(9))
        # connectivity per cage (BFS)
        connected = True
        for cage in cages:
            seen = {cage["cells"][0]}
            frontier = list(cage["cells"])
            while frontier:
                cur = frontier.pop()
                for nb in _neighbors(*cur):
                    if nb in cage["cells"] and nb not in seen:
                        seen.add(nb)
                        frontier.append(nb)
            if len(seen) != len(cage["cells"]):
                connected = False
        sums_ok = all(
            sum(sol[r][c] for (r, c) in cage["cells"]) == cage["sum"] for cage in cages
        )
        # killer rule: digits inside a cage must be distinct
        distinct_ok = all(
            len({sol[r][c] for (r, c) in cage["cells"]}) == len(cage["cells"])
            for cage in cages
        )
        singletons = sum(1 for c in cages if len(c["cells"]) == 1)
        print(f"{d:7s} cages={len(cages):2d} cover={cover} connected={connected} "
              f"sums_ok={sums_ok} distinct_ok={distinct_ok} "
              f"单格cage={singletons} 耗时={time.time()-t:.2f}s")
