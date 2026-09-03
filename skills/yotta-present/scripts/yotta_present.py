#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""yotta_present.py — 元呈（yotta-present）呈现核心 + CLI。

把任意 AI 输出（JSON / Markdown / 纯文本）归一为「标准内容对象」，
再按形态体系渲染成可复制的 Markdown / 纯文本（copyable-first），
按需附本地 SVG 图（复用 yotta_chart.py 的 12 图表内核 = 「图表形态」子集）。

形态（开源基线 8 种）：
  conclusion 结论卡 / table 表格交付 / checklist 清单卡 / prose 正文 /
  metrics 指标板 / qa 问答卡 / report 报告 / chart 图表

标准内容对象 schema：
  title     标题（字符串，可选）
  headline  头条 / 一句话结论（字符串，可选）
  grade     等级徽章（success|warn|danger|info 或任意文本，可选）
  verdict   裁决 / 结论正文（字符串，可选；与 grade 搭配）
  metrics   指标块（[{label, value, unit?, tone?}, ...]）
  rows      表格（对象列表 / 二维数组 / 键值对，见 references/schema.md）
  bullets   要点（字符串数组）
  body      正文段落（字符串数组，纯文本输入自动解析）
  notes     注记 / 免责（字符串数组）
  chart_data 图表数据（{"chart"|"type", "labels", "data", ...}，可选）
  headers   显式表头（rows 为二维数组时可选）
  form      显式形态（可选，缺省自动判断）

CLI：
  python scripts/yotta_present.py [--file PATH] [--content JSON|TEXT] [--form F]
      [--title T] [--md|--text|--both|--json] [--out PATH] [--svg PATH]
      [--explain] [--list-forms] [--version]

