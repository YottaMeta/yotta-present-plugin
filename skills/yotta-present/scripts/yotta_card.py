#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""yotta_card.py — 元呈（yotta-present）R3 SVG 整卡内核（开源 demo，v0.7.0）。

三形态整卡：conclusion（结论卡）/ metrics（指标板）/ table（表格卡）。
四场景模板：references/cards.json（release / weekly / compare / risk，可热更新）。
品牌 token：theme.json.brand + 品牌文件（name / primary / accent / footer / logo）。

可编辑 SVG 标准（渲染后 check_editable() 结构自检，失败即拒绝输出 = fail-closed）：
  - 文本全部 <text>/<tspan>（不转路径），元素带语义 id（card-header / card-body / ...）；
  - 无 <script> / 无外链引用 / 无 <foreignObject>；不栅格化；不引外部字体（系统字体栈）。

复用 yotta_chart 的 XML 转义（_e）与主题 token 取色（_theme_colors）；
不修改 yotta_chart，不在渲染函数里散落硬编码主题色。
"""

import base64
import json
import os
import re
import sys
import unicodedata
from xml.etree import ElementTree

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import yotta_chart as yc  # noqa: E402

VERSION = "0.7.1"

CARD_WIDTH = 720
PAD = 36
INNER_W = CARD_WIDTH - PAD * 2

R3_FORMS = ("conclusion", "metrics", "table")
_FORM_TITLE = {"conclusion": "结论卡", "metrics": "指标板", "table": "表格卡"}

MAX_BULLETS = 8
MAX_METRICS = 8
MAX_ROWS = 10
MAX_COLS = 4
MAX_NOTES = 4
MAX_CARD_HEIGHT = 2000

# 等级文案与 yotta_present.GRADE_META 对齐（测试断言防漂移）
GRADE_TEXT = {"success": "通过", "warn": "警告", "danger": "危险", "info": "信息"}
_GRADE_TONES = ("success", "warn", "danger", "info")

_CARDS_BUILTIN = {
    "release": {
        "title": "发布结果",
        "kicker": "RELEASE",
        "form": "conclusion",
        "sections": ["summary", "metrics"],
        "note": "版本发布 / 交付验收结果卡（结论 + 指标）",
    },
    "weekly": {
        "title": "数据快报",
        "kicker": "WEEKLY",
        "form": "metrics",
        "sections": ["metrics"],
        "note": "周报 / 使用统计快报卡（指标板）",
    },
    "compare": {
        "title": "对比评测",
        "kicker": "COMPARE",
        "form": "table",
        "sections": ["table"],
        "note": "方案 / 产品对比评测卡（表格）",
    },
    "risk": {
        "title": "风险报告",
        "kicker": "RISK",
        "form": "conclusion",
        "sections": ["summary", "table"],
        "tone": "danger",
        "note": "安全 / 风险报告卡（结论 + 明细表）",
    },
}


class CardError(Exception):
    """R3 整卡错误（带 hint；由 yotta_present 统一转 PresentError）。"""

    def __init__(self, message, hint=None):
        super().__init__(message)
        self.hint = hint


def _load_cards():
    """从 references/cards.json 加载整卡模板（可热更新）；缺失/损坏回退内置。"""
    ref = os.path.join(_HERE, "..", "references", "cards.json")
    try:
        with open(ref, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            out = {}
            for key, val in data.items():
                if isinstance(val, dict) and val.get("form") in R3_FORMS:
                    out[str(key)] = val
            if out:
                return out
    except Exception:  # noqa: BLE001
        pass
    return dict(_CARDS_BUILTIN)


CARDS = _load_cards()


# ---------------------------------------------------------------------------
# 文本宽度 / 确定性折行（CJK + 西文混排；上限保护）
# ---------------------------------------------------------------------------

def _char_w(ch, size):
    if ch == " ":
        return 0.32 * size
    if ch == "\t":
        return 1.28 * size
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 1.0 * size
    if ch.isdigit():
        return 0.58 * size
    if ch.isupper():
        return 0.66 * size
    return 0.55 * size


def text_width(text, size):
    """按字符宽度近似表估算文本宽度（px）；确定性、无外部依赖。"""
    return sum(_char_w(c, size) for c in str(text))


def _wrap_all(text, max_w, size):
    lines = []
    for para in str(text if text is not None else "").split("\n"):
        cur = ""
        for ch in para:
            if cur and text_width(cur, size) + _char_w(ch, size) > max_w:
                sp = cur.rfind(" ")
                tail = (cur[sp + 1:] + ch) if sp >= 0 else ""
                if sp > 0 and tail and text_width(tail, size) <= max_w:
                    lines.append(cur[:sp].rstrip())
                    cur = tail
                else:
                    lines.append(cur)
                    cur = ch
            else:
                cur += ch
        lines.append(cur)
    return lines or [""]


def wrap_text(text, max_w, size, max_lines=3):
    """确定性折行；超出 max_lines 时末行加省略号。返回 (lines, truncated)。"""
    s = str(text if text is not None else "")
    if len(s) > 2000:
        s = s[:2000]
    lines = _wrap_all(s, max_w, size)
    if len(lines) <= max_lines:
        return lines, False
    lines = lines[:max_lines]
    last = lines[-1]
    while last and text_width(last + "…", size) > max_w:
        last = last[:-1]
    lines[-1] = last + "…"
    return lines, True


# ---------------------------------------------------------------------------
# 主题 token 取色（复用 yotta_chart；缺 token 不崩）
# ---------------------------------------------------------------------------

def _colors(theme):
    return yc._theme_colors(theme)


def _semantic(tone, theme, part="bg"):
    t = str(tone or "").strip().lower()
    sem = (yc.THEME.get("semantic") or {}).get(t) or {}
    entry = sem.get(theme) or {}
    if not entry:
        neutral = (yc.THEME.get("semantic") or {}).get("neutral") or {}
        entry = neutral.get(theme) or {}
    if not entry:
        neutral = (yc._THEME_BUILTIN.get("semantic") or {}).get("neutral") or {}
        entry = neutral.get(theme) or {}
    return entry.get(part) or _colors(theme)["text"]


def _form_accent(form, theme):
    fa = yc.THEME.get("form_accent") or {}
    val = fa.get(form) or (yc._THEME_BUILTIN.get("form_accent") or {}).get(form)
    return val or _colors(theme)["text"]


# ---------------------------------------------------------------------------
# 品牌 token（theme.json.brand + --brand 文件；白名单 + 校验）
# ---------------------------------------------------------------------------

BRAND_KEYS = ("name", "primary", "accent", "footer", "logo")
_MAX_LOGO_BYTES = 262144  # 256 KB
_LOGO_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _norm_hex(value, field):
    s = str(value).strip()
    if not _HEX_RE.match(s):
        raise CardError(
            "品牌色 %s 无效：%s" % (field, s),
            hint="请用十六进制色值，如 #2F6FED 或 #fff；可用 references/brand.example.json 作模板。",
        )
    if len(s) == 4:
        s = "#" + "".join(c * 2 for c in s[1:])
    return s.lower()


def _theme_brand():
    b = yc.THEME.get("brand")
    out = {}
    if isinstance(b, dict):
        for k in ("name", "footer"):
            v = b.get(k)
            if isinstance(v, str) and v.strip():
                out[k] = v.strip()
        for k in ("primary", "accent"):
            v = b.get(k)
            if isinstance(v, str) and _HEX_RE.match(v.strip()):
                out[k] = _norm_hex(v, k)
    return out


def _embed_logo(brand_file, ref):
    lp = ref if os.path.isabs(ref) else os.path.join(os.path.dirname(brand_file), ref)
    lp = os.path.abspath(lp)
    ext = os.path.splitext(lp)[1].lower()
    if ext == ".svg":
        raise CardError(
            "不支持 SVG logo：%s" % lp,
            hint="logo 仅支持本地 PNG / JPEG 文件（SVG 嵌套 XML 有注入面，v1 不开放）。",
        )
    if ext not in _LOGO_MIME:
        raise CardError(
            "不支持的 logo 类型：%s" % (ext or "（无扩展名）"),
            hint="logo 仅支持 .png / .jpg / .jpeg 文件。",
        )
    if not os.path.isfile(lp):
        raise CardError("logo 文件不存在：%s" % lp, hint="logo 路径相对品牌文件所在目录；请检查文件是否存在。")
    size = os.path.getsize(lp)
    if size > _MAX_LOGO_BYTES:
        raise CardError(
            "logo 文件过大：%d 字节（上限 %d 字节 / 256 KB）" % (size, _MAX_LOGO_BYTES),
            hint="请压缩 logo 后重试。",
        )
    with open(lp, "rb") as f:
        raw = f.read()
    if ext == ".png" and not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise CardError("logo 扩展名是 .png，但内容不是 PNG 图片：%s" % lp, hint="请换用真实 PNG / JPEG 文件。")
    if ext in (".jpg", ".jpeg") and not raw.startswith(b"\xff\xd8\xff"):
        raise CardError("logo 扩展名是 JPEG，但内容不是 JPEG 图片：%s" % lp, hint="请换用真实 PNG / JPEG 文件。")
    return "data:%s;base64,%s" % (_LOGO_MIME[ext], base64.b64encode(raw).decode("ascii"))


def _load_brand_file(path):
    """读取品牌文件（白名单字段 + 校验）。返回 (brand, warnings)。"""
    p = os.path.abspath(os.path.expanduser(str(path)))
    try:
        # utf-8-sig：容忍 Windows 记事本 / PowerShell 写出的 UTF-8 BOM
        with open(p, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise CardError(
            "品牌文件不存在：%s" % p,
            hint="请检查 --brand 路径；可用 references/brand.example.json 作为模板。",
        )
    except (OSError, ValueError) as e:
        raise CardError(
            "品牌文件无法解析：%s" % e,
            hint="品牌文件须为 UTF-8 JSON 对象，字段：name / primary / accent / footer / logo。",
        )
    if not isinstance(data, dict):
        raise CardError("品牌文件顶层必须是 JSON 对象", hint="请用 references/brand.example.json 作模板。")
    brand = {}
    warnings = []
    for key, val in data.items():
        if key not in BRAND_KEYS:
            warnings.append("品牌文件忽略未知字段：%s（白名单：%s）" % (key, " / ".join(BRAND_KEYS)))
            continue
        if key == "logo":
            if val in (None, ""):
                continue
            brand["logo_data_uri"] = _embed_logo(p, str(val))
        elif key in ("primary", "accent"):
            brand[key] = _norm_hex(val, key)
        else:
            s = str(val).strip()
            if s:
                brand[key] = s
    return brand, warnings


def resolve_brand(brand_path=None):
    """生效品牌 = theme.json.brand（默认空）浅合并 --brand 文件。返回 (brand, warnings)。"""
    brand = _theme_brand()
    warnings = []
    if brand_path:
        user, warns = _load_brand_file(brand_path)
        brand.update(user)
        warnings.extend(warns)
    return brand, warnings


# ---------------------------------------------------------------------------
# SVG 原语（文本全部 <text>/<tspan>）
# ---------------------------------------------------------------------------

def _fmt(v):
    f = float(v)
    if abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    return ("%.1f" % f).rstrip("0").rstrip(".")


def _emit_text(x, y, lines, size, fill, line_h, tid, weight=None, anchor=None, spacing=None):
    attrs = ['id="%s"' % tid, 'x="%s"' % _fmt(x), 'y="%s"' % _fmt(y),
             'font-size="%s"' % _fmt(size), 'fill="%s"' % fill]
    if weight is not None:
        attrs.append('font-weight="%s"' % weight)
    if anchor:
        attrs.append('text-anchor="%s"' % anchor)
    if spacing is not None:
        attrs.append('letter-spacing="%s"' % _fmt(spacing))
    out = ["<text %s>" % " ".join(attrs)]
    for i, line in enumerate(lines):
        dy = 0 if i == 0 else line_h
        out.append('<tspan x="%s" dy="%s">%s</tspan>' % (_fmt(x), _fmt(dy), yc._e(line)))
    out.append("</text>")
    return "".join(out)


def _emit_chip(x, y, text, fill, fg, tid):
    w = text_width(text, 13) + 28
    return ('<g id="%s"><rect id="%s-bg" x="%s" y="%s" width="%s" height="26" rx="13" fill="%s"/>'
            '%s</g>') % (
        tid, tid, _fmt(x), _fmt(y), _fmt(w), fill,
        _emit_text(x + 14, y + 18, [text], 13, fg, 13, tid + "-text", weight=600),
    )


def _emit_brand_mark(brand, cols, accent, right_x, top):
    logo = brand.get("logo_data_uri")
    name = brand.get("name")
    if logo:
        return ('<g id="card-brand"><image id="card-brand-logo" x="%s" y="%s" width="120" height="28" '
                'preserveAspectRatio="xMaxYMid meet" href="%s"/></g>') % (
            _fmt(right_x - 120), _fmt(top), logo,
        )
    if name:
        ch = str(name).strip()[:1] or "•"
        name_lines, _ = wrap_text(str(name), 120, 13, max_lines=1)
        return ('<g id="card-brand">'
                '<circle id="card-brand-monogram" cx="%s" cy="%s" r="14" fill="%s"/>'
                '%s'
                '<text id="card-brand-monogram-text" x="%s" y="%s" font-size="14" font-weight="700" '
                'text-anchor="middle" fill="%s">%s</text>'
                '%s'
                '</g>') % (
            _fmt(right_x - 14), _fmt(top + 14), accent,
            _emit_text(right_x - 38, top + 19, name_lines, 13, cols["label"], 13, "card-brand-name", anchor="end"),
            _fmt(right_x - 14), _fmt(top + 19), cols["on_chip"], yc._e(ch),
            "",
        )
    return ""


# ---------------------------------------------------------------------------
# 分节布局（conclusion / metrics / table + notes + footer）
# ---------------------------------------------------------------------------

def _section_summary(y, content, cols, accent, theme):
    parts = []
    grade_raw = str(content.get("grade") or "").strip()
    if grade_raw:
        tone = grade_raw.lower() if grade_raw.lower() in _GRADE_TONES else "neutral"
        chip_text = GRADE_TEXT.get(grade_raw.lower()) or grade_raw
        parts.append(_emit_chip(PAD, y, chip_text, _semantic(tone, theme, "bg"), _semantic(tone, theme, "fg"), "card-grade"))
        y += 26 + 16
    verdict = content.get("verdict")
    if verdict:
        lines, _ = wrap_text(str(verdict), INNER_W, 18, max_lines=3)
        parts.append(_emit_text(PAD, y + 20, lines, 18, cols["text"], 28, "card-summary-text", weight=600))
        y += 20 + (len(lines) - 1) * 28 + 12
    headline = content.get("headline")
    if headline and headline != verdict:
        lines, _ = wrap_text(str(headline), INNER_W, 14, max_lines=2)
        parts.append(_emit_text(PAD, y + 16, lines, 14, cols["label"], 22, "card-headline"))
        y += 16 + (len(lines) - 1) * 22 + 10
    bullets = content.get("bullets") or []
    shown = list(bullets)[:MAX_BULLETS]
    for i, b in enumerate(shown):
        lines, _ = wrap_text(str(b), INNER_W - 18, 14, max_lines=2)
        parts.append('<circle id="card-bullet-%d-dot" cx="%s" cy="%s" r="3" fill="%s"/>'
                     % (i, _fmt(PAD + 5), _fmt(y + 10), accent))
        parts.append(_emit_text(PAD + 18, y + 15, lines, 14, cols["text"], 22, "card-bullet-text-%d" % i))
        y += 15 + (len(lines) - 1) * 22 + 10
    extra = len(bullets) - len(shown)
    if extra > 0:
        parts.append(_emit_text(PAD, y + 12, ["另有 %d 条要点未显示" % extra], 12, cols["muted"], 16, "card-bullets-more"))
        y += 20
    return parts, y


def _section_metrics(y, metrics, cols, theme):
    parts = []
    shown = list(metrics)[:MAX_METRICS]
    gap = 12.0
    tw = (INNER_W - gap) / 2.0
    th = 92.0
    for i, m in enumerate(shown):
        col_i = i % 2
        row_i = i // 2
        x = PAD + col_i * (tw + gap)
        ty = y + row_i * (th + gap)
        tone = str(m.get("tone") or "").strip().lower()
        arrow = {"up": "▲", "down": "▼", "neutral": "—"}.get(tone, "")
        arrow_color = _semantic({"up": "success", "down": "danger"}.get(tone, "neutral"), theme, "text")
        label = str(m.get("label", ""))
        value = str(m.get("value", ""))
        unit = str(m.get("unit", "")).strip()
        parts.append('<g id="metric-%d">' % i)
        parts.append('<rect id="metric-%d-bg" x="%s" y="%s" width="%s" height="%s" rx="10" '
                     'fill="%s" stroke="%s" stroke-width="1"/>'
                     % (i, _fmt(x), _fmt(ty), _fmt(tw), _fmt(th), cols["surface"], cols["border"]))
        label_lines, _ = wrap_text(label, tw - 28, 12, max_lines=1)
        parts.append(_emit_text(x + 14, ty + 24, label_lines, 12, cols["label"], 12, "metric-%d-label" % i))
        unit_w = (text_width(unit, 13) + 6) if unit else 0.0
        vlines, _ = wrap_text(value, tw - 28 - unit_w, 28, max_lines=1)
        vtext = vlines[0]
        parts.append(_emit_text(x + 14, ty + 62, [vtext], 28, cols["text"], 28, "metric-%d-value" % i, weight=700))
        if unit:
            ux = x + 14 + text_width(vtext, 28) + 6
            parts.append(_emit_text(ux, ty + 62, [unit], 13, cols["muted"], 13, "metric-%d-unit" % i))
        if arrow:
            parts.append(_emit_text(x + tw - 14, ty + 24, [arrow], 12, arrow_color, 12, "metric-%d-tone" % i, anchor="end"))
        parts.append("</g>")
    y += ((len(shown) + 1) // 2) * (th + gap)
    extra = len(metrics) - len(shown)
    if extra > 0:
        parts.append(_emit_text(PAD, y + 12, ["另有 %d 项指标未显示" % extra], 12, cols["muted"], 16, "card-metrics-more"))
        y += 20
    return parts, y


def _table_parts(content):
    """本模块自带兜底解析（yotta_present 会显式传入同一口径的 table=(headers,data)）。"""
    rows = content.get("rows") or []
    headers = content.get("headers")
    if headers is None:
        if rows and isinstance(rows[0], dict):
            keys = []
            for r in rows:
                if isinstance(r, dict):
                    for k in r:
                        if k not in keys:
                            keys.append(k)
            headers = keys
            data = [[r.get(k, "") for k in headers] for r in rows]
        elif len(rows) >= 2 and rows[0] and all(isinstance(x, str) for x in rows[0]):
            headers = [str(x) for x in rows[0]]
            data = rows[1:]
        elif rows and len(rows[0]) == 2:
            headers = ["项", "值"]
            data = rows
        else:
            n = max((len(r) for r in rows), default=0)
            headers = ["列 %d" % (i + 1) for i in range(n)]
            data = rows
    else:
        headers = [str(h) for h in headers]
        data = [list(r.values()) if isinstance(r, dict) else list(r) for r in rows]
    return headers, data


def _section_table(y, headers, data, cols, theme):
    parts = []
    raw_rows = [list(r) if not isinstance(r, dict) else list(r.values()) for r in (data or [])]
    orig_rows = len(raw_rows)
    orig_cols = max([len(headers or [])] + [len(r) for r in raw_rows] + [0])
    rows = raw_rows[:MAX_ROWS]
    headers = [str(h) for h in (headers or [])][:MAX_COLS]
    ncols = min(max(len(headers), max((len(r) for r in rows), default=0), 1), MAX_COLS)
    if not headers:
        headers = ["列 %d" % (i + 1) for i in range(ncols)]
    headers = headers[:ncols]
    cells = [[str(r[i]) if i < len(r) else "" for i in range(ncols)] for r in rows]
    parts.append('<g id="card-table">')
    if not cells:
        parts.append(_emit_text(PAD, y + 20, ["（无数据）"], 13, cols["muted"], 13, "card-table-empty"))
        parts.append("</g>")
        return parts, y + 30
    raws = []
    for ci in range(ncols):
        w = text_width(headers[ci], 13)
        for r in cells:
            w = max(w, text_width(r[ci], 13))
        raws.append(max(w, 40.0))
    total = sum(raws) or 1.0
    widths = [max(80.0, min(260.0, r / total * INNER_W)) for r in raws]
    scale = INNER_W / sum(widths)
    widths = [w * scale for w in widths]
    row_lines = []
    for r in cells:
        per = []
        hl = 1
        for ci, cell in enumerate(r):
            lines, _ = wrap_text(cell, widths[ci] - 20, 13, max_lines=2)
            per.append(lines)
            hl = max(hl, len(lines))
        row_lines.append((per, hl))
    head_h = 38.0
    parts.append('<rect id="table-header-bg" x="%s" y="%s" width="%s" height="%s" rx="8" fill="%s"/>'
                 % (_fmt(PAD), _fmt(y), _fmt(INNER_W), _fmt(head_h), cols["surface_2"]))
    x = PAD
    for ci, htext in enumerate(headers):
        lines, _ = wrap_text(htext, widths[ci] - 20, 13, max_lines=1)
        parts.append(_emit_text(x + 10, y + 24, lines, 13, cols["label"], 13, "table-head-%d" % ci, weight=600))
        x += widths[ci]
    yy = y + head_h
    for ri, (per, hl) in enumerate(row_lines):
        rh = max(40.0, hl * 20 + 20)
        if ri % 2 == 1:
            parts.append('<rect id="table-row-%d-bg" x="%s" y="%s" width="%s" height="%s" fill="%s"/>'
                         % (ri, _fmt(PAD), _fmt(yy), _fmt(INNER_W), _fmt(rh), cols["surface"]))
        x = PAD
        for ci, lines in enumerate(per):
            parts.append(_emit_text(x + 10, yy + 22, lines, 13, cols["text"], 20, "table-cell-%d-%d" % (ri, ci)))
            x += widths[ci]
        yy += rh
    parts.append("</g>")
    extra_rows = orig_rows - len(rows)
    extra_cols = orig_cols - ncols
    msgs = []
    if extra_rows > 0:
        msgs.append("另有 %d 行未显示" % extra_rows)
    if extra_cols > 0:
        msgs.append("另有 %d 列未显示" % extra_cols)
    if msgs:
        parts.append(_emit_text(PAD, yy + 14, ["；".join(msgs) + "（可用 R1 文本通道查看全部）"],
                                12, cols["muted"], 16, "card-table-more"))
        yy += 22
    return parts, yy


def _section_notes(y, notes, cols):
    parts = []
    shown = list(notes)[:MAX_NOTES]
    for i, n in enumerate(shown):
        lines, _ = wrap_text("注：" + str(n), INNER_W, 12, max_lines=2)
        parts.append(_emit_text(PAD, y + 14, lines, 12, cols["muted"], 18, "card-note-%d" % i))
        y += 14 + (len(lines) - 1) * 18 + 8
    extra = len(notes) - len(shown)
    if extra > 0:
        parts.append(_emit_text(PAD, y + 12, ["另有 %d 条注记未显示" % extra], 12, cols["muted"], 16, "card-notes-more"))
        y += 20
    return parts, y


# ---------------------------------------------------------------------------
# 可编辑结构自检（fail-closed）
# ---------------------------------------------------------------------------

_REQ_IDS = ("r3-card", "card-header", "card-body", "card-title")


def check_editable(svg):
    """可编辑 SVG 标准自检。返回 (ok, problems)。"""
    problems = []
    low = svg.lower()
    if "<script" in low:
        problems.append("包含 <script>")
    if "foreignobject" in low:
        problems.append("包含 <foreignObject>")
    for tag in re.findall(r"<[^>]*>", low):
        if re.search(r"\son[a-z]+\s*=", tag):
            problems.append("包含事件属性（on*）")
            break
    for m in re.finditer(r'(?:xlink:)?href\s*=\s*"([^"]*)"', svg):
        val = m.group(1).strip()
        if not (val.startswith("data:") or val.startswith("#")):
            problems.append("包含外链引用：%s" % val[:60])
    if "<text" not in low:
        problems.append("无 <text> 元素（文本不可编辑）")
    for tid in _REQ_IDS:
        if ('id="%s"' % tid) not in svg:
            problems.append("缺少语义 id：%s" % tid)
    try:
        ElementTree.fromstring(svg)
    except ElementTree.ParseError as e:
        problems.append("XML 不合法：%s" % e)
    return (not problems), problems


# ---------------------------------------------------------------------------
# 渲染入口
# ---------------------------------------------------------------------------

def _resolve_template(card, form):
    if not card:
        return None, None
    key = str(card).strip().lower()
    if key not in CARDS:
        raise CardError(
            "未知整卡模板：%s（可选：%s）" % (key, " / ".join(sorted(CARDS))),
            hint="--card 可选 %s；不带 --card 时按 --form 直接出卡。" % " / ".join(sorted(CARDS)),
        )
    tpl = CARDS[key]
    if tpl.get("form") != form:
        return key, tpl
    return key, tpl


def _sections(form, tpl):
    if tpl and tpl.get("form") == form and isinstance(tpl.get("sections"), list):
        secs = [s for s in tpl["sections"] if s in ("summary", "metrics", "table")]
        if secs:
            return secs
    return {"conclusion": ["summary", "metrics"], "metrics": ["metrics"], "table": ["table"]}[form]


def _write_utf8(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def render(form, content, theme="light", card=None, brand=None, table=None, out=None):
    """渲染 R3 整卡，返回 dict（svg / width / height / path / data_uri / editable 等）。

    table=(headers, data) 由 yotta_present 传入（与表格形态同一解析口径）；
    直接调用时可省略，本模块自带兜底解析。
    """
    form = str(form or "").strip().lower()
    if form not in R3_FORMS:
        raise CardError(
            "R3 整卡不支持形态：%s" % (form or "（空）"),
            hint="R3 支持 conclusion / metrics / table 三种形态；其他形态请用默认 R1 通道。",
        )
    theme = "dark" if str(theme or "light").strip().lower() == "dark" else "light"
    content = dict(content or {})
    tpl_key, tpl = _resolve_template(card, form)
    brand_map, brand_warnings = resolve_brand(brand)
    cols = _colors(theme)
    accent = brand_map.get("primary") or _form_accent(form, theme)
    sections = _sections(form, tpl)
    title = str(content.get("title") or (tpl or {}).get("title") or _FORM_TITLE[form])
    kicker = str((tpl or {}).get("kicker") or "").strip()

    bullets = content.get("bullets") or []
    metrics = content.get("metrics") or []
    notes = content.get("notes") or []
    if table and isinstance(table, (list, tuple)) and len(table) == 2:
        headers, data = table[0], table[1]
    else:
        headers, data = _table_parts(content)
    truncated = {
        "bullets": max(0, len(bullets) - MAX_BULLETS),
        "metrics": max(0, len(metrics) - MAX_METRICS),
        "rows": max(0, len(data or []) - MAX_ROWS),
        "cols": max(0, max([len(headers or [])] + [len(r) for r in (data or [])] + [0]) - MAX_COLS),
        "notes": max(0, len(notes) - MAX_NOTES),
    }

    y = 36.0
    header_parts = []
    if kicker:
        header_parts.append(_emit_text(PAD, y + 12, [kicker], 11, brand_map.get("accent") or accent, 11,
                                       "card-kicker", weight=700, spacing=2))
        y += 26.0
    brand_mark = _emit_brand_mark(brand_map, cols, accent, CARD_WIDTH - PAD, y)
    right_w = 150.0 if brand_mark else 0.0
    title_lines, _ = wrap_text(title, INNER_W - right_w, 26, max_lines=2)
    header_parts.append(_emit_text(PAD, y + 26, title_lines, 26, cols["text"], 34, "card-title", weight=700))
    y += 26 + (len(title_lines) - 1) * 34 + 14
    header_parts.append('<line id="card-header-rule" x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" stroke-width="1"/>'
                        % (_fmt(PAD), _fmt(y), _fmt(CARD_WIDTH - PAD), _fmt(y), cols["border"]))
    if brand_mark:
        header_parts.append(brand_mark)
    y += 28

    body_parts = []
    for sec in sections:
        if sec == "summary":
            sp, y = _section_summary(y, content, cols, accent, theme)
            body_parts.extend(sp)
        elif sec == "metrics":
            mp, y = _section_metrics(y, metrics, cols, theme)
            body_parts.extend(mp)
        elif sec == "table":
            tp, y = _section_table(y, headers, data, cols, theme)
            body_parts.extend(tp)
    if notes:
        np_, y = _section_notes(y + 6, notes, cols)
        body_parts.extend(np_)

    footer_parts = []
    footer_text = str(brand_map.get("footer") or brand_map.get("name") or "").strip()
    if footer_text:
        y += 6
        footer_parts.append('<line id="card-footer-rule" x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" stroke-width="1"/>'
                            % (_fmt(PAD), _fmt(y), _fmt(CARD_WIDTH - PAD), _fmt(y), cols["border"]))
        flines, _ = wrap_text(footer_text, INNER_W, 12, max_lines=2)
        footer_parts.append(_emit_text(PAD, y + 24, flines, 12, cols["muted"], 18, "card-footer-text"))
        y += 24 + (len(flines) - 1) * 18

    height = y + 36
    if height > MAX_CARD_HEIGHT:
        raise CardError(
            "整卡内容过长（约 %d px，上限 %d px）" % (height, MAX_CARD_HEIGHT),
            hint="请精简条目（要点 / 指标 / 行数）或改用 R1 文本通道。",
        )

    desc = "元呈 R3 整卡：form=%s%s；文本可编辑（text-as-text）、元素带语义 id。" % (
        form, ("；template=%s" % tpl_key) if tpl_key else "")
    svg_parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" id="r3-card" width="%d" height="%d" viewBox="0 0 %d %d" '
        'font-family="%s" role="img" aria-labelledby="card-doc-title card-doc-desc">'
        % (CARD_WIDTH, int(round(height)), CARD_WIDTH, int(round(height)), yc._e(yc.FONT)),
        '<title id="card-doc-title">%s</title>' % yc._e(title),
        '<desc id="card-doc-desc">%s</desc>' % yc._e(desc),
        '<!-- yotta-present R3 card: form=%s%s theme=%s; editable SVG (text-as-text, semantic ids) -->'
        % (form, (" template=%s" % tpl_key) if tpl_key else "", theme),
        '<rect id="card-bg" x="0" y="0" width="%d" height="%d" fill="%s"/>' % (CARD_WIDTH, int(round(height)), cols["bg"]),
        '<g id="card-header">',
        "\n".join(header_parts),
        "</g>",
        '<g id="card-body">',
        "\n".join(body_parts),
        "</g>",
    ]
    if footer_parts:
        svg_parts.extend(['<g id="card-footer">', "\n".join(footer_parts), "</g>"])
    svg_parts.append("</svg>")
    svg = "\n".join(p for p in svg_parts if p != "")

    ok, problems = check_editable(svg)
    if not ok:
        raise CardError(
            "整卡结构自检失败（fail-closed）：%s" % "；".join(problems),
            hint="这是元呈内部错误，请提交输入样例以便修复。",
        )

    path = None
    if out:
        path = os.path.abspath(os.path.expanduser(str(out)))
        if os.path.isdir(path):
            path = os.path.join(path, "yotta-present-r3-%s.svg" % form)
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        _write_utf8(path, svg)

    data_uri = "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return {
        "form": form,
        "template": tpl_key,
        "sections": sections,
        "theme": theme,
        "width": CARD_WIDTH,
        "height": int(round(height)),
        "svg": svg,
        "path": path,
        "data_uri": data_uri,
        "editable": {"ok": True, "problems": []},
        "truncated": truncated,
        "brand_warnings": brand_warnings,
        "meta": {"version": VERSION, "generator": "yotta-card", "title": title, "kicker": kicker},
    }
