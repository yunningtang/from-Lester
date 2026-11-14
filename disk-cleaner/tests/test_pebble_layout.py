import pytest

from ui.pebble_layout import area, inset, layout, rounded


def rect(w, h):
    return [(0, 0), (w, 0), (w, h), (0, h)]


def test_layout_areas_are_proportional():
    items = [("a", 50), ("b", 25), ("c", 15), ("d", 7), ("e", 3)]
    polys = layout(items, rect(400, 300))
    assert set(polys) == {k for k, _ in items}
    total = 400 * 300
    for k, v in items:
        assert area(polys[k]) == pytest.approx(total * v / 100, rel=1e-3)


def test_layout_is_stable_for_same_seed():
    items = [("a", 3), ("b", 2), ("c", 1)]
    assert layout(items, rect(100, 100), seed=1) == layout(items, rect(100, 100), seed=1)


def test_inset_shrinks_and_vanishes():
    p = inset(rect(100, 50), 5)
    assert area(p) == pytest.approx(90 * 40)
    assert inset(rect(8, 8), 5) is None


def test_rounded_keeps_shape_inside():
    pts = rounded(rect(100, 100), 20)
    assert all(-1e-9 <= x <= 100 and -1e-9 <= y <= 100 for x, y in pts)
    assert area(pts) < 100 * 100
