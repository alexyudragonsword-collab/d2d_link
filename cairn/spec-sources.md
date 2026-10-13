---
type: project_topic
status: active
summary: "规范数字的来源状态:哪些是综述、各自待核实什么、原文到手后怎么升级。"
tags: [spec, ucie, sources]
contains: [decision]
created: "2026-10-12"
updated: "2026-10-13"
related: [architecture-invariants.md]
authoring_mode: ai_generated
---
# 规范数字来源

## 当前结论

- 全部 15 条都是 `source: survey`,见 `data/spec/ucie_survey.yaml`;没有一条读过规范原文。`grep -c "source: survey" data/spec/ucie_survey.yaml` = 15
  (文件头注释不再含该字串,测试断言这条命令的计数)。
- 综述来源是公开材料的记忆与转述(Das Sharma 2022 的 UCIe 综述、Consortium 白皮书、Hot Chips 34 概览),**数值本身未经核对**,
  每条 note 都写了"未核实"。最不可靠的三条:收端眼高 40 mV、眼宽 0.75 UI(眼罩表的速率档与封装归属不明)、1e-15 的 retry 口径。
- 升级流程:用户把原文贴进 `cairn/Reference/`(只追加)→ 对应条目改 `source: spec`、加 `quote` 与 `section` → `tests/test_spec_sources.py`
  自动要求 quote 非空 → LOG 记一条。

## 规范数字进入模型的地方(里程碑 3)

- `standard.bump_pitch_um` / `advanced.bump_pitch_um` 的中值是耦合线串扰估计的默认 lane 间距(`channel/coupled.py::trace_pitch_um`),
  报表与示例打印 `pitch 115 um (source: survey)`;配置里显式给 `channel.trace_pitch_um` 时标 `config`。
- `data_rates_gtps` 是示例 07 的扫描轴。

## 决策记录

- 规范数字不进代码:`TargetConfig` 字段默认 None,运行时按 package 解析成 `(value, source)`,结果行打印 `source: xxx`。
  配置里显式写的值标 `source: config`,是配置自己的主张。
- `PACKAGE_RLGC` 是模型参数,不是规范数字,不进这张表;reach / pitch / 模块宽度进表。
