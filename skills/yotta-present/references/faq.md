# 元呈 FAQ / 避坑指南

> 常见问题速查：遇到报错或输出不符合预期时，先看这里。错误信息里也会附「修复建议」。

## 1. 想带徽章 / 裁决，但输出没有徽章？
纯文本 / Markdown 输入时，元呈无法提取 `grade` / `verdict`。请改用**标准内容对象 JSON**：

```json
{"title": "结论", "grade": "success", "verdict": "通过", "bullets": ["要点 1", "要点 2"]}
```

## 2. 表格里写了 `columns` 字段不生效？
`table` 不支持 `columns`。列名请用 `rows` 对象列表的键（`[{"名称": "值", ...}]`），或二维数组 + `headers`。

## 3. 想生成图表但报「形态 chart 需要 chart_data」？
图表形态必须传 `chart_data`：

```json
{"chart_data": {"chart": "pie", "labels": ["A", "B"], "data": [3, 1]}}
```

## 4. `--svg` 报错？
`--svg` 只在图表形态（`chart`）下有效。想用图表 → 传 `chart_data`；不需要本地文件 → 去掉 `--svg`（默认输出 Markdown 内嵌 data URI，自包含可复制）。

## 5. 输出形态不是我想要的？
自动判断偶尔不符合预期 → 显式指定 `--form`（conclusion / table / checklist / prose / metrics / qa / report / chart），或用 `--explain` 看判断理由。

## 6. 报「JSON 解析失败」？
检查引号、逗号、括号是否完整；JSON 必须是完整对象 `{...}`，不是数组或单值。

## 7. MCP 工具没加载？
检查 `mcpServers` 已配置 `yotta-present`（`python <技能目录>/scripts/yotta_present_mcp.py`）；改配置后需**重启 / 重载会话**。仍未加载 → 自动降级 CLI，输出一致。

## 8. 复制到 Word / 邮件格式乱？
用 `--text` 输出纯文本（去 Markdown 符号）。

## 9. 输出太长？
用 `--max-len N`：先压缩列表、再降标题层级、最后截断，保留结论（title / headline / verdict）。

## 10. 不同平台显示差异？
`--platform`：`webchat`（默认，完整 Markdown）/ `discord` / `whatsapp`（表格转列表、标题转加粗）/ `plain`（纯文本去符号）。

## 11. 退出码 0 / 1 / 2 什么意思？
0 = 成功；1 = 无输入或读取错误；2 = 内容校验或渲染错误（stderr 会给出原因 + 修复建议）。

## 12. 为什么有的内容不走元呈？
白名单例外：纯代码 / 命令、错误堆栈 / 日志、超长内容（走 `--out` 落盘）、用户明确要一句话 / 裸文本——这些原样输出，不用元呈。

## 13. 想去掉 emoji / 颜色（老终端 / sanitize 环境）？
`--channel r0`：保底通道，无 emoji 徽章（文字徽章仍在，如「危险」）。`platform=plain` 默认自动就是 r0。

## 14. `--channel r2 / r3` 报「尚未开放」？
R2（富文本 HTML）/ R3（SVG 整卡）属高级美化引擎（收费侧），计划后续版本推出；当前开源提供 r0（无色保底）/ r1（emoji 增强）。用默认 auto 即可，或显式 `--channel r0`。
