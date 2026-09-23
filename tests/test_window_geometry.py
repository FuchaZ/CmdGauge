"""窗口几何相关的纯函数单测 (不创建窗口, 不碰 GUI).

覆盖: 保存的几何在显示器变化后的夹紧/丢弃, 以及边缘缩放的物理像素下限换算
(本机实测 125% 缩放下 6px 热区难命中、min_size 逻辑像素与物理像素混用会夹不住)。
"""
from app.main import (
    WINDOW_MIN_SIZE,
    _clamp_window_geometry,
    _compute_resized_rect,
)

AREAS = [(0, 0, 2560, 1380)]          # 主屏工作区 (物理像素, 2560x1440 @125%)
SECOND = [(-2560, -135, -427, 1005)]  # 左侧副屏
MIN_125 = (1250, 850)                 # 1000x680 逻辑 × 1.25


def test_clamp_keeps_in_bounds_unchanged():
    geo = {"left": 300, "top": 200, "width": 1400, "height": 900}
    assert _clamp_window_geometry(geo, AREAS, MIN_125) == (300, 200, 1400, 900)


def test_clamp_pulls_window_back_from_edges():
    geo = {"left": 2400, "top": 1300, "width": 1400, "height": 900}
    left, top, width, height = _clamp_window_geometry(geo, AREAS, MIN_125)
    assert (left, top) == (1160, 480)          # 右/下边贴住工作区
    assert (width, height) == (1400, 900)


def test_clamp_rejects_geometry_off_all_monitors():
    geo = {"left": 90000, "top": 90000, "width": 1200, "height": 900}
    assert _clamp_window_geometry(geo, AREAS, MIN_125) is None


def test_clamp_enforces_min_size():
    geo = {"left": 10, "top": 10, "width": 200, "height": 100}
    assert _clamp_window_geometry(geo, AREAS, MIN_125) == (10, 10, 1250, 850)


def test_clamp_caps_size_to_work_area():
    geo = {"left": 0, "top": 0, "width": 9999, "height": 9999}
    assert _clamp_window_geometry(geo, AREAS, MIN_125) == (0, 0, 2560, 1380)


def test_clamp_picks_monitor_with_largest_overlap():
    """横跨两块屏时按重叠面积选显示器, 不把窗口硬拉回主屏。"""
    areas = AREAS + [(-1600, 0, -100, 1000)]
    geo = {"left": -1200, "top": 100, "width": 1500, "height": 900}
    left, top, width, height = _clamp_window_geometry(geo, areas, MIN_125)
    assert left < 0                                 # 留在副屏 (负坐标)
    assert -1600 <= left and left + width <= -100
    assert 0 <= top and top + height <= 1000


def test_clamp_handles_broken_payload():
    for bad in ({}, {"left": "x", "top": 0, "width": 800, "height": 600},
                {"left": 0, "top": 0, "width": 0, "height": 600}, None):
        assert _clamp_window_geometry(bad, AREAS, MIN_125) is None
    assert _clamp_window_geometry({"left": 0, "top": 0, "width": 800, "height": 600}, [], MIN_125) is None


def test_resized_rect_uses_passed_min_size():
    """min_size 必须按坐标系传入: 125% 缩放下物理下限是 1250x850。"""
    # 从右边缘往左拖 -5000: 宽度被夹在 min_w
    left, top, right, bottom = _compute_resized_rect(0, 0, 2000, 1000, "e", -5000, 0, MIN_125)
    assert (right - left, bottom - top) == (1250, 1000)
    # 从下边缘往上拖: 高度被夹在 min_h
    left, top, right, bottom = _compute_resized_rect(0, 0, 2000, 1000, "s", 0, -5000, MIN_125)
    assert (right - left, bottom - top) == (2000, 850)


def test_resized_rect_default_min_matches_constant():
    left, top, right, bottom = _compute_resized_rect(0, 0, 2000, 1000, "e", -5000, 0)
    assert (right - left) == WINDOW_MIN_SIZE[0]


def test_resized_rect_grows_and_keeps_opposite_edge():
    left, top, right, bottom = _compute_resized_rect(100, 100, 1100, 800, "se", 200, 150, (900, 700))
    assert (left, top) == (100, 100)
    assert (right, bottom) == (1300, 950)
