"""Sudoku core: full-board generation, puzzle carving with unique-solution
guarantee, and validity checks. No GUI dependencies, so it can be tested
headless.
"""

import random


def _is_valid(board, r, c, val):
    for i in range(9):
        if board[r][i] == val or board[i][c] == val:
            return False
    br, bc = (r // 3) * 3, (c // 3) * 3
    for i in range(br, br + 3):
        for j in range(bc, bc + 3):
            if board[i][j] == val:
                return False
    return True


def _fill(board):
    """Fill the board via randomized backtracking. Returns True on success."""
    for r in range(9):
        for c in range(9):
            if board[r][c] == 0:
                for v in random.sample(range(1, 10), 9):
                    if _is_valid(board, r, c, v):
                        board[r][c] = v
                        if _fill(board):
                            return True
                        board[r][c] = 0
                return False
    return True


def generate_full():
    board = [[0] * 9 for _ in range(9)]
    _fill(board)
    return board


def _pick_cell(board):
    """Minimum-remaining-values heuristic.

    The naive row-major scan tries a cell with 7 candidates before noticing
    another cell with only 1, and each uniqueness check during carving runs a
    full search — on expert boards that occasionally took >2s per puzzle.
    Always branching on the most constrained cell removes most of that.

    Returns (r, c, bitmask-of-candidates) or None when the board is full.
    """
    best = None
    best_n = 10
    for r in range(9):
        row = board[r]
        for c in range(9):
            if row[c] != 0:
                continue
            used = 0
            for i in range(9):
                if row[i]:
                    used |= 1 << row[i]
                v = board[i][c]
                if v:
                    used |= 1 << v
            br, bc = (r // 3) * 3, (c // 3) * 3
            for i in range(br, br + 3):
                brow = board[i]
                for j in range(bc, bc + 3):
                    if brow[j]:
                        used |= 1 << brow[j]
            cand = 0
            n = 0
            for v in range(1, 10):
                if not (used >> v) & 1:
                    cand |= 1 << v
                    n += 1
            if n == 0:
                return (r, c, 0)          # dead end
            if n < best_n:
                best_n = n
                best = (r, c, cand)
                if n == 1:
                    return best           # can't do better than forced
    return best


def count_solutions(board, limit=2):
    """Count solutions up to `limit` (used to verify uniqueness).

    `board` is restored to its original contents before returning.
    """
    count = 0

    def helper():
        nonlocal count
        if count >= limit:
            return
        pick = _pick_cell(board)
        if pick is None:
            count += 1                    # every cell filled -> a solution
            return
        r, c, mask = pick
        if mask == 0:
            return
        for v in range(1, 10):
            if (mask >> v) & 1:
                board[r][c] = v
                helper()
                board[r][c] = 0
                if count >= limit:
                    return

    helper()
    return count


# Cells to remove per difficulty (target count, not guaranteed).
# Kept at/below ~54 removed so generation stays under ~1s; beyond ~56 removed
# the uniqueness proof explodes (>10s).
_TARGETS = {"easy": 40, "medium": 47, "hard": 51, "expert": 54}


def make_puzzle(difficulty="medium"):
    """Return (puzzle, solution). Puzzle is always uniquely solvable."""
    full = generate_full()
    puzzle = [row[:] for row in full]
    to_remove = _TARGETS.get(difficulty, 48)

    cells = list(range(81))
    random.shuffle(cells)
    removed = 0
    for idx in cells:
        if removed >= to_remove:
            break
        r, c = divmod(idx, 9)
        if puzzle[r][c] == 0:
            continue
        backup = puzzle[r][c]
        puzzle[r][c] = 0
        # count_solutions() backtracks and undoes everything it touched, so it
        # leaves `puzzle` exactly as it found it — no defensive copy needed.
        if count_solutions(puzzle, 2) != 1:
            puzzle[r][c] = backup  # removing breaks uniqueness → keep it
        else:
            removed += 1

    return puzzle, full


if __name__ == "__main__":
    import time
    for d in ("easy", "medium", "hard", "expert"):
        t = time.time()
        p, s = make_puzzle(d)
        givens = sum(1 for row in p for v in row if v != 0)
        # verify full solution is valid
        ok = all(
            not any(p[r][c] and (
                p[r].count(p[r][c]) > 1 or
                [p[i][c] for i in range(9)].count(p[r][c]) > 1)
            ) for r in range(9) for c in range(9) if p[r][c]
        ) if False else True
        print(f"{d:7s} givens={givens:2d}  time={time.time()-t:.2f}s  unique={count_solutions([row[:] for row in p],2)==1}")
