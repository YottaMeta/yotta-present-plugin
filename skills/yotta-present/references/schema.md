# 标准内容对象 schema（v1）——元呈 yotta-present 呈现核心

> 用途：给 `yotta_present` CLI / `present_result` MCP 工具的标准输入格式。
> 智能体（经 SKILL.md 判断层）把「要呈现的内容」组装成标准内容对象，再交给元呈渲染；
> 也可直接喂 Markdown / 纯文本，由元呈自动解析并兜底美化。

## 字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `title` | string | 否 | 标题（# 一级标题） |
| `headline` | string | 否 | 头条 / 一句话结论（引用块） |
| `grade` | string | 否 | 等级徽章：`success`(🟢通过) / `warn`(🟡警告) / `danger`(🔴危险) / `info`(⚪信息)，或任意自定义文本 |
| `verdict` | string | 否 | 裁决 / 结论正文（与 `grade` 搭配） |
| `metrics` | array | 否 | 指标块：`[{label, value, unit?, tone?}]`；`tone` 取 `up`(▲) / `down`(▼) / `neutral`(—) |
| `rows` | array | 否 | 表格：对象列表 / 二维数组 / 键值对（见下） |
| `bullets` | array | 否 | 要点（短列表项）；`[x]` / `[ ]` 前缀自动保留为复选框 |
| `body` | array | 否 | 正文段落（长文本；纯文本输入自动解析而来） |
| `notes` | array | 否 | 注记 / 免责（`> 注：…`） |
| `chart_data` | object | 否 | 图表数据（见下）；存在时形态自动判为 `chart` |
| `headers` | array | 否 | 表格显式表头（`rows` 为二维数组时可选） |
| `form` | string | 否 | 显式形态（缺省自动判断）：`conclusion` / `table` / `checklist` / `prose` / `metrics` / `qa` / `report` / `chart` |
| `template` | string | 否 | 命名场景模板（优先于 `form`）：`vuln_report` / `faq` / `status`（定义见 `templates.json`） |
| `code` | string | 否 | 代码块内容（模板 `codeblock` 块使用） |
| `bold_keys` | array | 否 | 自动加粗的字段名数组（命中字段值渲染为 `**加粗**`；plain 不加） |
| `max_len` | integer | 否 | 长度熔断上限（字符数）：先压缩列表、再降标题层级、最后截断，保留 title/headline/verdict |


## 形态 → 输入形式 → 必填字段（速查）

| 形态 | 推荐输入 | 必填 / 关键字段 | 备注 |
|---|---|---|---|
| `conclusion` | JSON | `grade` / `verdict`（徽章与裁决结构） | 传 Markdown 会按 prose 兜底，无徽章 |
| `table` | JSON | `rows`（对象列表 / 二维数组 / 键值对） | **无 `columns` 字段**；二维数组可用 `headers` |
| `checklist` | Markdown `- [x]` / `- [ ]`，或 JSON | `bullets` | |
| `prose` | Markdown 段落 / JSON | `body` / `text` | 兜底形态 |
| `metrics` | JSON | `metrics`（≥1 项） | |
| `qa` | JSON | `rows`（键须命中 问题/question/q + 回答/answer/a 两列） | 否则判 `table` |
| `report` | JSON（多节组合）或 Markdown 多节 | `title` + 至少一段内容 | |
| `chart` | JSON | `chart_data`（`chart`/`type` + 数据） | 无 `--svg` 时 Markdown 内嵌 data URI |

> 规则：要精确控制形态，请显式传 `form` + 对应 JSON；不传 `form` 时按内容形状自动判断（可解释，`--explain` 返回原因）。错误字段组合不会报错，但会输出「提示」（CLI stderr / MCP `warnings` 字段）。

## rows 三种形式

1. **对象列表（推荐）**：键并集即表头，列序按首现。

```json
{"rows": [{"方案": "A", "成本": "低"}, {"方案": "B", "成本": "高"}]}
```

2. **二维数组**：首行全为字符串且行数 >= 2 时首行视为表头；恰好 2 列按「项 / 值」键值表；否则自动补「列 N」。

```json
{"rows": [["列1", "列2"], ["v1", "v2"]], "headers": ["列1", "列2"]}
```

3. **键值对**：每行恰为 `{"header": …, "value": …}`，或二维数组 2 列。

```json
{"rows": [{"header": "安装方式", "value": "npx -y @yottameta/yotta-present"}]}
```

## chart_data

复用元呈 12 图内核（bar / line / pie / radar / scatter / histogram / funnel /
waterfall / word_cloud / sankey / spreadsheet / treemap）。

```json
{"chart_data": {"chart": "line", "title": "访问趋势", "labels": ["一", "二", "三"], "data": [3, 5, 4]}}
```

- `chart`（或 `type`）指定图型，缺省 `bar`。
- 其余字段（`labels` / `data` / `width` / `height` / `palette` / `stacked` / `fill` 等）透传给渲染内核。
- 输出：Markdown 内嵌 `data:image/svg+xml;base64,…`（自包含可复制）；指定 `--svg <路径>` 时写本地 SVG 文件并在 Markdown 用相对路径引用。

