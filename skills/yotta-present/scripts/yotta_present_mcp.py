#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""yotta_present_mcp.py — 元呈（yotta-present）呈现 MCP server。

stdio MCP server（JSON-RPC 2.0，换行分隔），把 yotta_present.py 呈现核心
暴露为 MCP 工具：
  present_result  任意内容（JSON / Markdown / 纯文本）→ 可复制 Markdown / 纯文本
                   （按需本地 SVG；--output md|text|both|json；--explain 附判断说明）
  present_forms   列出开源基线形态清单（只读）

数据不出本机：只在本机拼字符串 / SVG，不联网、不调用远程渲染服务。

运行：python scripts/yotta_present_mcp.py
MCP 客户端配置：
  {"mcpServers":{"yotta-present":{"command":"python",
    "args":["<绝对路径>/scripts/yotta_present_mcp.py"]}}}
"""

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import yotta_present as yp  # noqa: E402

VERSION = yp.VERSION
TOOL_NAME = "yotta-present"
CN_NAME = yp.CN_NAME
MCP_PROTOCOL = "2025-03-26"
SERVERS = {TOOL_NAME: {"name": TOOL_NAME, "cn": CN_NAME, "version": VERSION}}


def _tool_error(message, extra=None):
    """构造工具调用错误结果（isError=true）。"""
    payload = {"error": message}
    if extra:
        payload.update(extra)
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
            "isError": True}


def _tool_spec(name, description, properties, required=None):
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            **({"required": required} if required else {}),
        },
    }


def mcp_tools():
    """返回 MCP tools 列表（呈现核心 + 形态清单）。"""
    return [
        _tool_spec(
            "present_result",
            "把任意 AI 输出（JSON 标准内容对象 / Markdown / 纯文本）统一为可复制的呈现结果："
            "输出 Markdown（--output md，默认）/ 纯文本（text）/ 两者（both）/ 完整 JSON（json）。"
            "自动判断形态（conclusion/table/checklist/prose/metrics/qa/report/chart），"
            "可用 --form 显式指定，或用 --template 套命名场景模板（vuln_report/faq/status）；"
            "--platform 平台自适应（discord/whatsapp 表格转列表、标题转加粗；plain 去符号）；"
            "--channel 渲染通道（auto 按 platform 映射：plain→r0 去 emoji、其余→r1 emoji 增强）；"
            "--max-len 长度熔断；图表形态会在本机生成 SVG（--svg 指定路径，否则 Markdown 内嵌 data URI）。"
            "数据不出本机。",
            {
                "content": {"type": "string", "description": "内容：JSON 标准内容对象字符串，或 Markdown / 纯文本"},
                "form": {"type": "string", "enum": yp.FORMS,
                         "description": "显式形态（缺省自动判断）"},
                "template": {"type": "string", "enum": sorted(yp.TEMPLATES),
                             "description": "命名场景模板：vuln_report/faq/status（优先于 form，可选）"},
                "platform": {"type": "string", "enum": yp.PLATFORMS, "description": "平台自适应（默认 webchat）：webchat 完整 Markdown；discord/whatsapp 表格转列表、标题转加粗；plain 去 Markdown 符号"},
                "channel": {"type": "string", "enum": yp.CHANNELS, "description": "渲染通道（默认 auto 按 platform 映射）：r0 保底无色（无 emoji）/ r1 emoji 增强；r2/r3 高级美化通道当前未开放"},
                "max_len": {"type": "integer", "description": "长度熔断上限（字符数，可选）：先压缩列表、再降标题、最后截断，保留结论"},
                "bold_keys": {"type": "array", "items": {"type": "string"},
                              "description": "自动加粗的字段名数组（可选），命中字段的值渲染为 **加粗**（plain 不加）"},
                "title": {"type": "string", "description": "覆盖标题（可选）"},
                "output": {"type": "string", "enum": ["md", "text", "both", "json"],
                           "description": "返回内容（默认 md）"},
                "svg": {"type": "string", "description": "图表形态：本地 SVG 输出路径（可选）"},
                "explain": {"type": "boolean", "description": "附判断说明（默认 true，缺省返回判型理由；可显式 explain=false 关闭）"},
            },
            ["content"],
        ),
        _tool_spec(
            "present_forms",
            "列出元呈开源基线 8 种呈现形态与说明（只读，无副作用）。",
            {},
        ),
        _tool_spec(
            "present_templates",
            "列出元呈命名场景模板骨架与说明（vuln_report/faq/status，只读，无副作用）。",
            {},
        ),
    ]


def _tool_present(arguments):
    content = arguments.get("content")
    if not content or not str(content).strip():
        return _tool_error("present_result 需要 content 参数")
    form = arguments.get("form") or None
    template = arguments.get("template") or None
    platform = str(arguments.get("platform") or "webchat").strip().lower()
    if platform not in yp.PLATFORMS:
        return _tool_error("platform 只支持 %s（当前：%s）" % ("/".join(yp.PLATFORMS), platform))
    channel = str(arguments.get("channel") or "auto").strip().lower()
    if channel not in yp.CHANNELS:
        return _tool_error("channel 只支持 %s（当前：%s）" % ("/".join(yp.CHANNELS), channel))
    max_len = arguments.get("max_len") or None
    bold_keys = arguments.get("bold_keys") or None
    if bold_keys is not None:
        # bold_keys 作为独立参数时并入 content（content 为 JSON 对象时）
        try:
            merged = json.loads(str(content)) if isinstance(content, str) and str(content).strip().startswith("{") else dict(content)
        except Exception:  # noqa: BLE001
            merged = None
        if isinstance(merged, dict):
            merged.setdefault("bold_keys", list(bold_keys))
            content = json.dumps(merged, ensure_ascii=False)
    title = arguments.get("title") or None
    svg = arguments.get("svg") or None
    output = str(arguments.get("output") or "md").strip().lower()
    if output not in ("md", "text", "both", "json"):
        return _tool_error("output 只支持 md|text|both|json（当前：%s）" % output)
    explain = bool(arguments.get("explain", True))
    try:
        r = yp.present(content, form=form, title=title, svg_out=svg, explain=explain,
                       platform=platform, channel=channel, template=template, max_len=max_len)
    except Exception as e:  # noqa: BLE001
        return _tool_error("present_result 执行失败：%s" % e)
    payload = {"form": r["form"], "channel": r.get("channel")}
    if explain:
        payload["explain"] = r.get("explain")
    if r.get("warnings"):
        payload["warnings"] = r["warnings"]
    if output in ("md", "both", "json"):
        payload["markdown"] = r["markdown"]
    if output in ("text", "both", "json"):
        payload["text"] = r["text"]
    if r.get("chart"):
        payload["chart"] = {k: v for k, v in r["chart"].items() if k != "svg"}
    if output == "json":
        payload["result"] = r
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
            "isError": False}


def _tool_forms(arguments):  # noqa: ARG001
    payload = {"forms": [{"name": f, "description": yp.FORM_DESC[f]} for f in yp.FORMS]}
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
            "isError": False}


def _tool_templates(arguments):  # noqa: ARG001
    payload = {"templates": [
        {"key": k, "title": t.get("title", ""),
         "structure": [b.get("type") for b in t.get("structure", [])]}
        for k, t in sorted(yp.TEMPLATES.items())]}
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
            "isError": False}


TOOL_HANDLERS = {
    "present_result": _tool_present,
    "present_forms": _tool_forms,
    "present_templates": _tool_templates,
}


def handle_message(msg):
    """处理一行 JSON-RPC 消息，返回响应 dict；通知返回 None。"""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        rid = msg.get("id") if isinstance(msg, dict) else None
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32600, "message": "invalid request"}}
    method = msg.get("method")
    rid = msg.get("id")
    if rid is None:  # JSON-RPC 通知（无 id）不响应
        return None
    if method is None:
        return None
    params = msg.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": rid,
            "result": {
                "protocolVersion": MCP_PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": TOOL_NAME, "version": VERSION},
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": mcp_tools()}}
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        handler = TOOL_HANDLERS.get(name)
        if not handler:
            return {
                "jsonrpc": "2.0", "id": rid,
                "result": {"content": [{"type": "text", "text": "未知工具: %s" % name}], "isError": True},
            }
        try:
            return {"jsonrpc": "2.0", "id": rid, "result": handler(arguments)}
        except Exception as e:  # noqa: BLE001
            return {
                "jsonrpc": "2.0", "id": rid,
                "result": {"content": [{"type": "text", "text": "工具执行异常：%s" % e}], "isError": True},
            }
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Method not found: " + str(method)}}


def main():
    """stdio 主循环：读行 -> JSON-RPC -> 响应行。"""
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(json.dumps(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}},
                ensure_ascii=False) + "\n")
            sys.stdout.flush()
            continue
        resp = handle_message(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
