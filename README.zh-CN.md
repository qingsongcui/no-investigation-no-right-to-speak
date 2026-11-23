# Evidence-First Research（没有调查，就没有发言权）

[English](README.md) · **简体中文**

面向 AI Agent 的证据优先研究流程与校验工具包。

本仓库给 AI Agent 一套有纪律的研究方法：带来源记录、显式不确定性，高风险或因果结论还要经过一次全新的独立审查。Python 工具只校验结构与溯源。PASS 不代表答案正确，只代表引用可解析、判断能对应到报告，且在 `reviewed` 模式下审查仍与受审文件匹配。

## 三种流程

| 模式 | 适用 | 必需产物 | 独立审查 |
|---|---|---|---|
| `answer` | 一般事实、解释和比较 | `research.json`、`final_report.md` | 作者核对 |
| `reviewed` | 高风险决策、因果结论、关键来源冲突 | 上述文件 + `review.json` | 一次全新综合审查 |
| `audited` | 明确要求正式审计，或恢复旧 v2.4 调查 | 保留 v2.4 研究设计、证据与双门禁契约 | 两个独立门禁 |

一般问题走 `answer`。`audited` 是更严格的兼容路径，不是推荐默认。高风险或因果任务不能降为 `answer`，校验器会拒绝。

## 哪项证据会改变答案

Agent 先建立可推翻的解释，再调查最能改变结论的疑点，而不是先固定几十条主张去配证据。新建的 `reviewed` 调查与用 `--deep` 建立的解释题，会在 `research.json` 里立一条关键检验（probe）：写清暂时判断、最有力的竞争解释，以及能区分两者的可观察差异。当一个问题的答案取决于谁付钱、谁执行、谁承担后果时，Agent 会沿一笔订单、一次排班或一次争议追查利益关系。完整方法见 `skills/deep-research/SKILL.md`。

## 开始使用

Agent 先完整读 `skills/deep-research/SKILL.md`。理解用户约束，列出真正会改变答案的疑问，再查资料。

```bash
python3 tools/research.py init investigations/my-question --question '要调查的问题' --author-id '实际作者标识'
# 重大决策增加 --stakes high；准备作因果结论增加 --causal
# 一般解释题需检验竞争解释时增加 --deep
python3 tools/research.py next investigations/my-question
python3 tools/research.py check investigations/my-question --draft
# 完成答案，以及 reviewed 所需独立审查后：
python3 tools/research.py check investigations/my-question
# 原 speak 入口也能识别 v3：
python3 tools/validate.py speak investigations/my-question
```

记录格式见 `schemas/research.schema.json`；空白模板见 `templates/research.json`。`--draft` 仅检查草稿结构，不是交付验收。

## 五分钟验证

```text
python3 -m unittest discover -s tests -p 'test*.py'
python3 tools/research.py check examples/agent-skill-installation-reviewed
python3 tools/validate.py speak examples/agent-skill-installation-reviewed
```

三条命令都须返回 `0`。第二条校验随仓库发布的 `reviewed` 示例（来源类型、标题级定位、SHA-256 校验的来源快照、实时的审查绑定）；第三条把同一目录走 `speak` 入口，它在发现 `research.json` 时分派到 v3 校验器。

## 少做无用功，多解决问题

- 先建立可推翻的解释，再调查关键疑点，不先固定几十条结论去配证据。
- 记录搜索新增了什么；按疑点查反证，不按每条主张机械重复五类查询。
- 不为凑预算继续搜索；有重要可补缺口也不提前停止。
- 一份记录维护问题、证据、判断和缺口，不反复抄进多套文件。
- 先直接回答，再解释依据和影响。没有固定摘要、前瞻章、因果图或页数要求。
- 只在用户需要时导出文件，默认朴素排版，保留正常标题与链接。

```bash
# 可选导出；需要 python-docx、officecli 与本机 Chrome
python3 tools/export_pdf.py investigations/my-question --style plain
```

## 质量边界

1. 本工具包不自行联网。检索和阅读来源由运行它的 Agent 用其运行环境的工具完成。
2. 它不认证来源真实性或语义蕴含。它只检查被引用的来源是否已记录、快照是否匹配、判断是否能对应到报告正文，不证明来源正确或真能推出结论。
3. 它不用密码学证明审查者独立性。`review.json` 的 `input_fingerprint` 证明受审文件在审查后未改动；`reviewer_id` 与 `provenance` 是声明，真实独立性需由实际工具调用记录支撑。
4. 它不保证抵抗模型层提示注入。外部材料按不可信数据处理（见 `docs/security.md`），但封箱是记账边界，不是安全证明。

机器 PASS 只表示结构和追溯通过，不能证明引用真正支持全文、资料真实或推理正确。真正的内容问题交给来源核对和独立审查。

## 目录结构

- `tools/` —— 校验器与辅助工具（`research.py` 走 v3 流程，`validate.py` 走旧 audited 路径与 `speak` 分派）。
- `schemas/` —— 研究记录与审查的 JSON 契约。
- `templates/` —— 新建调查的起点记录。
- `skills/deep-research/` —— Agent 工作流：何时用哪种流程、如何记录证据、如何请求独立审查。
- `examples/agent-skill-installation-reviewed/` —— 随仓库发布的唯一示例，见 `examples/README.md`。
- `tests/` —— 行为回归套件，外加合成的 audited 路径 fixtures。
- `docs/` —— 架构、安全模型与评估方法。