---
type: project_topic
status: active
summary: "段 8 的浏览器 GUI:报告即界面的设计决定、铁律 1 的守法、长任务怎么排队、哪些是有意不做的。"
tags: [gui, dash, report]
contains: [decision, lesson]
created: "2026-10-13"
updated: "2026-10-13"
related: [architecture-invariants.md, engines.md, spec-sources.md]
authoring_mode: ai_generated
---
# 浏览器 GUI

## 当前结论(G1,0.11.0)

- **页面就是报表**:`d2d_link.report`(从 `tools/budget_report.py` 搬进包,CLI 只剩入口;指纹逐位相同)的 dict 按"什么决定判定"的顺序渲染:
  标题句 → 1 Verdict → 3 Clock-path jitter → 5 Lanes & repair → 6 Crosstalk → 7 Receiver(2 What flips、4 Eye & bathtub、附录 sweeps 在 G2 / G3)。
  导出的 Markdown 与 CLI 输出逐字相同(`tests/test_gui.py::test_export_markdown_is_the_cli_report`)。
- **标题句里带下划线的值是控件**(封装、速率、长度、lane 数、串扰模式、布线):改一个 = 一条 override + 入队重跑;旧页面置灰保留到新结果落地。
  抽屉 "All fields" 由 `config/form.py::SECTIONS` 生成,改动只写 overrides、按 Re-run 才跑(93 个字段逐个自动重跑会刷爆队列)。
- **铁律 1 在代码里怎么守**:`gui/` 只 import `config`、`config.form`、`config.loader`、`engine`(`run_link`)、`report`、`spec`、`clock.forwarded`(worker 里建闭式预算)、
  `channel.coupled.describe`;`test_gui_imports_only_the_public_surface` 用 AST 扫每个文件。worker(`gui/jobs.py::execute`)返回纯 dict(可 pickle、可 JSON),
  页面永远拿不到 `LinkResult` 对象。
- **铁律 5 在页面上**:每个规范 / 模型数带来源 chip(survey 紫、model 橙、yaml 蓝、default 灰、override 琥珀、spec 绿);右栏"未核实输入"列出判定依赖的 survey 条目与 cite。
- **长任务**:`JobManager` = `ProcessPoolExecutor(2)` + 按 (kind, 配置哈希, 参数) 的结果缓存;页面 `dcc.Interval` 1 s 轮询,回调永不阻塞;`workers=0` 内联跑(测试)。
  ETA 按同 kind、同 lane 数的历史平均。
- 耗时基准(空闲机器):x1 1.6 s、x5 耦合 21 s、x16 29 s、bundled x64(无串扰、去重)0.9 s。

## 决策记录

- Dash 锁 `>=3,<5`(PyPI 4.4.1):Dash 4 的 Dropdown 换成了 `button.dash-dropdown` 结构,行内控件的 CSS 针对它写;不用 dash-bootstrap / dash-mantine,
  一个 `assets/light.css` 够了。只做浅色。
- 页面语言英文(与报表、导出同文),文档中文。
- 不用 Dash background callback(要 diskcache / celery):自管进程池更小、可测,也便于以后多用户时换成服务。
- `apply_overrides` 的类型转换没加:表单层 `values_to_overrides` 已经按字段 kind 转换,GUI 走它;CLI / API 的 overrides 仍要求正确类型。
- Opus 实跑纠正的三条记录(x5 耦合敏感性无单个翻转、x16 / x5 耗时 29 / 21 s、"x64 五分钟"只在开串扰时成立)已改进 ROADMAP / engines.md。

## 教训

- `python -m d2d_link.gui.app` 第一次静默退出:忘了 `if __name__ == "__main__"`,日志一行都没有。
- 无头 Chromium 的完整版 `chrome --headless=new` 只渲染约 910 px 高(视口比窗口少 90 px);截图用 `headless_shell` 或把窗口加高再裁。