## 形态清单（开源基线 8 种）

| 形态 | CLI 名 | 何时用 |
|---|---|---|
| 结论卡 | `conclusion` | 单个结论 / 评分 / 推荐 → 徽章 + 指标 + 要点 |
| 表格交付 | `table` | 行列分明、需对比 / 罗列的数据 |
| 清单卡 | `checklist` | 事项 / 要点 / 清单（支持 `[x]` / `[ ]`） |
| 正文 | `prose` | 叙述 / 说明 / 长段落 |
| 指标板 | `metrics` | 一组关键指标 |
| 问答卡 | `qa` | 问题 / 回答成对（rows 或 bullets 均可） |
| 报告 | `report` | 多节长内容（卡片 + 表 + 文组合 + 目录） |
| 图表 | `chart` | 数值分布 / 趋势 / 占比（本地 SVG） |

## 确定性判断兜底（内容形状 → 形态）

`--form` 显式指定优先；否则按以下顺序：

1. 含 `chart_data` → `chart`
2. `rows` 为「问题 / 回答」两列（表头或键命中 问题/question/q + 回答/answer/a）→ `qa`
3. `title` + `rows` + 其他内容段 → `report`
4. `rows` → `table`
5. `metrics` + 结论（verdict/grade/headline）→ `conclusion`；仅 `metrics`（>= 2 项）→ `metrics`
6. `bullets` 成对「问 / 答」→ `qa`；`bullets` + 结论 → `conclusion`；仅 `bullets` → `checklist`；含 `body` → `prose`
7. 仅 `verdict` / `grade` → `conclusion`
8. 仅标题 / 头条 / 正文 → `prose`
9. 兜底：任何输出至少套「正文」美化，不让内容裸奔

> 判断可解释：CLI `--explain` / MCP `explain=true` 返回选择原因。

## 示例

### 结论卡

```json
{
  "title": "安全扫描结果",
  "grade": "success",
  "verdict": "未发现高危风险",
  "metrics": [{"label": "检测点", "value": 8, "unit": "项"}],
  "bullets": ["全部 8 个检测点通过", "数据未出本机"],
  "notes": ["扫描仅在本机进行"]
}
```

### 报告

```json
{
  "title": "周报",
  "headline": "本周三项推进顺利",
  "verdict": "整体进度正常",
  "metrics": [{"label": "任务", "value": 12}, {"label": "完成", "value": 9}],
  "rows": [["项", "状态"], ["元呈 S3", "进行中"], ["在线检测", "定案"]],
  "bullets": ["下周进入校验"]
}
```

### 图表

```json
{"title": "趋势", "chart_data": {"chart": "pie", "labels": ["A", "B"], "data": [3, 1]}}
```

## 渲染通道与平台（channel × platform）

`channel`（CLI `--channel` / MCP `channel`，默认 `auto`）定「载体族」；`platform`（CLI `--platform` / MCP `platform`，默认 `webchat`）定「族内降级」。

| channel | 载体 | 说明 |
|---|---|---|
| `auto`（默认） | — | 按 platform 自动映射：`plain` → `r0`；`webchat` / `discord` / `whatsapp` → `r1` |
| `r0` | 基础 Markdown / 纯文本 | 保底无色：无 emoji 徽章（文字徽章仍在，如「危险」） |
| `r1` | Markdown | emoji 增强：🟢🟡🔴⚪ 徽章 + 引用条 + 分隔线（默认） |
| `r2` / `r3` | — | 富文本 HTML / SVG 整卡（高级美化引擎，后续版本推出；显式指定提示未开放） |

| platform | 族内降级 |
|---|---|
| `webchat` | 完整 Markdown（标题 / 表格 / 代码块全支持，默认） |
| `discord` / `whatsapp` | 禁表格、禁大标题 → 表格自动转列表、标题转加粗；代码块保留 |
| `plain` | 命令行 / 纯文本：保留分点与逻辑顺序，去 Markdown 符号（# / ** / > / 表格竖线）；自动 r0 去 emoji |

## 命名场景模板（template）

声明式 structure 骨架 + 平台策略，**一次定义多处复用**；定义存 `references/templates.json`（可热更新，缺失回退内置）。

| 模板 key | 用途 | 结构 |
|---|---|---|
| `vuln_report` | 漏洞 / 安全报告 | 概述 → 等级与指纹（表格）→ 复现步骤（有序列表）→ 请求样本（codeblock）→ 危害分析（列表）→ 修复建议（有序列表） |
| `faq` | 问答 | 结论先行 → 问答对 |
| `status` | 状态一句话 | 纯文本（headline / verdict） |

模板块类型：`heading` / `summary` / `table` / `list`（bulleted / ordered）/ `codeblock` / `qa` / `plain`；每块 `source` 指定内容字段，缺字段自动跳过（骨架自适应）。

## 长度熔断（max_len）

`max_len`（content）或 `--max-len N`（CLI）：渲染结果超限时依次「压缩列表 → 降标题层级 → 硬截断」，保留 `title` / `headline` / `verdict` 结论，不丢重点。
