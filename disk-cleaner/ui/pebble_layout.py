"""石头地图的几何：把一个矩形按面积切成一块块凸多边形，再缩边、倒圆角，像铺满的小石头。

做法：按大小把项目分成两组，用一条略微倾斜的直线把区域切开，
两边面积之比 = 两组大小之比，然后递归。切线是共享的，所以缩边后缝隙宽度均匀。
不依赖 tkinter，可以单独测试。
"""
from __future__ import annotations

import math
import random
from typing import Sequence

Point = tuple[float, float]
Poly = list[Point]


def area(poly: Sequence[Point]) -> float:
    s = 0.0
    for i, (x1, y1) in enumerate(poly):
        x2, y2 = poly[(i + 1) % len(poly)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def centroid(poly: Sequence[Point]) -> Point:
    a = cx = cy = 0.0
    for i, (x1, y1) in enumerate(poly):
        x2, y2 = poly[(i + 1) % len(poly)]
        c = x1 * y2 - x2 * y1
        a += c
        cx += (x1 + x2) * c
        cy += (y1 + y2) * c
    if abs(a) < 1e-9:
        return (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))
    return (cx / (3 * a), cy / (3 * a))


def bbox(poly: Sequence[Point]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def clip(poly: Sequence[Point], n: Point, c: float) -> Poly:
    """保留满足 n·p <= c 的部分（Sutherland–Hodgman）。"""
    out: Poly = []
    m = len(poly)
    for i in range(m):
        p, q = poly[i], poly[(i + 1) % m]
        dp = n[0] * p[0] + n[1] * p[1] - c
        dq = n[0] * q[0] + n[1] * q[1] - c
        if dp <= 0:
            out.append(p)
        if (dp < 0 < dq) or (dq < 0 < dp):
            t = dp / (dp - dq)
            out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
    return _dedupe(out)


def _dedupe(poly: Poly, eps: float = 1e-6) -> Poly:
    out: Poly = []
    for p in poly:
        if not out or abs(p[0] - out[-1][0]) > eps or abs(p[1] - out[-1][1]) > eps:
            out.append(p)
    if len(out) > 1 and abs(out[0][0] - out[-1][0]) <= eps and abs(out[0][1] - out[-1][1]) <= eps:
        out.pop()
    return out


def split(poly: Poly, frac: float, angle: float) -> tuple[Poly, Poly]:
    """用法向为 angle 的直线切开，使第一块面积占 frac。"""
    n = (math.cos(angle), math.sin(angle))
    dots = [n[0] * x + n[1] * y for x, y in poly]
    lo, hi = min(dots), max(dots)
    target = frac * area(poly)
    for _ in range(50):
        mid = (lo + hi) / 2
        if area(clip(poly, n, mid)) < target:
            lo = mid
        else:
            hi = mid
    c = (lo + hi) / 2
    return clip(poly, n, c), clip(poly, (-n[0], -n[1]), -c)


def layout(items: Sequence[tuple[str, float]], poly: Poly, seed: int = 7,
           tilt_deg: float = 18) -> dict[str, Poly]:
    """items: (key, value)。返回 key → 多边形，面积与 value 成比例。"""
    rng = random.Random(seed)
    items = sorted(((k, v) for k, v in items if v > 0), key=lambda kv: -kv[1])
    out: dict[str, Poly] = {}

    def rec(group, region):
        if not group:
            return
        if len(group) == 1:
            out[group[0][0]] = region
            return
        total = sum(v for _, v in group)
        # 找最接近一半的切分点
        best_k, best_d, acc = 1, float("inf"), 0.0
        for k in range(1, len(group)):
            acc += group[k - 1][1]
            d = abs(acc - total / 2)
            if d < best_d:
                best_k, best_d = k, d
        a, b = group[:best_k], group[best_k:]
        if rng.random() < 0.5:
            a, b = b, a
        x0, y0, x1, y1 = bbox(region)
        base = 0.0 if (x1 - x0) >= (y1 - y0) else math.pi / 2
        angle = base + math.radians(rng.uniform(-tilt_deg, tilt_deg))
        ra, rb = split(region, sum(v for _, v in a) / total, angle)
        rec(a, ra)
        rec(b, rb)

    rec(items, poly)
    return out


def _ccw(poly: Poly) -> Poly:
    s = sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
            for i in range(len(poly)))
    return poly if s > 0 else list(reversed(poly))


def inset(poly: Poly, d: float) -> Poly | None:
    """凸多边形每条边向内平移 d。太小缩没了返回 None。"""
    poly = _ccw(_dedupe(list(poly)))
    m = len(poly)
    if m < 3:
        return None
    # 屏幕坐标 y 向下，_ccw 按数学方向算，向内法向为 (-dy, dx) 取反后的一侧，用面积检验
    lines = []
    for i in range(m):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % m]
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy)
        if L < 1e-9:
            continue
        nx, ny = -dy / L, dx / L  # 逆时针多边形的左侧 = 内侧
        lines.append(((x1 + nx * d, y1 + ny * d), (dx, dy)))
    pts: Poly = []
    k = len(lines)
    for i in range(k):
        (p1, d1), (p2, d2) = lines[i - 1], lines[i]
        cross = d1[0] * d2[1] - d1[1] * d2[0]
        if abs(cross) < 1e-9:
            pts.append(p2)
            continue
        t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / cross
        pts.append((p1[0] + t * d1[0], p1[1] + t * d1[1]))
    # 检查每条边方向没翻转（翻转说明缩没了）
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        ex, ey = b[0] - a[0], b[1] - a[1]
        dx, dy = lines[i][1]
        if ex * dx + ey * dy <= 0:
            return None
    return pts if area(pts) > 1 else None


def rounded(poly: Poly, radius: float, steps: int = 7) -> Poly:
    """每个角用二次贝塞尔曲线倒圆角，返回采样后的点。"""
    m = len(poly)
    out: Poly = []
    for i in range(m):
        a, v, b = poly[i - 1], poly[i], poly[(i + 1) % m]
        la = math.hypot(a[0] - v[0], a[1] - v[1])
        lb = math.hypot(b[0] - v[0], b[1] - v[1])
        r = min(radius, 0.48 * la, 0.48 * lb)
        if r <= 0.5:
            out.append(v)
            continue
        p1 = (v[0] + (a[0] - v[0]) / la * r, v[1] + (a[1] - v[1]) / la * r)
        p2 = (v[0] + (b[0] - v[0]) / lb * r, v[1] + (b[1] - v[1]) / lb * r)
        for s in range(steps + 1):
            t = s / steps
            u = 1 - t
            out.append((u * u * p1[0] + 2 * u * t * v[0] + t * t * p2[0],
                        u * u * p1[1] + 2 * u * t * v[1] + t * t * p2[1]))
    return out


def inner_box(poly: Poly) -> tuple[float, float]:
    """粗略估计能放下文字的宽高（取包围盒的 70%）。"""
    x0, y0, x1, y1 = bbox(poly)
    return (x1 - x0) * 0.7, (y1 - y0) * 0.7
