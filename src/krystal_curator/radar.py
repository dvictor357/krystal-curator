"""Braille radar (spider) chart as a Rich Text — one axis per score component."""

from __future__ import annotations

import math

from rich.text import Text

# braille dot bit for (dx in 0..1, dy in 0..3)
_DOT = ((0x01, 0x02, 0x04, 0x40), (0x08, 0x10, 0x20, 0x80))

STYLE_GRID = "grey35"
STYLE_FILL = "#a05e00"
STYLE_EDGE = "bold #ffb000"
STYLE_LABEL = "bold white"
STYLE_VALUE = "#ffb000"


class _Canvas:
    def __init__(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows
        self.w, self.h = cols * 2, rows * 4
        self.dots = [[0] * cols for _ in range(rows)]
        self.layer = [[0] * cols for _ in range(rows)]  # 0 none, 1 grid, 2 fill, 3 edge

    def plot(self, x: float, y: float, layer: int) -> None:
        xi, yi = round(x), round(y)
        if 0 <= xi < self.w and 0 <= yi < self.h:
            c, r = xi // 2, yi // 4
            self.dots[r][c] |= _DOT[xi % 2][yi % 4]
            self.layer[r][c] = max(self.layer[r][c], layer)

    def line(self, x0: float, y0: float, x1: float, y1: float, layer: int) -> None:
        n = max(1, int(max(abs(x1 - x0), abs(y1 - y0))))
        for i in range(n + 1):
            t = i / n
            self.plot(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, layer)

    def fill(self, pts: list[tuple[float, float]], layer: int) -> None:
        """Even-odd scanline fill, every other pixel so the fill reads as a tint."""
        ys = [p[1] for p in pts]
        for y in range(int(min(ys)), int(max(ys)) + 1):
            xs: list[float] = []
            for i, (x0, y0) in enumerate(pts):
                x1, y1 = pts[(i + 1) % len(pts)]
                if (y0 <= y < y1) or (y1 <= y < y0):
                    xs.append(x0 + (y - y0) * (x1 - x0) / (y1 - y0))
            xs.sort()
            for a, b in zip(xs[::2], xs[1::2], strict=False):
                for x in range(math.ceil(a), int(b) + 1):
                    if (x + y) % 2 == 0:
                        self.plot(x, y, layer)


def render_radar(
    values: list[tuple[str, float]], *, cols: int = 44, rows: int = 15, show_values: bool = True
) -> Text:
    """values: [(label, 0..1), ...] drawn clockwise from 12 o'clock."""
    n = len(values)
    cv = _Canvas(cols, rows)
    cx, cy = cv.w / 2, cv.h / 2
    rx, ry = cv.w * 0.30, cv.h * 0.42  # leave a ring of cells for labels

    def pt(i: int, r: float) -> tuple[float, float]:
        a = -math.pi / 2 + 2 * math.pi * i / n
        return cx + rx * r * math.cos(a), cy + ry * r * math.sin(a)

    # grid rings + spokes
    for ring in (0.25, 0.5, 0.75, 1.0):
        ring_pts = [pt(i, ring) for i in range(n)]
        for i in range(n):
            x0, y0 = ring_pts[i]
            x1, y1 = ring_pts[(i + 1) % n]
            cv.line(x0, y0, x1, y1, 1)
    for i in range(n):
        cv.line(cx, cy, *pt(i, 1.0), 1)

    # data polygon
    data = [pt(i, max(0.0, min(1.0, v))) for i, (_, v) in enumerate(values)]
    cv.fill(data, 2)
    for i in range(n):
        x0, y0 = data[i]
        x1, y1 = data[(i + 1) % n]
        cv.line(x0, y0, x1, y1, 3)

    # rasterise cells
    grid: list[list[tuple[str, str]]] = [
        [
            (chr(0x2800 + cv.dots[r][c]) if cv.dots[r][c] else " ", _style(cv.layer[r][c]))
            for c in range(cols)
        ]
        for r in range(rows)
    ]

    # labels at each vertex, pushed outward
    for i, (label, v) in enumerate(values):
        x, y = pt(i, 1.0)
        c, r = int(x // 2), int(y // 4)
        a = -math.pi / 2 + 2 * math.pi * i / n
        text = f"{label} {v:.2f}" if show_values else label
        dx, dy = math.cos(a), math.sin(a)
        if abs(dx) < 0.3:  # top / bottom: centre
            r += -1 if dy < 0 else 1
            c -= len(text) // 2
        elif dx > 0:  # right side
            c += 3
        else:  # left side: right-align
            c -= len(text) + 2
        r = max(0, min(rows - 1, r))
        c = max(0, min(cols - len(text), c))
        for k, ch in enumerate(text):
            style = STYLE_LABEL if k < len(label) else STYLE_VALUE
            grid[r][c + k] = (ch, style)

    out = Text(no_wrap=True, overflow="crop")
    for r, row in enumerate(grid):
        for ch, style in row:
            out.append(ch, style=style or None)
        if r < rows - 1:
            out.append("\n")
    return out


def _style(layer: int) -> str:
    return {1: STYLE_GRID, 2: STYLE_FILL, 3: STYLE_EDGE}.get(layer, "")
