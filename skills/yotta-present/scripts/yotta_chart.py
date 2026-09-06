#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""yotta_chart.py — 元呈（yotta-present）本地零依赖 SVG 渲染内核 + CLI。

纯 Python 3.8+ 标准库生成 SVG 图表（bar/line/pie/radar/scatter/histogram/
funnel/waterfall/word_cloud/sankey/spreadsheet/treemap，共 12 种）。
数据不出本机：只在本机拼 SVG 字符串并写文件，不联网、不调用远程渲染服务。

CLI：
    python scripts/yotta_chart.py <chart> [--title ...] [--labels a,b,c] \
        [--data 1,2,3] [--out out.svg] [--width 800] [--height 500] [--palette ...] [--theme light|dark]

MCP：图表形态经 yotta-present（scripts/yotta_present_mcp.py）的 present_result 暴露（chart_data），
复用本渲染内核。
"""

import base64
import json
import math
import os
import re
import sys
import tempfile
import time
from xml.sax.saxutils import escape as _xml_escape

VERSION = "0.5.0"
TOOL_NAME = "yotta-present"
CN_NAME = "元呈"

_HERE = os.path.dirname(os.path.abspath(__file__))

# 支持图表清单（MCP tools / CLI 共用）
CHART_TYPES = [
    "bar", "line", "pie", "radar", "scatter", "histogram",
    "funnel", "waterfall", "word_cloud", "sankey", "spreadsheet", "treemap",
]

# ---------------------------------------------------------------------------
# 主题 token（S7-M2 色板 token 化）：一处定义、全通道消费。
# 权威源 = references/theme.json（声明式、可热更新、社区可贡献）；
# 缺失/损坏自动回退内置（单文件也能跑）。渲染一律经 _t() 取色，
# 禁止在渲染函数里散落硬编码色值（色板/语义色仅在 token 定义处出现）。
# 主题：light / dark；语义色名与 yotta_present 的 GRADE_META 对齐
# （success/warn/danger/info/neutral），不另造色名。
# ---------------------------------------------------------------------------

THEMES = ["light", "dark"]

_THEME_BUILTIN = {
    "meta": {"schema": 1, "brand_primary": "#2F6FED", "default_theme": "light"},
    "themes": {
        "light": {
            "bg": "#ffffff", "surface": "#F8F9FA", "surface_2": "#F1F3F5",
            "border": "#DEE2E6", "text": "#212529", "label": "#495057",
            "muted": "#6C757D", "grid": "#EDF2FF", "axis": "#ADB5BD",
            "edge": "#ffffff", "on_chip": "#ffffff",
        },
        "dark": {
            "bg": "#1E2329", "surface": "#262C33", "surface_2": "#2C333B",
            "border": "#39414A", "text": "#EDF1F5", "label": "#C9D1D9",
            "muted": "#9AA4AF", "grid": "#2A3138", "axis": "#4A525C",
            "edge": "#ffffff", "on_chip": "#ffffff",
        },
    },
    "semantic": {
        "success": {"light": {"bg": "#1A7F37", "fg": "#ffffff", "text": "#1A7F37"},
                    "dark": {"bg": "#1A7F37", "fg": "#ffffff", "text": "#69DB7C"}},
        "warn": {"light": {"bg": "#C2410C", "fg": "#ffffff", "text": "#B23A0A"},
                 "dark": {"bg": "#C2410C", "fg": "#ffffff", "text": "#FFA94D"}},
        "danger": {"light": {"bg": "#C92A2A", "fg": "#ffffff", "text": "#C92A2A"},
                   "dark": {"bg": "#C92A2A", "fg": "#ffffff", "text": "#FF8787"}},
        "info": {"light": {"bg": "#1971C2", "fg": "#ffffff", "text": "#1971C2"},
                 "dark": {"bg": "#1971C2", "fg": "#ffffff", "text": "#74C0FC"}},
        "neutral": {"light": {"bg": "#495057", "fg": "#ffffff", "text": "#495057"},
                    "dark": {"bg": "#495057", "fg": "#ffffff", "text": "#ADB5BD"}},
    },
    "form_accent": {
        "conclusion": "#2F6FED", "table": "#495057", "checklist": "#2B8A3E",
        "prose": "#2F6FED", "metrics": "#2F6FED", "qa": "#1971C2",
        "report": "#2F6FED", "chart": "#2F6FED",
    },
    "chart_palettes": {
        "light": {
            "default": ["#2F6FED", "#22B8A6", "#F59F00", "#E64980", "#7048E8",
                        "#868E96", "#38D9A9", "#FAB005", "#4E9BFF", "#E8590C"],
            "ocean": ["#1864AB", "#339AF0", "#74C0FC", "#22B8A6", "#0CA678",
                      "#F59F00", "#E8590C", "#7048E8"],
            "forest": ["#2B8A3E", "#51CF66", "#8CE99A", "#0CA678", "#22B8A6",
                       "#FAB005", "#E8590C", "#5F3DC4"],
            "mono": ["#212529", "#495057", "#868E96", "#ADB5BD", "#CED4DA",
                     "#212529", "#495057", "#868E96"],
            "warm": ["#E8590C", "#F59F00", "#FAB005", "#FFD43B", "#E64980",
                     "#C2255C", "#A61E4D", "#862E9C"],
        },
        "dark": {
            "default": ["#5C9CFF", "#3DD6C0", "#FFC24D", "#FF7BA9", "#9D7BFF",
                        "#A8B3BF", "#4ED6A8", "#FFD166", "#74C0FC", "#FF8A5C"],
            "ocean": ["#4C9AFF", "#74C0FC", "#A5D8FF", "#3DD6C0", "#63E6BE",
                      "#FFC24D", "#FF8A5C", "#9D7BFF"],
            "forest": ["#63E6BE", "#8CE99A", "#B2F2BB", "#3DD6C0", "#4ED6A8",
                       "#FFD166", "#FF8A5C", "#B197FC"],
            "mono": ["#DEE2E6", "#C9D1D9", "#A8B3BF", "#8B98A5", "#6C7A87",
                     "#DEE2E6", "#C9D1D9", "#A8B3BF"],
            "warm": ["#FF8A5C", "#FFC24D", "#FFD166", "#FFE082", "#FF7BA9",
                     "#F06595", "#E64980", "#CC5DE8"],
        },
    },
}


def _load_theme_file():
    """从 references/theme.json 加载主题配置；缺失/损坏回退内置。"""
    ref = os.path.join(_HERE, "..", "references", "theme.json")
    try:
        with open(ref, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("themes") and data.get("chart_palettes"):
            return data
    except Exception:  # noqa: BLE001
        pass
    return _THEME_BUILTIN


THEME = _load_theme_file()


def _theme_colors(theme):
    t = "dark" if str(theme or "").strip().lower() == "dark" else "light"
    colors = (THEME.get("themes") or {}).get(t)
    return colors if colors else (_THEME_BUILTIN["themes"][t])


def _palette_table(theme):
    """某主题的序列色板表（theme.json 优先，内置兜底）。"""
    dark = str(theme or "").strip().lower() == "dark"
    key = "dark" if dark else "light"
    base = dict(_THEME_BUILTIN["chart_palettes"][key])
    ext = ((THEME.get("chart_palettes") or {}).get(key)) or {}
    base.update(ext or {})
    return base


# 序列色板（light / dark 各一套；render 按活动主题选用）
PALETTES = _palette_table("light")
DARK_PALETTES = _palette_table("dark")

# 活动主题（render() 单线程内设置，渲染器统一经 _t() 取色；未设置 = light）
_ACTIVE_COLORS = _theme_colors("light")


def _use_theme(theme):
    global _ACTIVE_COLORS
    _ACTIVE_COLORS = _theme_colors(theme)


def _reset_theme():
    global _ACTIVE_COLORS
    _ACTIVE_COLORS = _theme_colors("light")


def _t(key):
    """按活动主题取色（缺省回退 light，绝不因缺 token 崩渲染）。"""
    v = _ACTIVE_COLORS.get(key)
    if v is None:
        v = _theme_colors("light").get(key)
    return v or "#000000"


# 模板占位符 → 角色 token（_apply_theme 统一替换；用户内容经 XML 转义不会误命中）
_T_MARKERS = {
    "&YTBG;": "bg", "&YTTEXT;": "text", "&YTLABEL;": "label",
    "&YTMUTED;": "muted", "&YTGRID;": "grid", "&YTAXIS;": "axis",
    "&YTEDGE;": "edge", "&YTCHIP;": "on_chip",
    "&YTSURFACE;": "surface", "&YTSURFACE2;": "surface_2", "&YTBORDER;": "border",
}


def _apply_theme(body):
    """把模板占位符替换为活动主题颜色（一处映射，全通道消费）。"""
    for marker, key in _T_MARKERS.items():
        if marker in body:
            body = body.replace(marker, _t(key))
    return body


def check_contrast(threshold=4.5):
    """WCAG 对比度自查（正文/背景配对 >= threshold）。返回 (ok, report)。"""
    def _lum(hexc):
        h = str(hexc or "#000000").lstrip("#")
        if len(h) != 6:
            h = "000000"
        r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
        def f(c):
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)

    def _ratio(a, b):
        la, lb = _lum(a), _lum(b)
        hi, lo = max(la, lb), min(la, lb)
        return (hi + 0.05) / (lo + 0.05)

    pairs = []
    themes = THEME.get("themes") or {}
    for tname, tc in themes.items():
        if not isinstance(tc, dict):
            continue
        pairs.append((tname, "text/bg", tc.get("text"), tc.get("bg")))
        pairs.append((tname, "label/bg", tc.get("label"), tc.get("bg")))
        pairs.append((tname, "muted/bg", tc.get("muted"), tc.get("bg")))
        pairs.append((tname, "label/surface", tc.get("label"), tc.get("surface")))
        pairs.append((tname, "label/surface_2", tc.get("label"), tc.get("surface_2")))
        pairs.append((tname, "text/surface_2", tc.get("text"), tc.get("surface_2")))
    semantic = THEME.get("semantic") or {}
    for gname, g in semantic.items():
        for tname in ("light", "dark"):
            c = g.get(tname)
            if isinstance(c, dict) and c.get("fg") and c.get("bg"):
                pairs.append((tname, "semantic:%s chip" % gname, c.get("fg"), c.get("bg")))
    report = []
    ok = True
    for tname, label, fg, bg in pairs:
        if not fg or not bg:
            report.append("  [skip] %s %s 缺色" % (tname, label))
            continue
        ratio = _ratio(fg, bg)
        status = "ok" if ratio >= threshold else "FAIL"
        if ratio < threshold:
            ok = False
        report.append("  [%s] %-26s %-7s on %-7s = %.2f:1 (>= %.1f)" % (status, "%s %s" % (tname, label), fg, bg, ratio, threshold))
    return ok, "\n".join(report)

FONT = "system-ui, -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif"


def _e(text):
    """XML 转义（防 SVG 注入：script / 事件属性等一律转义）。"""
    if text is None:
        return ""
    return _xml_escape(str(text), {'"': "&quot;", "'": "&apos;"})


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _as_list(v):
    """把入参归一化为列表；字符串按逗号拆分。"""
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return list(v)
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return []
        return [x.strip() for x in s.split(",")]
    return [v]


def _nice_ticks(lo, hi, n=5):
    """生成 [lo,hi] 区间 n 个左右的好看刻度（1/2/5×10^k）。"""
    if hi < lo:
        lo, hi = hi, lo
    if lo == hi:
        lo -= 1.0
        hi += 1.0
    span = hi - lo
    step_raw = span / max(1, n)
    mag = 10 ** math.floor(math.log10(step_raw))
    for m in (1, 2, 5, 10):
        step = m * mag
        if step >= step_raw:
            break
    start = math.floor(lo / step) * step
    ticks = []
    v = start
    while v <= hi + 1e-9:
        ticks.append(round(v, 10))
        v += step
        if len(ticks) > 50:
            break
    # 保证覆盖 hi（数据最大值不越界）
    while ticks[-1] < hi - 1e-9:
        ticks.append(round(ticks[-1] + step, 10))
        if len(ticks) > 60:
            break
    return ticks


def _fmt_num(v):
    """数值格式化：整数不带小数；大数用 K/M。"""
    v = _num(v)
    if v == int(v) and abs(v) < 1e15:
        iv = int(v)
        if abs(iv) >= 1e9:
            return "%.1fB" % (iv / 1e9)
        if abs(iv) >= 1e6:
            return "%.1fM" % (iv / 1e6)
        if abs(iv) >= 1e4:
            return "%.1fK" % (iv / 1e3)
        return str(iv)
    if abs(v) >= 100:
        return "%.0f" % v
    return "%.2f" % v if v != int(v) else str(int(v))


def _palette(name):
    p = PALETTES.get(name or "default")
    return p if p else PALETTES["default"]


def _palette_for(theme, name):
    """按主题取序列色板（dark 用暗色变体；缺名回退 light/内置 default）。"""
    name = name or "default"
    if str(theme or "").strip().lower() == "dark":
        return DARK_PALETTES.get(name) or PALETTES.get(name) or PALETTES["default"]
    return PALETTES.get(name) or PALETTES["default"]


def _svg_wrap(body, width, height, title=None):
    """包一层 SVG 骨架（含标题），返回完整 SVG 字符串。"""
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
        'viewBox="0 0 %d %d" font-family="%s" role="img">' % (width, height, width, height, _e(FONT)),
        '<rect x="0" y="0" width="%d" height="%d" fill="&YTBG;"/>' % (width, height),
    ]
    if title:
        parts.append(
            '<text x="%d" y="30" text-anchor="middle" font-size="18" font-weight="600" '
            'fill="&YTTEXT;">%s</text>' % (width / 2, _e(title)))
    parts.append(body)
    parts.append("</svg>")
    return _apply_theme("\n".join(parts))


def _legend(entries, x, y, font_size=12, box=14, gap=6):
    """绘制图例：entries=[(label, color)]，返回 SVG 片段。"""
    if not entries:
        return ""
    parts = []
    cx = x
    cy = y
    max_w = 0
    for label, color in entries:
        tw = len(label) * font_size + box + gap + 10
        if cx + tw > 10000:  # 防止极端输入
            break
        parts.append('<rect x="%d" y="%d" width="%d" height="%d" rx="3" fill="%s"/>'
                     % (cx, cy, box, box, _e(color)))
        parts.append('<text x="%d" y="%d" font-size="%d" fill="&YTLABEL;">%s</text>'
                     % (cx + box + gap, cy + box - 3, font_size, _e(label)))
        max_w = max(max_w, tw)
        cx += tw
    return _apply_theme("\n".join(parts))


def _text_wrapped(s, max_len=24):
    s = str(s)
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


# ---------------------------------------------------------------------------
# 笛卡尔坐标系基础（bar / line / scatter / histogram 共用）
# ---------------------------------------------------------------------------

class Cart:
    """笛卡尔绘图区：margin + 坐标映射 + y 轴刻度/网格。"""

    def __init__(self, width, height, y_lo=0, y_hi=1, top=50, bottom=52,
                 left=64, right=24):
        self.width = width
        self.height = height
        self.top = top
        self.bottom = bottom
        self.left = left
        self.right = right
        self.plot_w = max(50, width - left - right)
        self.plot_h = max(50, height - top - bottom)
        self.x0 = left
        self.y0 = top
        self.y_ticks = _nice_ticks(y_lo, y_hi, 5)
        self.y_min = self.y_ticks[0]
        self.y_max = self.y_ticks[-1]

    def x(self, i, n):
        if n <= 1:
            return self.x0 + self.plot_w / 2.0
        return self.x0 + self.plot_w * (i / float(n - 1))

    def y(self, v):
        span = (self.y_max - self.y_min) or 1.0
        return self.y0 + self.plot_h * (1.0 - (v - self.y_min) / span)

    def grid(self):
        parts = []
        for t in self.y_ticks:
            yy = self.y(t)
            parts.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="&YTGRID;" stroke-width="1"/>'
                         % (self.x0, yy, self.x0 + self.plot_w, yy))
            parts.append('<text x="%d" y="%.1f" font-size="11" fill="&YTMUTED;" text-anchor="end">%s</text>'
                         % (self.x0 - 8, yy + 4, _e(_fmt_num(t))))
        return _apply_theme("\n".join(parts))

    def axes(self):
        return ('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="&YTAXIS;" stroke-width="1"/>'
                % (self.x0, self.y(0), self.x0 + self.plot_w, self.y(0)))


def _bar(labels, data, width, height, title, palette, stacked=False):
    """柱状图：data=[...] 单序列，或 data=[[...],[...]] 多序列分组。"""
    series = []
    if data and isinstance(data[0], (list, tuple)):
        series = [list(map(_num, d)) for d in data]
    else:
        series = [list(map(_num, data))]
    n = max(len(labels), max((len(s) for s in series), default=0))
    all_vals = [v for s in series for v in s]
    hi = max(all_vals, default=1)
    lo = 0
    cart = Cart(width, height, y_lo=lo, y_hi=hi if hi > 0 else 1)
    parts = [cart.grid(), cart.axes()]
    group_w = cart.plot_w / max(1, n)
    bar_w = group_w * 0.62 / max(1, len(series))
    if stacked:
        base = [0.0] * n
        for si, s in enumerate(series):
            color = palette[si % len(palette)]
            for i in range(n):
                if i >= len(s):
                    continue
                v = s[i]
                x0 = cart.x0 + group_w * i + group_w * 0.19
                y_top = cart.y(v + base[i])
                y_bot = cart.y(base[i])
                if v != 0:
                    parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>'
                                 % (x0, y_top, bar_w, max(1.0, y_bot - y_top), _e(color)))
                base[i] += v
    else:
        for si, s in enumerate(series):
            color = palette[si % len(palette)]
            for i in range(n):
                if i >= len(s):
                    continue
                v = s[i]
                x0 = cart.x0 + group_w * i + group_w * 0.19 + bar_w * si
                y_top = cart.y(max(0, v))
                y_bot = cart.y(0)
                if v != 0:
                    parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>'
                                 % (x0, y_top, bar_w, max(1.0, y_bot - y_top), _e(color)))
                parts.append('<text x="%.1f" y="%.1f" font-size="10" fill="&YTLABEL;" text-anchor="middle">%s</text>'
                             % (x0 + bar_w / 2, y_top - 4, _e(_fmt_num(v))))
    # x 轴标签
    step = 1
    while n > 12 and n % step != 0:
        step += 1
    for i in range(0, n, step):
        label = _text_wrapped(labels[i], 12) if i < len(labels) else ""
        cx = cart.x0 + group_w * i + group_w / 2
        parts.append('<text x="%.1f" y="%d" font-size="11" fill="&YTLABEL;" text-anchor="middle">%s</text>'
                     % (cx, height - 18, _e(label)))
    # 图例（多序列）
    if len(series) > 1:
        parts.append(_legend([("序列 %d" % (i + 1), palette[i % len(palette)])
                              for i in range(len(series))], cart.x0, 44))
    return _svg_wrap("\n".join(parts), width, height, title)


def _line(labels, data, width, height, title, palette, fill=False):
    """折线图：data=[...] 或 data=[[...],[...]] 多序列。"""
    series = []
    if data and isinstance(data[0], (list, tuple)):
        series = [list(map(_num, d)) for d in data]
    else:
        series = [list(map(_num, data))]
    n = max(len(labels), max((len(s) for s in series), default=0))
    all_vals = [v for s in series for v in s]
    lo = min(all_vals, default=0)
    hi = max(all_vals, default=1)
    if lo >= hi:
        lo, hi = 0, 1
    pad = (hi - lo) * 0.08
    cart = Cart(width, height, y_lo=lo - pad, y_hi=hi + pad)
    parts = [cart.grid(), cart.axes()]
    for si, s in enumerate(series):
        color = palette[si % len(palette)]
        pts = []
        for i in range(n):
            if i >= len(s):
                continue
            pts.append((cart.x(i, n), cart.y(s[i])))
        if len(pts) >= 2:
            poly = " ".join("%.1f,%.1f" % p for p in pts)
            if fill:
                area = poly + " %.1f,%.1f %.1f,%.1f" % (pts[-1][0], cart.y(0), pts[0][0], cart.y(0))
                parts.append('<polygon points="%s" fill="%s" fill-opacity="0.12" stroke="none"/>'
                             % (area, _e(color)))
            parts.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>'
                         % (poly, _e(color)))
        for x, y in pts:
            parts.append('<circle cx="%.1f" cy="%.1f" r="3.5" fill="&YTBG;" stroke="%s" stroke-width="2"/>'
                         % (x, y, _e(color)))
    step = 1
    while n > 12 and n % step != 0:
        step += 1
    for i in range(0, n, step):
        label = _text_wrapped(labels[i], 12) if i < len(labels) else ""
        cx = cart.x(i, n)
        parts.append('<text x="%.1f" y="%d" font-size="11" fill="&YTLABEL;" text-anchor="middle">%s</text>'
                     % (cx, height - 18, _e(label)))
    if len(series) > 1:
        parts.append(_legend([("序列 %d" % (i + 1), palette[i % len(palette)])
                              for i in range(len(series))], cart.x0, 44))
    return _svg_wrap("\n".join(parts), width, height, title)

# ---------------------------------------------------------------------------
# pie / radar / scatter / histogram
# ---------------------------------------------------------------------------

def _pie(labels, data, width, height, title, palette, show_pct=True):
    """饼图：labels + data。"""
    vals = [max(0, _num(v)) for v in _as_list(data)]
    labels = _as_list(labels)
    total = sum(vals)
    cx = width * 0.42
    cy = height * 0.52
    r = min(width, height) * 0.30
    parts = []
    if total <= 0:
        parts.append('<text x="%.1f" y="%.1f" font-size="14" fill="&YTMUTED;" text-anchor="middle">无数据</text>'
                     % (cx, cy))
        return _svg_wrap("\n".join(parts), width, height, title)
    angle = -90.0
    for i, v in enumerate(vals):
        if v <= 0:
            continue
        color = palette[i % len(palette)]
        sweep = 360.0 * v / total
        a1 = angle
        a2 = angle + sweep
        rad1 = math.radians(a1)
        rad2 = math.radians(a2)
        x1 = cx + r * math.cos(rad1)
        y1 = cy + r * math.sin(rad1)
        x2 = cx + r * math.cos(rad2)
        y2 = cy + r * math.sin(rad2)
        large = 1 if sweep > 180 else 0
        d = ("M %.1f %.1f L %.1f %.1f A %.1f %.1f 0 %d 1 %.1f %.1f Z"
             % (cx, cy, x1, y1, r, r, large, x2, y2))
        parts.append('<path d="%s" fill="%s" stroke="&YTEDGE;" stroke-width="1.5"/>' % (d, _e(color)))
        if show_pct and sweep >= 8:
            mid = math.radians((a1 + a2) / 2)
            lx = cx + r * 0.62 * math.cos(mid)
            ly = cy + r * 0.62 * math.sin(mid)
            pct = "%.0f%%" % (100.0 * v / total)
            parts.append('<text x="%.1f" y="%.1f" font-size="11" fill="&YTCHIP;" text-anchor="middle">%s</text>'
                         % (lx, ly + 4, _e(pct)))
        angle = a2
    # 图例（右侧）
    lx = width * 0.78
    ly = height * 0.5 - (min(8, len(labels)) * 20) / 2
    for i in range(min(8, len(labels))):
        color = palette[i % len(palette)]
        parts.append('<rect x="%.1f" y="%.1f" width="12" height="12" rx="2" fill="%s"/>'
                     % (lx, ly + i * 20, _e(color)))
        pct = "%.0f%%" % (100.0 * vals[i] / total) if i < len(vals) and total > 0 else ""
        parts.append('<text x="%.1f" y="%.1f" font-size="11" fill="&YTLABEL;">%s  %s</text>'
                     % (lx + 18, ly + i * 20 + 11, _e(_text_wrapped(labels[i], 10)), _e(pct)))
    return _svg_wrap("\n".join(parts), width, height, title)


def _radar(labels, data, width, height, title, palette, fill=True):
    """雷达图：labels=维度，data=[...] 或 data=[[...],[...]] 多序列。"""
    dims = _as_list(labels)
    series = []
    if data and isinstance(data[0], (list, tuple)):
        series = [list(map(_num, d)) for d in data]
    else:
        series = [list(map(_num, data))]
    k = max(len(dims), max((len(s) for s in series), default=0))
    if k < 3:
        return _svg_wrap('<text x="%d" y="%d" font-size="14" fill="&YTMUTED;" text-anchor="middle">雷达图至少需要 3 个维度</text>'
                         % (width / 2, height / 2), width, height, title)
    maxv = max([v for s in series for v in s] + [1.0])
    maxv = max(1.0, maxv)
    cx = width * 0.42
    cy = height * 0.54
    r = min(width, height) * 0.30
    parts = []
    # 网格（4 层环 + 轴线）
    for ring in (0.25, 0.5, 0.75, 1.0):
        pts = []
        for i in range(k):
            a = math.radians(-90 + 360.0 * i / k)
            pts.append("%.1f,%.1f" % (cx + r * ring * math.cos(a), cy + r * ring * math.sin(a)))
        parts.append('<polygon points="%s" fill="none" stroke="&YTGRID;" stroke-width="1"/>' % " ".join(pts))
    for i in range(k):
        a = math.radians(-90 + 360.0 * i / k)
        parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="&YTGRID;" stroke-width="1"/>'
                     % (cx, cy, cx + r * math.cos(a), cy + r * math.sin(a)))
    for si, s in enumerate(series):
        color = palette[si % len(palette)]
        pts = []
        for i in range(k):
            v = s[i] if i < len(s) else 0
            a = math.radians(-90 + 360.0 * i / k)
            rr = r * (v / maxv)
            pts.append("%.1f,%.1f" % (cx + rr * math.cos(a), cy + rr * math.sin(a)))
        poly = " ".join(pts)
        if fill:
            parts.append('<polygon points="%s" fill="%s" fill-opacity="0.18"/>' % (poly, _e(color)))
        parts.append('<polygon points="%s" fill="none" stroke="%s" stroke-width="2"/>' % (poly, _e(color)))
        for p in pts:
            px, py = p.split(",")
            parts.append('<circle cx="%s" cy="%s" r="3" fill="%s"/>' % (px, py, _e(color)))
    # 维度标签
    for i in range(k):
        a = math.radians(-90 + 360.0 * i / k)
        lx = cx + (r + 24) * math.cos(a)
        ly = cy + (r + 24) * math.sin(a)
        anchor = "middle"
        if abs(math.cos(a)) > 0.3:
            anchor = "start" if math.cos(a) > 0 else "end"
        parts.append('<text x="%.1f" y="%.1f" font-size="11" fill="&YTLABEL;" text-anchor="%s">%s</text>'
                     % (lx, ly + 4, anchor, _e(_text_wrapped(dims[i], 10))))
    if len(series) > 1:
        parts.append(_legend([("序列 %d" % (i + 1), palette[i % len(palette)])
                              for i in range(len(series))], width * 0.14, height - 30))
    return _svg_wrap("\n".join(parts), width, height, title)


def _scatter(data, width, height, title, palette, labels=None):
    """散点图：data=[[x,y],...] 或 data=[[[x,y],...], ...] 多组。"""
    groups = []
    if data and isinstance(data[0], (list, tuple)) and data[0] and isinstance(data[0][0], (list, tuple)):
        for g in data:
            groups.append([( _num(p[0]), _num(p[1])) for p in g if len(p) >= 2])
    else:
        groups.append([(_num(p[0]), _num(p[1])) for p in data if isinstance(p, (list, tuple)) and len(p) >= 2])
    all_x = [p[0] for g in groups for p in g]
    all_y = [p[1] for g in groups for p in g]
    if not all_x:
        return _svg_wrap('<text x="%d" y="%d" font-size="14" fill="&YTMUTED;" text-anchor="middle">无数据</text>'
                         % (width / 2, height / 2), width, height, title)
    x_lo, x_hi = min(all_x), max(all_x)
    y_lo, y_hi = min(all_y), max(all_y)
    if x_lo == x_hi:
        x_lo, x_hi = x_lo - 1, x_hi + 1
    if y_lo == y_hi:
        y_lo, y_hi = y_lo - 1, y_hi + 1
    pad_x = (x_hi - x_lo) * 0.08
    pad_y = (y_hi - y_lo) * 0.08
    cart = Cart(width, height, y_lo=y_lo - pad_y, y_hi=y_hi + pad_y)
    # x 轴刻度（自定义）
    x_ticks = _nice_ticks(x_lo - pad_x, x_hi + pad_x, 5)
    x_lo2, x_hi2 = x_ticks[0], x_ticks[-1]
    def _x(v):
        span = (x_hi2 - x_lo2) or 1.0
        return cart.x0 + cart.plot_w * (v - x_lo2) / span
    parts = [cart.grid()]
    for t in x_ticks:
        xx = _x(t)
        parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="&YTGRID;" stroke-width="1"/>'
                     % (xx, cart.y0, xx, cart.y0 + cart.plot_h))
        parts.append('<text x="%.1f" y="%d" font-size="11" fill="&YTMUTED;" text-anchor="middle">%s</text>'
                     % (xx, height - 20, _e(_fmt_num(t))))
    parts.append(cart.axes())
    for gi, g in enumerate(groups):
        color = palette[gi % len(palette)]
        for x, y in g:
            parts.append('<circle cx="%.1f" cy="%.1f" r="4.5" fill="%s" fill-opacity="0.75"/>'
                         % (_x(x), cart.y(y), _e(color)))
    if len(groups) > 1:
        parts.append(_legend([("组 %d" % (i + 1), palette[i % len(palette)])
                              for i in range(len(groups))], cart.x0, 44))
    return _svg_wrap("\n".join(parts), width, height, title)


def _histogram(data, width, height, title, palette, bins=None):
    """直方图：data=原始数值列表；bins 可选（默认 sqrt(n)）。"""
    vals = [_num(v) for v in _as_list(data)]
    vals = [v for v in vals if not math.isnan(v)]
    if not vals:
        return _svg_wrap('<text x="%d" y="%d" font-size="14" fill="&YTMUTED;" text-anchor="middle">无数据</text>'
                         % (width / 2, height / 2), width, height, title)
    if bins is None:
        bins = max(5, min(20, int(math.sqrt(len(vals))) + 1))
    else:
        bins = max(2, int(_num(bins, 5)))
    lo, hi = min(vals), max(vals)
    if lo == hi:
        lo, hi = lo - 1, hi + 1
    step = (hi - lo) / bins
    counts = [0] * bins
    for v in vals:
        idx = min(bins - 1, int((v - lo) / step)) if step > 0 else 0
        counts[idx] += 1
    edges = [lo + i * step for i in range(bins + 1)]
    cart = Cart(width, height, y_lo=0, y_hi=max(counts, default=1) * 1.1)
    parts = [cart.grid(), cart.axes()]
    color = palette[0]
    bw = cart.plot_w / bins * 0.82
    for i, c in enumerate(counts):
        x0 = cart.x0 + cart.plot_w * i / bins + cart.plot_w / bins * 0.09
        y_top = cart.y(c)
        y_bot = cart.y(0)
        parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>'
                     % (x0, y_top, bw, max(1.0, y_bot - y_top), _e(color)))
        if i % max(1, bins // 8) == 0 or i == bins - 1:
            parts.append('<text x="%.1f" y="%d" font-size="10" fill="&YTMUTED;" text-anchor="middle">%s</text>'
                         % (x0 + bw / 2, height - 20, _e(_fmt_num(edges[i]))))
    return _svg_wrap("\n".join(parts), width, height, title)

# ---------------------------------------------------------------------------
# funnel / waterfall / word_cloud / sankey / spreadsheet / treemap
# ---------------------------------------------------------------------------

def _funnel(labels, data, width, height, title, palette):
    """漏斗图：labels=阶段，data=阶段值。"""
    labels = _as_list(labels)
    vals = [max(0, _num(v)) for v in _as_list(data)]
    n = min(len(labels), len(vals))
    if n == 0:
        return _svg_wrap('<text x="%d" y="%d" font-size="14" fill="&YTMUTED;" text-anchor="middle">无数据</text>'
                         % (width / 2, height / 2), width, height, title)
    maxv = max(vals, default=1) or 1
    top = 54
    bottom = height - 34
    row_h = (bottom - top) / n
    parts = []
    cx = width / 2
    for i in range(n):
        w_top = width * 0.72 * (vals[i] / maxv)
        w_bot = width * 0.72 * ((vals[i + 1] if i + 1 < n else vals[i]) / maxv)
        y0 = top + i * row_h
        y1 = y0 + row_h
        xl0 = cx - w_top / 2
        xr0 = cx + w_top / 2
        xl1 = cx - w_bot / 2
        xr1 = cx + w_bot / 2
        color = palette[i % len(palette)]
        parts.append('<polygon points="%.1f,%.1f %.1f,%.1f %.1f,%.1f %.1f,%.1f" fill="%s" fill-opacity="%s" stroke="&YTEDGE;" stroke-width="1.5"/>'
                     % (xl0, y0, xr0, y0, xr1, y1, xl1, y1, _e(color),
                        "%.2f" % (0.9 - 0.12 * (i % 5))))
        pct = "%.0f%%" % (100.0 * vals[i] / maxv)
        parts.append('<text x="%.1f" y="%.1f" font-size="12" fill="&YTCHIP;" text-anchor="middle">%s  %s</text>'
                     % (cx, (y0 + y1) / 2 + 4, _e(_text_wrapped(labels[i], 16)), _e(pct)))
    return _svg_wrap("\n".join(parts), width, height, title)


def _waterfall(labels, data, width, height, title, palette):
    """瀑布图：data=[起始值, 增减..., 累计值]；正值=增加色、负值=减少色。"""
    labels = _as_list(labels)
    vals = [_num(v) for v in _as_list(data)]
    n = len(vals)
    if n == 0:
        return _svg_wrap('<text x="%d" y="%d" font-size="14" fill="&YTMUTED;" text-anchor="middle">无数据</text>'
                         % (width / 2, height / 2), width, height, title)
    base = [0.0] * n
    running = 0.0
    for i in range(n):
        v = vals[i]
        if i == 0:
            base[i] = 0.0
            running = v
        elif i == n - 1:
            base[i] = 0.0
            running = running + v
        else:
            base[i] = running
            running = running + v
    all_vals = [base[i] for i in range(n)] + [base[i] + vals[i] for i in range(n)]
    lo = min(all_vals + [0])
    hi = max(all_vals + [1])
    pad = (hi - lo) * 0.08
    cart = Cart(width, height, y_lo=lo - pad, y_hi=hi + pad)
    parts = [cart.grid(), cart.axes()]
    group_w = cart.plot_w / max(1, n)
    bar_w = group_w * 0.52
    for i in range(n):
        ya = cart.y(base[i])
        yb = cart.y(base[i] + vals[i])
        y_top = min(ya, yb)
        y_bot = max(ya, yb)
        if i == 0 or i == n - 1:
            color = palette[0]
        elif vals[i] >= 0:
            color = palette[1]
        else:
            color = palette[2]
        parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>'
                     % (cart.x0 + group_w * i + group_w * 0.24, y_top, bar_w,
                        max(1.0, y_bot - y_top), _e(color)))
        parts.append('<text x="%.1f" y="%.1f" font-size="10" fill="&YTLABEL;" text-anchor="middle">%s</text>'
                     % (cart.x0 + group_w * i + group_w / 2, y_top - 4, _e(_fmt_num(vals[i]))))
        if 0 < i < n - 1:
            x_prev = cart.x0 + group_w * (i - 1) + group_w / 2
            x_cur = cart.x0 + group_w * i + group_w / 2
            y_prev = cart.y(base[i])
            parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="&YTAXIS;" stroke-width="1" stroke-dasharray="3,3"/>'
                         % (x_prev, y_prev, x_cur, y_prev))
    step = 1
    while n > 12 and n % step != 0:
        step += 1
    for i in range(0, n, step):
        label = _text_wrapped(labels[i], 10) if i < len(labels) else ""
        parts.append('<text x="%.1f" y="%d" font-size="11" fill="&YTLABEL;" text-anchor="middle">%s</text>'
                     % (cart.x0 + group_w * i + group_w / 2, height - 18, _e(label)))
    parts.append(_legend([("累计", palette[0]), ("增加", palette[1]), ("减少", palette[2])],
                         cart.x0, 44))
    return _svg_wrap("\n".join(parts), width, height, title)


def _word_cloud(data, width, height, title, palette, max_words=60):
    """词云：data=[{"text":..,"weight":..}, ...] 或 data=[[text, weight], ...]。
    简化实现：按权重降序，逐行填充（行式排布，稳定可复现）。"""
    words = []
    for item in _as_list(data):
        if isinstance(item, dict):
            t = str(item.get("text", item.get("word", "")))
            w = _num(item.get("weight", item.get("value", 1)), 1)
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            t = str(item[0])
            w = _num(item[1], 1)
        else:
            t = str(item)
            w = 1.0
        if t.strip():
            words.append((t, max(0.0, w)))
    if not words:
        return _svg_wrap('<text x="%d" y="%d" font-size="14" fill="&YTMUTED;" text-anchor="middle">无数据</text>'
                         % (width / 2, height / 2), width, height, title)
    words.sort(key=lambda x: -x[1])
    words = words[:max_words]
    maxw = max(w for _, w in words) or 1.0
    minw = min(w for _, w in words)
    span = (maxw - minw) or 1.0
    top = 52
    bottom = height - 24
    usable = bottom - top
    # 字号 16..54 映射
    def _font(w):
        return 16 + int(38 * (w - minw) / span)
    # 行式排布
    parts = []
    y = top + 20
    x = width * 0.08
    line_h = 0
    first = True
    for idx, (t, w) in enumerate(words):
        fs = _font(w)
        tw = len(t) * fs * 0.72  # 粗略宽度
        if not first and x + tw > width * 0.92:
            x = width * 0.08
            y += line_h + 6
            line_h = 0
        color = palette[idx % len(palette)]
        parts.append('<text x="%.1f" y="%d" font-size="%d" font-weight="%d" fill="%s">%s</text>'
                     % (x, y, fs, 700 if w >= maxw * 0.8 else 500, _e(color), _e(t)))
        x += tw + 8
        line_h = max(line_h, fs)
        first = False
        if y > bottom:
            break
    return _svg_wrap("\n".join(parts), width, height, title)


def _sankey(data, width, height, title, palette):
    """桑基图：nodes=[{id,label}] + links=[{source,target,value}]（两列简化布局）。"""
    nodes = data.get("nodes") if isinstance(data, dict) else None
    links = data.get("links") if isinstance(data, dict) else []
    node_map = {}
    if nodes:
        for nd in nodes:
            nid = str(nd.get("id"))
            node_map[nid] = {"label": str(nd.get("label", nid)), "id": nid}
    for lk in links:
        src = str(lk.get("source"))
        tgt = str(lk.get("target"))
        if src not in node_map:
            node_map[src] = {"label": src, "id": src}
        if tgt not in node_map:
            node_map[tgt] = {"label": tgt, "id": tgt}
    if not links or not node_map:
        return _svg_wrap('<text x="%d" y="%d" font-size="14" fill="&YTMUTED;" text-anchor="middle">无数据</text>'
                         % (width / 2, height / 2), width, height, title)
    sources = []
    targets = []
    for lk in links:
        s = str(lk.get("source"))
        t = str(lk.get("target"))
        if s not in sources:
            sources.append(s)
        if t not in targets:
            targets.append(t)
    left = [node_map[s] for s in sources]
    right = [node_map[t] for t in targets]
    # 节点流量 = 出/入 link 值之和
    flow = {}
    for lk in links:
        v = max(0.0, _num(lk.get("value"), 0))
        flow[str(lk.get("source"))] = flow.get(str(lk.get("source")), 0.0) + v
        flow[str(lk.get("target"))] = flow.get(str(lk.get("target")), 0.0) + v
    top = 56
    bottom = height - 30
    band = (bottom - top) / max(1, max(len(left), len(right)))

    def _pos(side_list, node_id):
        idx = side_list.index(node_id) if node_id in side_list else 0
        total = len(side_list)
        return top + band * (idx + 0.5)

    x0 = width * 0.14
    x1 = width * 0.86
    parts = []
    max_flow = max(flow.values(), default=1) or 1
    # 先画 link 贝塞尔（半透明）
    for lk in links:
        s = str(lk.get("source"))
        t = str(lk.get("target"))
        v = max(0.0, _num(lk.get("value"), 0))
        y0 = _pos(sources, s)
        y1 = _pos(targets, t)
        sw = max(2.0, 22.0 * v / max_flow)
        d = ("M %.1f %.1f C %.1f %.1f %.1f %.1f %.1f %.1f L %.1f %.1f C %.1f %.1f %.1f %.1f %.1f %.1f Z"
             % (x0, y0 - sw / 2, (x0 + x1) / 2, y0 - sw / 2,
                (x0 + x1) / 2, y1 - sw / 2, x1, y1 - sw / 2,
                x1, y1 + sw / 2, (x0 + x1) / 2, y1 + sw / 2,
                (x0 + x1) / 2, y0 + sw / 2, x0, y0 + sw / 2))
        parts.append('<path d="%s" fill="%s" fill-opacity="0.30"/>' % (d, _e(palette[1])))

    def _node_rect(node, side):
        x = x0 if side == "L" else x1
        yc = _pos(sources, node["id"]) if side == "L" else _pos(targets, node["id"])
        f = flow.get(node["id"], 0)
        h = max(8.0, 30.0 * f / max_flow)
        anchor = "end" if side == "L" else "start"
        tx = x - 8 if side == "L" else x + 8
        return ('<rect x="%.1f" y="%.1f" width="10" height="%.1f" rx="2" fill="%s"/>'
                '<text x="%.1f" y="%.1f" font-size="11" fill="&YTLABEL;" text-anchor="%s">%s</text>'
                % (x, yc - h / 2, h, _e(palette[0]), tx, yc + 4, anchor,
                   _e(_text_wrapped(node["label"], 14))))

    for nd in left:
        parts.append(_node_rect(nd, "L"))
    for nd in right:
        parts.append(_node_rect(nd, "R"))
    return _svg_wrap("\n".join(parts), width, height, title)


def _spreadsheet(data, width, height, title, palette, headers=None):
    """表格：data=二维数组（每行一个列表）；headers 可选列头。"""
    rows = []
    if isinstance(data, list):
        for r in data:
            if isinstance(r, (list, tuple)):
                rows.append([str(c) for c in r])
            else:
                rows.append([str(r)])
    if not rows:
        return _svg_wrap('<text x="%d" y="%d" font-size="14" fill="&YTMUTED;" text-anchor="middle">无数据</text>'
                         % (width / 2, height / 2), width, height, title)
    hdrs = _as_list(headers) if headers else []
    ncol = max(len(hdrs), max((len(r) for r in rows), default=1))
    left = 24
    right = width - 24
    usable = max(100, right - left)
    col_w = usable / max(1, ncol)
    row_h = 26
    hdr_h = 30 if hdrs else 0
    top = 52
    max_rows = max(1, int((height - top - hdr_h - 20) / row_h))
    visible = rows[:max_rows]
    parts = []
    # 表头
    for c in range(ncol):
        x = left + col_w * c
        txt = _text_wrapped(hdrs[c], 14) if c < len(hdrs) else ""
        parts.append('<rect x="%.1f" y="%d" width="%.1f" height="%d" fill="&YTSURFACE2;" stroke="&YTBORDER;"/>'
                     % (x, top, col_w + 0.5, hdr_h))
        parts.append('<text x="%.1f" y="%d" font-size="12" font-weight="600" fill="&YTLABEL;">%s</text>'
                     % (x + 8, top + hdr_h - 9, _e(txt)))
    # 数据行（斑马纹）
    for ri, r in enumerate(visible):
        y = top + hdr_h + ri * row_h
        if ri % 2 == 1:
            parts.append('<rect x="%d" y="%d" width="%d" height="%d" fill="&YTSURFACE;"/>'
                         % (left, y, int(usable) + 1, row_h))
        for c in range(ncol):
            x = left + col_w * c
            txt = _text_wrapped(r[c], 14) if c < len(r) else ""
            parts.append('<text x="%.1f" y="%.1f" font-size="11" fill="&YTTEXT;">%s</text>'
                         % (x + 8, y + row_h - 8, _e(txt)))
    if len(rows) > max_rows:
        parts.append('<text x="%d" y="%d" font-size="11" fill="&YTMUTED;" text-anchor="middle">… 还有 %d 行未显示</text>'
                     % (width / 2, height - 8, len(rows) - max_rows))
    return _svg_wrap("\n".join(parts), width, height, title)


def _treemap(data, width, height, title, palette, max_boxes=60):
    """矩形树图：data=[{label,value}] 或 data=[[label,value],...]。
    简化 squarify：按 value 降序，递归沿长边二分切矩形。"""
    boxes = []
    for item in _as_list(data):
        if isinstance(item, dict):
            label = str(item.get("label", item.get("name", "")))
            value = max(0.0, _num(item.get("value", 0), 0))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            label = str(item[0])
            value = max(0.0, _num(item[1], 0))
        else:
            label = str(item)
            value = 1.0
        if value > 0:
            boxes.append((label, value))
    if not boxes:
        return _svg_wrap('<text x="%d" y="%d" font-size="14" fill="&YTMUTED;" text-anchor="middle">无数据</text>'
                         % (width / 2, height / 2), width, height, title)
    boxes.sort(key=lambda x: -x[1])
    boxes = boxes[:max_boxes]
    total = sum(v for _, v in boxes)
    parts = []
    left = 24
    top = 52
    right = width - 24
    bottom = height - 20

    def _split(rect, items):
        if not items or rect[2] - rect[0] < 20 or rect[3] - rect[1] < 20:
            return
        if len(items) == 1:
            _emit(rect, items[0])
            return
        sub_total = sum(v for _, v in items)
        if sub_total <= 0:
            return
        x0, y0, x1, y1 = rect
        w = x1 - x0
        h = y1 - y0
        half = sub_total / 2.0
        acc = 0.0
        cut = 1
        for i in range(len(items)):
            acc += items[i][1]
            if acc >= half:
                cut = i + 1
                break
        cut = max(1, min(len(items) - 1, cut))
        group_a = items[:cut]
        group_b = items[cut:]
        va = sum(v for _, v in group_a) or 1
        vb = sum(v for _, v in group_b) or 1
        if w >= h:  # 垂直切
            xm = x0 + w * va / (va + vb)
            _split((x0, y0, xm, y1), group_a)
            _split((xm, y0, x1, y1), group_b)
        else:  # 水平切
            ym = y0 + h * va / (va + vb)
            _split((x0, y0, x1, ym), group_a)
            _split((x0, ym, x1, y1), group_b)

    _idx = [0]

    def _emit(rect, item):
        x0, y0, x1, y1 = rect
        label, value = item
        color = palette[_idx[0] % len(palette)]
        _idx[0] += 1
        parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" stroke="&YTEDGE;" stroke-width="1"/>'
                     % (x0 + 1, y0 + 1, max(1, x1 - x0 - 2), max(1, y1 - y0 - 2), _e(color)))
        fs = 11 if (x1 - x0) > 70 and (y1 - y0) > 30 else 9
        pct = "%.0f%%" % (100.0 * value / total)
        parts.append('<text x="%.1f" y="%.1f" font-size="%d" font-weight="600" fill="&YTCHIP;">%s</text>'
                     % (x0 + 6, y0 + 16, fs, _e(_text_wrapped(label, 18))))
        if (y1 - y0) > 40:
            parts.append('<text x="%.1f" y="%.1f" font-size="10" fill="&YTCHIP;" fill-opacity="0.85">%s</text>'
                         % (x0 + 6, y0 + 30, _e(pct)))

    _split((left, top, right, bottom), boxes)
    return _svg_wrap("\n".join(parts), width, height, title)

def _svg_bg_free():
    return ""

# ---------------------------------------------------------------------------
# 统一入口：render(chart, params) -> {svg, path, data_uri, width, height, meta}
# ---------------------------------------------------------------------------

_RENDERERS = {
    "bar": _bar,
    "line": _line,
    "pie": _pie,
    "radar": _radar,
    "scatter": _scatter,
    "histogram": _histogram,
    "funnel": _funnel,
    "waterfall": _waterfall,
    "word_cloud": _word_cloud,
    "sankey": _sankey,
    "spreadsheet": _spreadsheet,
    "treemap": _treemap,
}


def _default_width(chart):
    return 700 if chart == "spreadsheet" else 800


def _default_height(chart):
    if chart in ("funnel", "sankey"):
        return 520
    if chart == "word_cloud":
        return 480
    if chart == "spreadsheet":
        return 480
    return 500


def render(chart, params=None):
    """渲染一种图表，返回 dict。

    入参 params（MCP / CLI 归一化后）：
      theme / title / labels / data / width / height / palette / filename / out / stacked /
      fill / show_pct / bins / headers / max_words / max_boxes
    返回：
      {chart, svg, path, data_uri, width, height, meta}
    其中 data_uri 为 data:image/svg+xml;base64,...；path 在写文件后存在。
    """
    chart = (chart or "").strip().lower()
    if chart not in _RENDERERS:
        raise ValueError("不支持的图表类型：%s（可选：%s）" % (chart, ", ".join(CHART_TYPES)))
    params = params or {}
    width = int(_num(params.get("width"), _default_width(chart)))
    height = int(_num(params.get("height"), _default_height(chart)))
    width = max(240, min(2400, width))
    height = max(160, min(2000, height))
    theme = str(params.get("theme") or "light").strip().lower()
    theme = "dark" if theme == "dark" else "light"
    palette = _palette_for(theme, params.get("palette"))
    title = params.get("title") or ""
    labels = _as_list(params.get("labels"))
    data = params.get("data")
    if isinstance(data, str):
        # 字符串：优先按 JSON 解析；失败则按逗号拆分成数值
        try:
            data = json.loads(data)
        except (ValueError, TypeError):
            data = [_num(x) for x in _as_list(data)]
    fn = _RENDERERS[chart]
    no_labels = chart in ("histogram", "word_cloud", "sankey", "spreadsheet", "treemap")
    kwargs = {"data": data, "width": width, "height": height,
              "title": title, "palette": palette}
    if not no_labels:
        kwargs["labels"] = labels
    if chart == "bar":
        kwargs["stacked"] = bool(params.get("stacked"))
    if chart == "line":
        kwargs["fill"] = bool(params.get("fill"))
    if chart == "pie":
        kwargs["show_pct"] = bool(params.get("show_pct", True))
    if chart == "histogram":
        kwargs["bins"] = params.get("bins")
    if chart == "word_cloud":
        kwargs["max_words"] = int(_num(params.get("max_words"), 60))
    if chart == "treemap":
        kwargs["max_boxes"] = int(_num(params.get("max_boxes"), 60))
    if chart == "spreadsheet":
        kwargs["headers"] = params.get("headers")
    _use_theme(theme)
    try:
        svg = fn(**kwargs)
    finally:
        _reset_theme()
    result = {
        "chart": chart,
        "svg": svg,
        "width": width,
        "height": height,
        "path": None,
        "data_uri": "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii"),
        "meta": {"version": VERSION, "theme": theme, "palette": params.get("palette") or "default",
                 "title": title, "labels_count": len(labels), "renderer": chart},
    }
    out = params.get("out")
    filename = params.get("filename")
    if out:
        out = os.path.abspath(os.path.expanduser(str(out)))
        if os.path.isdir(out):
            out = os.path.join(out, filename or "yotta-present-%s.svg" % chart)
        parent = os.path.dirname(out)
        if parent:
            os.makedirs(parent, exist_ok=True)
        _write_utf8(out, svg)
        result["path"] = out
    elif filename:
        out = os.path.abspath(os.path.expanduser(str(filename)))
        parent = os.path.dirname(out)
        if parent:
            os.makedirs(parent, exist_ok=True)
        _write_utf8(out, svg)
        result["path"] = out
    return result


def _write_utf8(path, text):
    """UTF-8 无 BOM 写文件。"""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _parse_data_arg(raw):
    """CLI --data 解析：先试 JSON，再试逗号数值。"""
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return [_num(x) for x in _as_list(raw)]


def cli(argv=None):
    """CLI 入口：python yotta_chart.py <chart> [options]。"""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print("元呈 yotta-present %s — 本地零依赖 SVG 可视化（Python 3.8+ stdlib）" % VERSION)
        print("用法：python yotta_chart.py <chart> [--title T] [--labels a,b,c] [--data 1,2,3]")
        print("      [--out out.svg] [--width 800] [--height 500] [--palette default] [--theme light|dark] [--json]")
        print("图表：%s" % ", ".join(CHART_TYPES))
        return 0
    if argv[0].lower() in ("--check-contrast", "check-contrast", "check_contrast"):
        ok, report = check_contrast()
        print("元呈 yotta-chart 主题对比度自查（WCAG AA，文本 >= 4.5:1）")
        print(report)
        return 0 if ok else 2
    chart = argv[0].lower()
    params = {}
    i = 1
    while i < len(argv):
        a = argv[i]
        if a.startswith("--") and i + 1 < len(argv):
            key = a[2:].replace("-", "_")
            val = argv[i + 1]
            if key in ("title", "labels", "data", "out", "filename", "palette",
                       "theme", "headers", "bins"):
                params[key] = val
            elif key in ("width", "height", "max_words", "max_boxes"):
                params[key] = _num(val, 0)
            elif key in ("stacked", "fill", "show_pct"):
                params[key] = str(val).lower() in ("1", "true", "yes", "on")
            i += 2
        elif a == "--json":
            params["_json"] = True
            i += 1
        else:
            i += 1
    params["data"] = _parse_data_arg(params.get("data"))
    if params.get("labels") and isinstance(params.get("labels"), str):
        params["labels"] = _as_list(params["labels"])
    if params.get("headers") and isinstance(params.get("headers"), str):
        params["headers"] = _as_list(params["headers"])
    try:
        result = render(chart, params)
    except Exception as e:  # noqa: BLE001
        print("错误：%s" % e, file=sys.stderr)
        return 2
    if params.get("_json") or not result.get("path"):
        print(json.dumps({k: v for k, v in result.items() if k != "svg"},
                         ensure_ascii=False, indent=2))
    else:
        print("已生成：%s（%dx%d，%s）" % (result["path"], result["width"],
                                         result["height"], result["chart"]))
    return 0


if __name__ == "__main__":
    sys.exit(cli())