数据不出本机：只在本机拼字符串 / SVG，不联网、不调用远程渲染服务。
"""

import argparse
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import yotta_chart as yc  # noqa: E402  （图表形态复用 12 图内核）

VERSION = "0.3.0"
TOOL_NAME = "yotta-present"
CN_NAME = "元呈·呈现"

PLATFORMS = ["webchat", "discord", "whatsapp", "plain"]
PLATFORM_DESC = {
    "webchat": "Web/TUI：完整 Markdown（标题/表格/代码块全支持）",
    "discord": "Discord：禁表格、禁大标题 → 表格转列表、标题转加粗",
    "whatsapp": "WhatsApp：禁表格、禁大标题 → 表格转列表、标题转加粗",
    "plain": "命令行/纯文本：保留分点与逻辑顺序，去 Markdown 符号",
}

# 渲染通道（R0-R3，D1/D3/D4 落地；M1 实现 R0/R1，R2/R3 收费侧后续版本）
CHANNELS = ["auto", "r0", "r1", "r2", "r3"]
CHANNEL_DESC = {
    "auto": "按 platform 自动映射：plain → r0，webchat/discord/whatsapp → r1",
    "r0": "保底通道：基础 Markdown / 纯文本，无色（无 emoji 徽章）",
    "r1": "增强通道：emoji 徽章 + 引用条 + 分隔线（假色，开源）",
    "r2": "富文本 HTML 通道（高级美化引擎，收费侧后续版本）",
    "r3": "SVG 卡片图通道（高级美化引擎，收费侧后续版本）",
}
PLATFORM_TO_CHANNEL = {"webchat": "r1", "discord": "r1", "whatsapp": "r1", "plain": "r0"}

TEMPLATES = {
    "vuln_report": {
        "title": "漏洞报告",
        "structure": [
            {"type": "heading", "level": 2, "text": "概述"},
            {"type": "summary", "source": ["verdict", "headline"]},
            {"type": "table", "source": "rows", "label": "等级与指纹"},
            {"type": "list", "source": "steps", "style": "ordered", "label": "复现步骤"},
            {"type": "codeblock", "source": "code", "lang": "http", "label": "请求样本"},
            {"type": "list", "source": "impact", "style": "bulleted", "label": "危害分析"},
            {"type": "list", "source": "fixes", "style": "ordered", "label": "修复建议"},
        ],
        "platform": {"webchat": "full", "discord": "downgrade", "whatsapp": "downgrade", "default": "full"},
    },
    "faq": {
        "title": "问答",
        "structure": [
            {"type": "summary", "source": ["headline", "verdict"]},
            {"type": "qa", "source": "rows", "label": "问答"},
        ],
        "platform": {"default": "full"},
    },
    "status": {
        "title": "状态一句话",
        "structure": [
            {"type": "plain", "source": ["headline", "verdict"]},
        ],
        "platform": {"default": "plain"},
    },
}
def _load_templates():
    """从 references/templates.json 加载模板（可热更新）；缺失/损坏回退内置。"""
    ref = os.path.join(_HERE, "..", "references", "templates.json")
    try:
        with open(ref, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data:
            return data
    except Exception:  # noqa: BLE001
        pass
    return dict(TEMPLATES)


TEMPLATES = _load_templates()

FORMS = ["conclusion", "table", "checklist", "prose", "metrics", "qa", "report", "chart"]

FORM_DESC = {
    "conclusion": "结论卡：单个结论 / 评分 / 推荐 → 徽章 + 指标 + 要点",
    "table": "表格交付：行列分明、需对比 / 罗列的数据",
    "checklist": "清单卡：事项 / 要点 / 清单",
    "prose": "正文：叙述 / 说明 / 长段落",
    "metrics": "指标板：一组关键指标",
    "qa": "问答卡：问题 / 回答成对",
    "report": "报告：多节长内容（卡片 + 表 + 文组合 + 目录）",
    "chart": "图表：数值分布 / 趋势 / 占比（本地 SVG，复用 12 图内核）",
}

# 等级徽章（元阁设计语言：🟢🟡🔴；info 用 ⚪）
GRADE_META = {
    "success": {"emoji": "🟢", "text": "通过"},
    "warn": {"emoji": "🟡", "text": "警告"},
    "danger": {"emoji": "🔴", "text": "危险"},
    "info": {"emoji": "⚪", "text": "信息"},
}

SCALAR_KEYS = ("title", "headline", "grade", "verdict")
LIST_KEYS = ("metrics", "rows", "bullets", "body", "notes", "headers")
DICT_KEYS = ("chart_data",)


class PresentError(Exception):
    """内容校验 / 渲染错误（CLI 退出码 2，MCP isError）。"""

    def __init__(self, message, hint=None):
        super().__init__(message)
        self.hint = hint


# ---------------------------------------------------------------------------
# 标准内容对象归一化
# ---------------------------------------------------------------------------

def _fmt_num(v):
    """数字显示：整数不带小数点，浮点最多两位。"""
    if isinstance(v, float):
        if v == int(v):
            return str(int(v))
        s = ("%.2f" % v).rstrip("0").rstrip(".")
        return s
    return v


def _norm_scalar_list(key, items):
    out = []
    for i, it in enumerate(items):
        if isinstance(it, (dict, list)):
            raise PresentError("%s 第 %d 项必须是字符串（当前是 %s）"
                               % (key, i + 1, type(it).__name__))
        out.append(str(it))
    return out


def _norm_metrics(items):
    out = []
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            raise PresentError("metrics 第 %d 项必须是对象 {label, value, ...}" % (i + 1))
        if "label" not in it or "value" not in it:
            raise PresentError("metrics 第 %d 项缺 label 或 value" % (i + 1))
        m = dict(it)
        m["label"] = str(m["label"])
        m["value"] = _fmt_num(m["value"]) if isinstance(m["value"], (int, float)) else str(m["value"])
        out.append(m)
    return out


def _norm_rows(items):
    out = []
    for i, it in enumerate(items):
        if isinstance(it, dict):
            out.append(dict(it))
        elif isinstance(it, list):
            out.append([_fmt_num(c) if isinstance(c, (int, float)) else str(c) for c in it])
        else:
            raise PresentError("rows 第 %d 项必须是对象或数组" % (i + 1))
    return out


def _parse_text(raw):
    """纯文本 / Markdown 输入 → 标准内容对象（title/headline/bullets/body）。"""
    data = {}
    title = None
    headline = None
    bullets = []
    body = []
    for ln in raw.splitlines():
        s = ln.rstrip()
        m = re.match(r"^\s*#\s+(.+?)\s*$", s)
        if m and title is None:
            title = m.group(1).strip()
            continue
        m = re.match(r"^\s*>\s*(.+)$", s)
        if m:
            if headline is None:
                headline = m.group(1).strip()
            else:
                bullets.append(m.group(1).strip())
            continue
        if re.match(r"^\s*[-*]\s+", s):
            bullets.append(re.sub(r"^\s*[-*]\s+", "", s))
            continue
        if re.match(r"^\s*\[[ xX]\]\s+", s):
            bullets.append(s.strip())
            continue
        if s.strip():
            body.append(s)
    if title:
        data["title"] = title
    if headline:
        data["headline"] = headline
    if bullets:
        data["bullets"] = bullets
    if body:
        data["body"] = body
    return data


def normalize_content(raw, title_override=None):
    """把输入归一化为标准内容对象 dict。

    raw 可为 dict / JSON 字符串 / 纯文本（Markdown）。
    返回 dict；非法输入抛 PresentError。
    """
    if isinstance(raw, dict):
        data = dict(raw)
    elif isinstance(raw, str):
        s = raw.strip()
        if not s:
            raise PresentError("内容为空", hint="请提供要呈现的内容：--content 内容、--file 路径，或通过 stdin 传入。")
        if s[0] in "[{":
            try:
                data = json.loads(s)
            except json.JSONDecodeError as e:
                raise PresentError("JSON 解析失败：%s" % e, hint="请检查 JSON 格式（引号、逗号、括号是否完整）；可先用 JSON 校验工具验证。")
            if not isinstance(data, dict):
                raise PresentError("JSON 顶层必须是对象（标准内容对象）", hint="请传 {title, bullets, metrics, rows, ...} 标准内容对象，或直接传一段 Markdown/纯文本让元呈自动美化。")
        else:
            data = _parse_text(raw)
    else:
        raise PresentError("不支持的输入类型：%s" % type(raw).__name__, hint="请传 JSON 字符串、Markdown 文本、纯文本或文件路径。")

    if title_override is not None:
        data["title"] = str(title_override)

    for k in SCALAR_KEYS:
        if k in data and data[k] is not None and not isinstance(data[k], str):
            data[k] = str(data[k])
    for k in LIST_KEYS:
        if k not in data or data[k] is None:
            continue
        if not isinstance(data[k], list):
            raise PresentError("%s 必须是数组" % k, hint="该字段应为数组（列表），例如 [a, b]；请检查数据类型。")
        if k == "metrics":
            data[k] = _norm_metrics(data[k])
        elif k == "rows":
            data[k] = _norm_rows(data[k])
        else:
            data[k] = _norm_scalar_list(k, data[k])
    if data.get("chart_data") is not None and not isinstance(data.get("chart_data"), dict):
        raise PresentError("chart_data 必须是对象", hint="请传图表数据对象，如 {chart: bar, labels: [...], data: [...]}；或去掉 chart_data 用其它形态。")
    return data


# ---------------------------------------------------------------------------
# 确定性判断兜底：内容形状 → 形态（可解释）
# ---------------------------------------------------------------------------

def _row_keys(rows):
    """对象表行：键并集（按首现顺序）。"""
    keys = []
    for r in rows:
        if isinstance(r, dict):
            for k in r:
                if k not in keys:
                    keys.append(k)
    return keys


def _row_cells(row):
    if isinstance(row, dict):
        return list(row.values())
    return list(row)


def _rows_cols(rows):
    """表格列数（对象表取键并集长度，二维表取最长行）。"""
    if rows and isinstance(rows[0], dict):
        return len(_row_keys(rows))
    return max((len(r) for r in rows), default=0)


def _looks_qa_rows(rows, headers=None):
    if headers:
        hh = [str(h).strip().lower() for h in headers]
        if any(h in ("问题", "question", "q") for h in hh) and any(h in ("回答", "答案", "answer", "a") for h in hh):
            return True
    if rows and isinstance(rows[0], dict):
        keys = [str(k).lower() for k in _row_keys(rows)]
        qhit = any(k in ("问题", "question", "q") for k in keys)
        ahit = any(k in ("回答", "答案", "answer", "a") for k in keys)
        if qhit and ahit:
            return True
    return False


def _looks_qa_bullets(bullets):
    n = 0
    for b in bullets:
        s = str(b).strip()
        if re.match(r"^(问|答|q|a)\s*[:：]", s, re.I):
            n += 1
    return n >= 2


def decide_form(content):
    """确定性判断兜底：按内容形状选形态，返回 (form, reasons)。"""
    f = content.get("form")
    if f:
        f = str(f).strip().lower()
        if f not in FORMS:
            raise PresentError("未知形态：%s（可选：%s）" % (f, ", ".join(FORMS)), hint="请从可选形态中选择，或去掉 --form 让元呈自动判断。")
        return f, ["用户显式指定 form=%s" % f]

    if content.get("chart_data"):
        return "chart", ["chart_data 存在 → 图表形态（本地 SVG，复用 12 图内核）"]

    rows = content.get("rows")
    if rows:
        if _looks_qa_rows(rows, content.get("headers")):
            return "qa", ["rows 呈现『问题 / 回答』两列 → 问答卡"]
        if content.get("title") and (
                content.get("metrics") or content.get("bullets")
                or content.get("verdict") or content.get("headline") or content.get("body")):
            return "report", ["标题 + 表格 + 其他内容段 → 多节报告"]
        return "table", ["rows 为行列分明的表格数据 → 表格交付"]

    metrics = content.get("metrics")
    if metrics:
        if content.get("verdict") or content.get("grade") or content.get("headline"):
            return "conclusion", ["指标 + 结论 / 头条 → 结论卡"]
        if len(metrics) >= 2:
            return "metrics", ["仅指标（>=2 项）→ 指标板"]
        return "conclusion", ["单指标 + 其余要点 → 结论卡"]

    bullets = content.get("bullets")
    if bullets:
        if _looks_qa_bullets(bullets):
            return "qa", ["要点成对出现『问 / 答』→ 问答卡"]
        if content.get("verdict") or content.get("grade") or content.get("headline"):
            return "conclusion", ["要点 + 结论 / 头条 → 结论卡"]
        if content.get("body"):
            return "prose", ["含正文段落 → 正文"]
        return "checklist", ["仅要点 → 清单卡"]

    if content.get("verdict") or content.get("grade"):
        return "conclusion", ["存在结论 / 裁决 → 结论卡"]

    if content.get("body"):
        return "prose", ["叙述性内容 / 正文段落 → 正文"]

    if content.get("headline") or content.get("title"):
        return "prose", ["仅标题 / 头条 → 正文"]

    return "prose", ["兜底：任何输出至少套『正文』美化，不让内容裸奔"]



def _collect_warnings(content, form):
    """收集常见错用提示（不阻断渲染，只提醒；CLI 打 stderr / MCP 附 warnings 字段）。"""
    warnings = []
    if "columns" in content:
        warnings.append(
            "table 不支持 columns 字段（已忽略）；列名请用 rows 对象列表的键，或二维数组 + headers。"
        )
    if form == "conclusion":
        if not (content.get("grade") or content.get("verdict")):
            warnings.append(
                "conclusion 建议传 JSON：{title, grade, verdict, bullets}；当前输入（如 Markdown）无 grade / verdict，渲染无徽章 / 裁决结构。"
            )
    if form == "qa":
        rows = content.get("rows")
        if rows and not _looks_qa_rows(rows, content.get("headers")):
            warnings.append(
                "qa 的 rows 须为『问题 / 回答』两列（键命中 问题/question/q + 回答/answer/a），否则会判为 table。"
            )
    return warnings


# ---------------------------------------------------------------------------
# Markdown / 纯文本 渲染原语
# ---------------------------------------------------------------------------


def _esc_md_cell(v):
    """表格单元格转义：竖线转义、换行转 <br>。"""
    s = str(v)
    return s.replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")


def _h(level, text, platform="webchat"):
    """标题渲染：webchat 完整 Markdown；discord/whatsapp 转加粗；plain 去符号。"""
    if platform in ("discord", "whatsapp"):
        return "**%s**" % text
    if platform == "plain":
        return text
    return "%s %s" % ("#" * level, text)


def _quote(text, platform="webchat"):
    """引用块渲染：webchat 保留 >；discord/whatsapp 转加粗；plain 去符号。"""
    if platform in ("discord", "whatsapp"):
        return "**%s**" % text
    if platform == "plain":
        return text
    return "> %s" % text


def _bold(text, platform="webchat"):
    """加粗渲染：plain 去符号，其余保留 **。"""
    if platform == "plain":
        return str(text)
    return "**%s**" % text


def _maybe_bold(key, value, content, platform="webchat"):
    """bold_keys：命中字段的值自动加粗（plain 不加）。"""
    if value is None:
        return ""
    if platform == "plain":
        return str(value)
    if key in (content.get("bold_keys") or []):
        return "**%s**" % value
    return str(value)


def _md_table(headers, rows, platform="webchat"):
    """表格渲染：webchat Markdown 表格；discord/whatsapp 降级为列表；plain 文本表格。"""
    if platform in ("discord", "whatsapp"):
        out = []
        if headers:
            out.append("- %s" % " · ".join(_esc_md_cell(h) for h in headers))
        for row in rows:
            cells = [_esc_md_cell(c) for c in row]
            out.append("- %s" % " · ".join(cells))
        return "\n".join(out)
    if platform == "plain":
        out = []
        if headers:
            out.append("- %s" % " · ".join(str(h) for h in headers))
        for row in rows:
            out.append("- %s" % " · ".join(str(c) for c in row))
        return "\n".join(out)
    out = ["| %s |" % " | ".join(_esc_md_cell(h) for h in headers),
           "| %s |" % " | ".join(["---"] * len(headers))]
    for row in rows:
        cells = [_esc_md_cell(c) for c in row]
        while len(cells) < len(headers):
            cells.append("")
        out.append("| %s |" % " | ".join(cells[:len(headers)]))
    return "\n".join(out)


def _text_table(headers, rows):
    lines = []
    if headers:
        lines.append(" | ".join(str(h) for h in headers))
    for row in rows:
        lines.append(" | ".join(str(c) for c in row))
    return "\n".join(lines)


def _md_bullets(bullets, platform="webchat"):
    out = []
    for b in bullets:
        s = str(b)
        if re.match(r"^\s*[-*]\s", s) or re.match(r"^\s*\[[ xX]\]\s", s):
            out.append(s.strip())
        elif platform == "plain":
            out.append("• %s" % s)
        else:
            out.append("- %s" % s)
    return "\n".join(out)


def _text_bullets(bullets):
    return "\n".join(str(b) for b in bullets)


def _md_body(body):
    return "\n\n".join(str(b) for b in body)


def _md_notes(notes, platform="webchat"):
    if platform in ("discord", "whatsapp"):
        return "\n".join("**注：%s**" % n for n in notes)
    if platform == "plain":
        return "\n".join("注：%s" % n for n in notes)
    return "\n".join("> 注：%s" % n for n in notes)


def _text_notes(notes):
    return "\n".join("注：%s" % n for n in notes)


def _grade_badge(grade):
    """返回 (emoji 或 None, 文案)。"""
    if not grade:
        return (None, None)
    g = str(grade).strip().lower()
    meta = GRADE_META.get(g)
    if meta:
        return (meta["emoji"], meta["text"])
    return (None, str(grade))


def _resolve_channel(platform, channel):
    """channel×platform 映射（D4）：auto 按 platform 保守落 r0/r1；r2/r3 当前未开放。"""
    if channel in (None, "", "auto"):
        return PLATFORM_TO_CHANNEL.get(platform, "r1")
    ch = str(channel).strip().lower()
    if ch not in CHANNELS:
        raise PresentError("未知通道：%s（可选：%s）" % (ch, ", ".join(CHANNELS)),
                           hint="channel 是载体族（auto/r0/r1/r2/r3）；一般用默认 auto，由 platform 自动映射即可。")
    if ch in ("r2", "r3"):
        raise PresentError("通道 %s 尚未开放：%s（属高级美化引擎，收费侧后续版本）" % (ch, CHANNEL_DESC[ch]),
                           hint="当前版本提供 R0（保底无色）/ R1（emoji 增强）两条开源通道；R2/R3 是富文本 HTML / SVG 整卡通道，计划在后续版本推出。")
    return ch


def _grade_chip_md(content, platform, channel):
    """grade 徽章行内片段：r1 = emoji + 文案；r0 = 仅文案（无色）。无 grade → 空串。"""
    badge = _grade_badge(content.get("grade"))
    if not badge or not badge[1]:
        return ""
    if channel == "r0" or not badge[0]:
        return _bold(badge[1], platform)
    return "%s %s" % (badge[0], _bold(badge[1], platform))


def _summary_parts(content, platform, channel):
    """统一摘要条部件：grade chip + verdict + headline（按通道控 emoji）。"""
    parts = []
    chip = _grade_chip_md(content, platform, channel)
    if chip:
        parts.append(chip)
    verdict = content.get("verdict")
    if verdict:
        parts.append(_maybe_bold("verdict", verdict, content, platform))
    headline = content.get("headline")
    if headline and headline != verdict:
        parts.append(_maybe_bold("headline", headline, content, platform))
    return parts


def _summary_bar_md(content, platform, channel):
    """统一引用条（R1 规范）：grade chip + verdict + headline 合成一条 blockquote；无内容返回 None。"""
    parts = _summary_parts(content, platform, channel)
    if not parts:
        return None
    return _quote(" — ".join(parts), platform)


def _metrics_rows(metrics):
    rows = []
    for m in metrics:
        label = m.get("label", "")
        value = str(m.get("value", ""))
        unit = str(m.get("unit", "")).strip()
        tone = str(m.get("tone", "")).strip().lower()
        arrow = {"up": "▲", "down": "▼", "neutral": "—"}.get(tone, "")
        cell = value
        if unit:
            cell = "%s %s" % (cell, unit)
        if arrow:
            cell = "%s %s" % (arrow, cell)
        rows.append([label, cell])
    return rows


# ---------------------------------------------------------------------------
# 各形态渲染
# ---------------------------------------------------------------------------

def _render_conclusion_md(c, platform="webchat", channel="r1"):
    sec = []
    if c.get("title"):
        sec.append(_h(1, _maybe_bold("title", c["title"], c, platform), platform))
    bar = _summary_bar_md(c, platform, channel)
    if bar:
        sec.append(bar)
    if c.get("metrics"):
        sec.append(_bold("关键指标", platform))
        sec.append(_md_table(["指标", "数值"], _metrics_rows(c["metrics"]), platform))
    if c.get("bullets"):
        sec.append(_bold("要点", platform))
        sec.append(_md_bullets(c["bullets"], platform))
    if c.get("body"):
        sec.append(_bold("说明", platform))
        sec.append(_md_body(c["body"]))
    if c.get("notes"):
        sec.append("---")
        sec.append(_md_notes(c["notes"], platform))
    return "\n\n".join(sec)


def _render_conclusion_text(c):
    sec = []
    if c.get("title"):
        sec.append(c["title"])
    badge = _grade_badge(c.get("grade"))
    verdict = c.get("verdict")
    headline = c.get("headline")
    parts = []
    if badge and badge[1]:
        parts.append("[%s]" % badge[1])
    if verdict:
        parts.append(verdict)
    if headline and headline != verdict:
        parts.append(headline)
    if parts:
        sec.append(" ".join(parts))
    elif headline:
        sec.append(headline)
    if c.get("metrics"):
        sec.append("关键指标")
        sec.append(_text_table(["指标", "数值"], _metrics_rows(c["metrics"])))
    if c.get("bullets"):
        sec.append("要点")
        sec.append(_text_bullets(c["bullets"]))
    if c.get("body"):
        sec.append("说明")
        sec.append(_md_body(c["body"]))
    if c.get("notes"):
        sec.append("")
        sec.append(_text_notes(c["notes"]))
    return "\n\n".join(sec)


def _table_parts(c):
    """解析 rows → (headers, data)；供表格形态与报告『明细』共用。"""
    rows = c["rows"]
    headers = c.get("headers")
    if headers is None:
        if rows and isinstance(rows[0], dict):
            keys = _row_keys(rows)
            if set(keys) <= {"header", "value"} and len(keys) == 2:
                headers = ["项", "值"]
            else:
                headers = keys
            data = [[r.get(k, "") for k in headers] for r in rows]
        else:
            # 二维数组：首行全为字符串且 >=2 行 → 视为表头
            if (len(rows) >= 2 and rows[0] and all(isinstance(x, str) for x in rows[0])):
                headers = [str(x) for x in rows[0]]
                data = rows[1:]
            elif rows and len(rows[0]) == 2:
                headers = ["项", "值"]
                data = rows
            else:
                headers = ["列 %d" % (i + 1) for i in range(_rows_cols(rows))]
                data = rows
    else:
        headers = [str(h) for h in headers]
        data = [_row_cells(r) for r in rows]
    return headers, data


def _render_table_md(c, platform="webchat", channel="r1"):
    sec = []
    if c.get("title"):
        sec.append(_h(1, _maybe_bold("title", c["title"], c, platform), platform))
    bar = _summary_bar_md(c, platform, channel)
    if bar:
        sec.append(bar)
    headers, data = _table_parts(c)
    sec.append(_md_table(headers, data, platform))
    if c.get("notes"):
        sec.append("---")
        sec.append(_md_notes(c["notes"], platform))
    return "\n\n".join(sec)


def _render_table_text(c):
    sec = []
    if c.get("title"):
        sec.append(c["title"])
    headers, data = _table_parts(c)
    sec.append(_text_table(headers, data))
    if c.get("notes"):
        sec.append(_text_notes(c["notes"]))
    return "\n\n".join(sec)


def _render_checklist_md(c, platform="webchat", channel="r1"):
    sec = []
    if c.get("title"):
        sec.append(_h(1, _maybe_bold("title", c["title"], c, platform), platform))
    bar = _summary_bar_md(c, platform, channel)
    if bar:
        sec.append(bar)
    if c.get("bullets"):
        sec.append(_md_bullets(c["bullets"], platform))
    if c.get("notes"):
        sec.append("---")
        sec.append(_md_notes(c["notes"], platform))
    return "\n\n".join(sec)


def _render_checklist_text(c):
    sec = []
    if c.get("title"):
        sec.append(c["title"])
    if c.get("headline"):
        sec.append(c["headline"])
    if c.get("bullets"):
        sec.append(_text_bullets(c["bullets"]))
    if c.get("notes"):
        sec.append("")
        sec.append(_text_notes(c["notes"]))
    return "\n\n".join(sec)


def _render_prose_md(c, platform="webchat", channel="r1"):
    sec = []
    if c.get("title"):
        sec.append(_h(1, _maybe_bold("title", c["title"], c, platform), platform))
    bar = _summary_bar_md(c, platform, channel)
    if bar:
        sec.append(bar)
    if c.get("body"):
        sec.append(_md_body(c["body"]))
    if c.get("bullets"):
        sec.append(_bold("要点", platform))
        sec.append(_md_bullets(c["bullets"], platform))
    if c.get("notes"):
        sec.append("---")
        sec.append(_md_notes(c["notes"], platform))
    return "\n\n".join(sec)


def _render_prose_text(c):
    sec = []
    if c.get("title"):
        sec.append(c["title"])
    if c.get("headline"):
        sec.append(c["headline"])
    if c.get("body"):
        sec.append(_md_body(c["body"]))
    if c.get("bullets"):
        sec.append("要点")
        sec.append(_text_bullets(c["bullets"]))
    if c.get("notes"):
        sec.append("")
        sec.append(_text_notes(c["notes"]))
    return "\n\n".join(sec)


def _render_metrics_md(c, platform="webchat", channel="r1"):
    sec = []
    if c.get("title"):
        sec.append(_h(1, _maybe_bold("title", c["title"], c, platform), platform))
    bar = _summary_bar_md(c, platform, channel)
    if bar:
        sec.append(bar)
    sec.append(_bold("关键指标", platform))
    sec.append(_md_table(["指标", "数值"], _metrics_rows(c["metrics"]), platform))
    if c.get("notes"):
        sec.append("---")
        sec.append(_md_notes(c["notes"], platform))
    return "\n\n".join(sec)


def _render_metrics_text(c):
    sec = []
    if c.get("title"):
        sec.append(c["title"])
    sec.append("关键指标")
    sec.append(_text_table(["指标", "数值"], _metrics_rows(c["metrics"])))
    if c.get("headline"):
        sec.append(c["headline"])
    if c.get("notes"):
        sec.append("")
        sec.append(_text_notes(c["notes"]))
    return "\n\n".join(sec)


def _parse_qa(content):
    """解析问答对列表 [(问, 答), ...]。"""
    pairs = []
    rows = content.get("rows")
    if rows:
        if rows and isinstance(rows[0], dict):
            keys = _row_keys(rows)
            if set(keys) <= {"header", "value"} and len(keys) == 2:
                for r in rows:
                    pairs.append((str(r.get("header", "")), str(r.get("value", ""))))
            else:
                qkey = akey = None
                for k in keys:
                    kl = str(k).lower()
                    if qkey is None and kl in ("问题", "question", "q"):
                        qkey = k
                    if akey is None and kl in ("回答", "答案", "answer", "a"):
                        akey = k
                if qkey and akey:
                    for r in rows:
                        pairs.append((str(r.get(qkey, "")), str(r.get(akey, ""))))
                else:
                    for r in rows:
                        cells = _row_cells(r)
                        if len(cells) >= 2:
                            pairs.append((str(cells[0]), str(cells[1])))
        else:
            for r in rows:
                cells = _row_cells(r)
                if len(cells) >= 2:
                    pairs.append((str(cells[0]), str(cells[1])))
    elif content.get("bullets"):
        pairs = _pairs_from_bullets(content["bullets"])
    return pairs


def _pairs_from_bullets(bullets):
    pairs = []
    cur_q = None
    cur_a = None
    for b in bullets:
        s = str(b).strip()
        m = re.match(r"^(?:问|q|question)\s*[:：]\s*(.+)$", s, re.I)
        if m:
            if cur_q is not None:
                pairs.append((cur_q, cur_a or ""))
            cur_q = m.group(1).strip()
            cur_a = None
            continue
        m = re.match(r"^(?:答|a|answer)\s*[:：]\s*(.+)$", s, re.I)
        if m:
            cur_a = m.group(1).strip()
            continue
        if cur_q is not None and cur_a is None:
            cur_a = s
        elif cur_q is not None:
            pairs.append((cur_q, cur_a or ""))
            cur_q = s
            cur_a = None
        else:
            cur_q = s
    if cur_q is not None:
        pairs.append((cur_q, cur_a or ""))
    return pairs


def _render_qa_md(c, platform="webchat", channel="r1"):
    sec = []
    if c.get("title"):
        sec.append(_h(1, _maybe_bold("title", c["title"], c, platform), platform))
    bar = _summary_bar_md(c, platform, channel)
    if bar:
        sec.append(bar)
    for q, a in _parse_qa(c):
        sec.append(_bold("问：%s" % q, platform))
        sec.append("答：%s" % a)
    if c.get("notes"):
        sec.append("---")
        sec.append(_md_notes(c["notes"], platform))
    return "\n\n".join(sec)


def _render_qa_text(c):
    sec = []
    if c.get("title"):
        sec.append(c["title"])
    for q, a in _parse_qa(c):
        sec.append("问：%s" % q)
        sec.append("答：%s" % a)
    if c.get("notes"):
        sec.append("")
        sec.append(_text_notes(c["notes"]))
    return "\n\n".join(sec)


def _report_sections(c):
    """报告章节列表 [(标题, 是否存在), ...]。"""
    return [
        ("摘要", bool(c.get("verdict") or c.get("headline") or c.get("body"))),
        ("关键指标", bool(c.get("metrics"))),
        ("明细", bool(c.get("rows"))),
        ("要点", bool(c.get("bullets"))),
        ("注记", bool(c.get("notes"))),
    ]


def _render_report_md(c, platform="webchat", channel="r1"):
    sec = []
    if c.get("title"):
        sec.append(_h(1, _maybe_bold("title", c["title"], c, platform), platform))
    # 顶部引用条：report 的 grade/verdict 在「摘要」节呈现，顶部仅无 grade/verdict 时给 headline，避免重复
    if c.get("headline") and not (c.get("grade") or c.get("verdict")):
        sec.append(_quote(_maybe_bold("headline", c["headline"], c, platform), platform))
    sections = [t for t, on in _report_sections(c) if on]
    if sections:
        sec.append(_bold("目录", platform))
        sec.append("\n".join("- %s" % t for t in sections))
    badge = _grade_badge(c.get("grade"))
    for t, on in _report_sections(c):
        if not on:
            continue
        sec.append(_h(2, t, platform))
        if t == "摘要":
            parts = []
            if badge and badge[1]:
                if channel == "r0" or not badge[0]:
                    parts.append(_bold(badge[1], platform))
                else:
                    parts.append("%s %s" % (badge[0], _bold(badge[1], platform)))
            if c.get("verdict"):
                parts.append(_maybe_bold("verdict", c["verdict"], c, platform))
            if parts:
                sec.append(" ".join(parts))
            if c.get("headline") and c.get("headline") != c.get("verdict"):
                sec.append(_maybe_bold("headline", c["headline"], c, platform))
            if c.get("body"):
                sec.append(_md_body(c["body"]))
        elif t == "关键指标":
            sec.append(_md_table(["指标", "数值"], _metrics_rows(c["metrics"]), platform))
        elif t == "明细":
            headers, data = _table_parts(c)
            sec.append(_md_table(headers, data, platform))
        elif t == "要点":
            sec.append(_md_bullets(c["bullets"], platform))
        elif t == "注记":
            sec.append(_md_notes(c["notes"], platform))
    return "\n\n".join(sec)


def _render_report_text(c):
    sec = []
    if c.get("title"):
        sec.append(c["title"])
    if c.get("headline"):
        sec.append(c["headline"])
    badge = _grade_badge(c.get("grade"))
    for t, on in _report_sections(c):
        if not on:
            continue
        sec.append("== %s ==" % t)
        if t == "摘要":
            parts = []
            if badge and badge[1]:
                parts.append("[%s]" % badge[1])
            if c.get("verdict"):
                parts.append(c["verdict"])
            if parts:
                sec.append(" ".join(parts))
            if c.get("headline") and c.get("headline") != c.get("verdict"):
                sec.append(c["headline"])
            if c.get("body"):
                sec.append(_md_body(c["body"]))
        elif t == "关键指标":
            sec.append(_text_table(["指标", "数值"], _metrics_rows(c["metrics"])))
        elif t == "明细":
            headers, data = _table_parts(c)
            sec.append(_text_table(headers, data))
        elif t == "要点":
            sec.append(_text_bullets(c["bullets"]))
        elif t == "注记":
            sec.append(_text_notes(c["notes"]))
    return "\n\n".join(sec)


def _chart_ref(chart, prefer_path=False):
    """Markdown 图片引用：有本地路径且允许时用相对路径，否则用 data URI（自包含可复制）。"""
    if prefer_path and chart.get("path"):
        p = chart["path"]
        try:
            rel = os.path.relpath(p, os.getcwd())
            if not rel.startswith(".."):
                return rel.replace("\\", "/")
        except ValueError:
            pass
        return p
    return chart.get("data_uri") or ""


def _render_chart_md(c, chart, prefer_path=False, platform="webchat"):
    sec = []
    if c.get("title"):
        sec.append(_h(1, _maybe_bold("title", c["title"], c, platform), platform))
    ctitle = chart.get("title") or c.get("title") or chart.get("chart")
    if platform == "plain":
        sec.append("图表（%s）：data URI 内嵌于 Markdown 输出" % chart["chart"])
    else:
        sec.append("![%s](%s)" % (ctitle, _chart_ref(chart, prefer_path)))
    if c.get("headline"):
        sec.append(_quote(_maybe_bold("headline", c["headline"], c, platform), platform))
    if c.get("notes"):
        sec.append("---")
        sec.append(_md_notes(c["notes"], platform))
    return "\n\n".join(sec)


def _render_chart_text(c, chart):
    sec = []
    if c.get("title"):
        sec.append(c["title"])
    if chart.get("path"):
        sec.append("图表（%s）已生成：%s" % (chart["chart"], chart["path"]))
    else:
        sec.append("图表（%s）：data URI 内嵌于 Markdown 输出" % chart["chart"])
    if c.get("headline"):
        sec.append(c["headline"])
    if c.get("notes"):
        sec.append("")
        sec.append(_text_notes(c["notes"]))
    return "\n\n".join(sec)


# ---------------------------------------------------------------------------
# 命名场景模板（声明式 structure 骨架 + 平台策略）
# ---------------------------------------------------------------------------

def _tpl_source(content, source):
    """取模板块的 source 数据：字段名（或字段名数组，取第一个非空）。"""
    if isinstance(source, (list, tuple)):
        for k in source:
            if content.get(k):
                return content.get(k)
        return None
    return content.get(source)


def _render_template_md(key, content, platform="webchat", channel="r1"):
    """按模板 structure 渲染 Markdown（缺 source 的块跳过）。"""
    tpl = TEMPLATES.get(key)
    if not tpl:
        raise PresentError("未知模板：%s（可选：%s）" % (key, ", ".join(sorted(TEMPLATES))), hint="请从可选模板中选择，或改用 --form 直接指定形态。")
    sec = []
    if content.get("title"):
        sec.append(_h(1, _maybe_bold("title", content["title"], content, platform), platform))
    for block in tpl["structure"]:
        btype = block.get("type")
        src = block.get("source")
        label = block.get("label") or ""
        if btype == "heading":
            sec.append(_h(block.get("level", 2), block.get("text") or block.get("label") or "", platform))
        elif btype == "summary":
            val = _tpl_source(content, src) or content.get("verdict") or content.get("headline")
            if val:
                parts = []
                badge = _grade_badge(content.get("grade"))
                if badge and badge[1]:
                    if channel == "r0" or not badge[0]:
                        parts.append(_bold(badge[1], platform))
                    else:
                        parts.append("%s %s" % (badge[0], _bold(badge[1], platform)))
                parts.append(_maybe_bold(str(src[0] if isinstance(src, (list, tuple)) else src), val, content, platform))
                sec.append(_quote(" — ".join(parts), platform))
        elif btype == "table":
            rows = content.get("rows")
            if rows:
                if label:
                    sec.append(_bold(label, platform))
                headers, data = _table_parts(content)
                sec.append(_md_table(headers, data, platform))
        elif btype == "list":
            items = _tpl_source(content, src)
            if items:
                if label:
                    sec.append(_bold(label, platform))
                if block.get("style") == "ordered":
                    sec.append("\n".join("%d. %s" % (i + 1, it) for i, it in enumerate(items)))
                else:
                    sec.append(_md_bullets(items, platform))
        elif btype == "codeblock":
            code = content.get("code")
            if code:
                if label:
                    sec.append(_bold(label, platform))
                lang = block.get("lang", "")
                sec.append("```%s\n%s\n```" % (lang, code))
        elif btype == "qa":
            pairs = _parse_qa(content)
            if pairs:
                if label:
                    sec.append(_bold(label, platform))
                for q, a in pairs:
                    sec.append(_bold("问：%s" % q, platform))
                    sec.append("答：%s" % a)
        elif btype == "plain":
            val = _tpl_source(content, src)
            if val:
                sec.append(str(val))
    return "\n\n".join(sec)


def _render_template_text(key, content):
    """模板纯文本渲染（无 Markdown 符号）。"""
    tpl = TEMPLATES.get(key)
    if not tpl:
        raise PresentError("未知模板：%s（可选：%s）" % (key, ", ".join(sorted(TEMPLATES))), hint="请从可选模板中选择，或改用 --form 直接指定形态。")
    sec = []
    if content.get("title"):
        sec.append(content["title"])
    for block in tpl["structure"]:
        btype = block.get("type")
        src = block.get("source")
        label = block.get("label") or ""
        if btype == "heading":
            sec.append(label)
        elif btype == "summary":
            val = _tpl_source(content, src) or content.get("verdict") or content.get("headline")
            if val:
                sec.append(str(val))
        elif btype == "table":
            rows = content.get("rows")
            if rows:
                if label:
                    sec.append(label)
                headers, data = _table_parts(content)
                sec.append(_text_table(headers, data))
        elif btype == "list":
            items = _tpl_source(content, src)
            if items:
                if label:
                    sec.append(label)
                if block.get("style") == "ordered":
                    sec.append("\n".join("%d. %s" % (i + 1, it) for i, it in enumerate(items)))
                else:
                    sec.append(_text_bullets(items))
        elif btype == "codeblock":
            code = content.get("code")
            if code:
                if label:
                    sec.append(label)
                sec.append(str(code))
        elif btype == "qa":
            pairs = _parse_qa(content)
            if pairs:
                if label:
                    sec.append(label)
                for q, a in pairs:
                    sec.append("问：%s" % q)
                    sec.append("答：%s" % a)
        elif btype == "plain":
            val = _tpl_source(content, src)
            if val:
                sec.append(str(val))
    return "\n\n".join(sec)


# ---------------------------------------------------------------------------
# 长度熔断（max_len）：先压缩列表、再降标题层级、最后硬截断，保留结论
# ---------------------------------------------------------------------------

def _enforce_max_len(text, max_len):
    """max_len 熔断：压缩列表 → 降标题 → 硬截断；保留开头结论。"""
    if max_len is None or len(text) <= max_len:
        return text
    lines = text.split("\n")
    # pass 1: 压缩列表（每个连续列表段保留首项 + 省略号）
    out = []
    i = 0
    while i < len(lines):
        if re.match(r"^\s*(?:[-*•]|\d+\.)\s", lines[i]):
            j = i
            while j < len(lines) and re.match(r"^\s*(?:[-*•]|\d+\.)\s", lines[j]):
                j += 1
            out.append(lines[i])
            if j - i > 1:
                marker = lines[i][:1] if lines[i][:1] in "-*•" else "-"
                out.append("%s …（其余已折叠）" % marker)
            i = j
        else:
            out.append(lines[i])
            i += 1
    text = "\n".join(out)
    if len(text) <= max_len:
        return text
    # pass 2: 降标题层级（## → ** 或去符号）
    lines = text.split("\n")
    out = []
    for ln in lines:
        m = re.match(r"^#{1,6}\s+(.+)$", ln)
        if m:
            out.append("**%s**" % m.group(1).strip())
        else:
            out.append(ln)
    text = "\n".join(out)
    if len(text) <= max_len:
        return text
    # pass 3: 硬截断，保留开头结论
    return text[: max(1, max_len - 1)] + "…"


def _resolve_test_python():
    """测试用 Python 解释器解析：只接受绝对路径且 basename 以 python 开头的
    YOTTA_TEST_PYTHON 覆盖，否则回退 sys.executable（TT2 安全修复）。"""
    env = os.environ.get("YOTTA_TEST_PYTHON")
    if env:
        p = os.path.abspath(env)
        base = os.path.basename(p).lower()
        if os.path.isfile(p) and base.startswith("python"):
            return p
    return sys.executable


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------

def _render_chart(cd, svg_out=None):
    """渲染图表（复用 yotta_chart 内核），返回 meta dict。"""
    cd = cd or {}
    params = dict(cd)
    ctype = params.pop("chart", None) or params.pop("type", None) or "bar"
    if svg_out:
        params["out"] = svg_out
    try:
        r = yc.render(str(ctype), params)
    except Exception as e:  # noqa: BLE001
        raise PresentError("图表渲染失败：%s" % e, hint="请检查 chart_data 的 chart 类型与数据是否完整（labels/data 长度一致）。")
    return {
        "chart": r.get("chart") or str(ctype),
        "title": cd.get("title") or "",
        "width": r.get("width"),
        "height": r.get("height"),
        "path": r.get("path"),
        "data_uri": r.get("data_uri"),
    }


def present(raw, form=None, title=None, svg_out=None, explain=False,
            platform="webchat", channel="auto", template=None, max_len=None):
    """呈现核心入口。

    raw: dict / JSON 字符串 / 纯文本
    form: 显式形态（可选）
    title: 标题覆盖（可选）
    svg_out: 图表形态的本地 SVG 输出路径（可选）
    explain: 附判断说明（可选）
    platform: 平台自适应（webchat/discord/whatsapp/plain，默认 webchat）
    channel: 渲染通道（auto/r0/r1/r2/r3，默认 auto 按 platform 自动映射：
             plain → r0 保底无色，webchat/discord/whatsapp → r1 emoji 增强；
             r2/r3 高级美化通道当前未开放）
    template: 命名场景模板 key（vuln_report/faq/status，可选；优先于 form）
    max_len: 长度熔断上限（字符数，可选）
    返回: {form, channel, markdown, text, explain?, chart?, warnings?}
    """
    if platform not in PLATFORMS:
        raise PresentError("未知平台：%s（可选：%s）" % (platform, ", ".join(PLATFORMS)), hint="请从可选平台中选择：webchat / discord / whatsapp / plain。")
    eff_channel = _resolve_channel(platform, channel)
    content = normalize_content(raw, title_override=title)
    if template is not None:
        tpl_key = str(template).strip().lower()
        if tpl_key not in TEMPLATES:
            raise PresentError("未知模板：%s（可选：%s）" % (tpl_key, ", ".join(sorted(TEMPLATES))), hint="请从可选模板中选择，或改用 --form 直接指定形态。")
        f = tpl_key
        reasons = ["用户显式指定 template=%s" % tpl_key]
        md = _render_template_md(tpl_key, content, platform=platform, channel=eff_channel)
        text = _render_template_text(tpl_key, content)
        result = {"form": f, "markdown": md, "text": text}
    else:
        if form is not None:
            f = str(form).strip().lower()
            if f not in FORMS:
                raise PresentError("未知形态：%s（可选：%s）" % (f, ", ".join(FORMS)), hint="请从可选形态中选择，或去掉 --form 让元呈自动判断。")
            reasons = ["用户显式指定 form=%s" % f]
        else:
            f, reasons = decide_form(content)

        if f == "chart":
            if not content.get("chart_data"):
                raise PresentError("形态 chart 需要 chart_data 字段", hint="请传 chart_data（如 {chart: pie, labels: [...], data: [...]}），或用 --form 指定其它形态。")
            chart = _render_chart(content["chart_data"], svg_out=svg_out)
            md = _render_chart_md(content, chart, prefer_path=bool(svg_out), platform=platform)
            text = _render_chart_text(content, chart)
            result = {"form": f, "markdown": md, "text": text, "chart": chart}
        elif f == "conclusion":
            result = {"form": f, "markdown": _render_conclusion_md(content, platform, channel=eff_channel),
                      "text": _render_conclusion_text(content)}
        elif f == "table":
            result = {"form": f, "markdown": _render_table_md(content, platform, channel=eff_channel),
                      "text": _render_table_text(content)}
        elif f == "checklist":
            result = {"form": f, "markdown": _render_checklist_md(content, platform, channel=eff_channel),
                      "text": _render_checklist_text(content)}
        elif f == "prose":
            result = {"form": f, "markdown": _render_prose_md(content, platform, channel=eff_channel),
                      "text": _render_prose_text(content)}
        elif f == "metrics":
            result = {"form": f, "markdown": _render_metrics_md(content, platform, channel=eff_channel),
                      "text": _render_metrics_text(content)}
        elif f == "qa":
            result = {"form": f, "markdown": _render_qa_md(content, platform, channel=eff_channel),
                      "text": _render_qa_text(content)}
        elif f == "report":
            result = {"form": f, "markdown": _render_report_md(content, platform, channel=eff_channel),
                      "text": _render_report_text(content)}
        else:
            raise PresentError("未实现的形态：%s" % f, hint="该形态当前不可用，请从可选形态中选择。")

    result["channel"] = eff_channel
    if max_len is not None:
        try:
            ml = int(max_len)
        except (TypeError, ValueError):
            raise PresentError("max_len 必须是正整数（当前：%s）" % max_len, hint="max_len 是输出长度上限（字符数），请传正整数。")
        result["markdown"] = _enforce_max_len(result["markdown"], ml)
        result["text"] = _enforce_max_len(result["text"], ml)

    if explain:
        result["explain"] = reasons
    warnings = _collect_warnings(content, f)
    if warnings:
        result["warnings"] = warnings
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _write_utf8(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _read_utf8(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _build_parser():
    p = argparse.ArgumentParser(
        prog="yotta_present",
        description="元呈 yotta-present 呈现核心：任意内容 → 可复制 Markdown / 纯文本（按需附本地 SVG）")
    p.add_argument("--file", metavar="PATH", help="从文件读取内容（UTF-8）")
    p.add_argument("--content", metavar="TEXT", help="直接传入内容（JSON 或文本）")
    p.add_argument("--form", choices=FORMS, help="显式指定形态（缺省自动判断）")
    p.add_argument("--template", metavar="KEY", help="命名场景模板：vuln_report/faq/status（优先于 --form）")
    p.add_argument("--platform", choices=PLATFORMS, default="webchat",
                   help="平台自适应：webchat/discord/whatsapp/plain（默认 webchat）")
    p.add_argument("--channel", choices=CHANNELS, default="auto",
                   help="渲染通道（默认 auto，按 platform 自动映射）：r0 保底无色（无 emoji）/ r1 emoji 增强；r2/r3 高级美化通道当前未开放")
    p.add_argument("--max-len", metavar="N", type=int, help="长度熔断上限（字符数，可选）")
    p.add_argument("--title", metavar="T", help="覆盖标题")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--md", action="store_true", help="输出 Markdown（默认）")
    g.add_argument("--text", action="store_true", help="输出纯文本")
    g.add_argument("--both", action="store_true", help="同时输出 Markdown 与纯文本")
    g.add_argument("--json", dest="json_out", action="store_true", help="输出完整 JSON 结果")
    p.add_argument("--out", metavar="PATH", help="写文件（--both 时写 .md 与 .txt；目录则按形态命名）")
    p.add_argument("--svg", metavar="PATH", help="图表形态：本地 SVG 输出路径")
    p.add_argument("--explain", action="store_true", help="附判断说明")
    p.add_argument("--list-forms", action="store_true", help="列出形态清单")
    p.add_argument("--list-templates", action="store_true", help="列出命名场景模板清单")
    p.add_argument("--version", action="store_true", help="显示版本")
    return p


def _read_input(args):
    if args.file:
        try:
            return _read_utf8(args.file)
        except OSError as e:
            raise PresentError("无法读取文件：%s" % e, hint="请检查文件路径是否存在、是否有读取权限；Windows 可用正斜杠路径。")
    if args.content is not None:
        return args.content
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return None


def _write_out(args, result):
    """--out 写文件；返回已写文件列表。"""
    out = args.out
    is_dir = os.path.isdir(out)
    base = out if is_dir else os.path.splitext(out)[0]
    written = []
    if args.json_out:
        p = os.path.join(base, "present.json") if is_dir else out
        _write_utf8(p, json.dumps(result, ensure_ascii=False, indent=2))
        written.append(p)
    elif args.text:
        p = os.path.join(base, "present-%s.txt" % result["form"]) if is_dir else out
        _write_utf8(p, result["text"])
        written.append(p)
    elif args.both:
        md_p = os.path.join(base, "present-%s.md" % result["form"]) if is_dir else (out or base + ".md")
        txt_p = os.path.splitext(md_p)[0] + ".txt"
        _write_utf8(md_p, result["markdown"])
        _write_utf8(txt_p, result["text"])
        written.extend([md_p, txt_p])
    else:
        p = os.path.join(base, "present-%s.md" % result["form"]) if is_dir else out
        _write_utf8(p, result["markdown"])
        written.append(p)
    for p in written:
        print("已写入：%s" % p)


def _friendly_error(e):
    """错误输出：人话 + 修复建议。"""
    msg = "错误：%s" % e
    hint = getattr(e, "hint", None)
    if hint:
        msg += "\n修复建议：%s" % hint
    return msg


def cli(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print("元呈 yotta-present %s（呈现核心，TOOL_NAME=%s）" % (VERSION, TOOL_NAME))
        return 0
    if args.list_forms:
        print("元呈 yotta-present 呈现形态（开源基线 %d 种）：" % len(FORMS))
        for f in FORMS:
            print("  %-12s %s" % (f, FORM_DESC[f]))
        return 0
    if args.list_templates:
        print("元呈 yotta-present 命名场景模板（%d 个）：" % len(TEMPLATES))
        for k, t in TEMPLATES.items():
            print("  %-14s %s" % (k, t.get("title", "")))
        return 0

    try:
        raw = _read_input(args)
    except PresentError as e:
        print(_friendly_error(e), file=sys.stderr)
        return 1
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        parser.print_help()
        return 1

    try:
        result = present(raw, form=args.form, title=args.title,
                         svg_out=args.svg, explain=args.explain,
                         platform=args.platform, channel=args.channel,
                         template=args.template, max_len=args.max_len)
    except PresentError as e:
        print(_friendly_error(e), file=sys.stderr)
        return 2
    except ValueError as e:
        print(_friendly_error(e), file=sys.stderr)
        return 2

    if args.svg and result["form"] != "chart":
        print("错误：--svg 仅在图表形态下有效（当前形态：%s，可加 --form chart）\n修复建议：图表形态用 --form chart，或去掉 --svg 走默认 Markdown 输出。"
              % result["form"], file=sys.stderr)
        return 2

    for w in result.get("warnings", []):
        print("提示：%s" % w, file=sys.stderr)

    if args.out:
        try:
            _write_out(args, result)
        except OSError as e:
            print("错误：写入失败：%s\n修复建议：请检查输出路径是否存在、目录是否可写。" % e, file=sys.stderr)
            return 2
        return 0

    if args.json_out:
        out = dict(result)
        if out.get("chart"):
            out["chart"] = {k: v for k, v in out["chart"].items() if k != "svg"}
        print(json.dumps(out, ensure_ascii=False, indent=2))
    elif args.text:
        print(result["text"])
    elif args.both:
        print(result["markdown"])
        print("\n---\n")
        print(result["text"])
    else:
        print(result["markdown"])
    return 0


if __name__ == "__main__":
    sys.exit(cli())
