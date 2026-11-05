---
type: project_topic
status: active
summary: "规范数字的来源状态:哪些是综述、各自待核实什么、原文到手后怎么升级。"
tags: [spec, ucie, sources]
contains: [decision]
created: "2026-10-12"
updated: "2026-11-04"
related: [architecture-invariants.md]
authoring_mode: ai_generated
---
# 规范数字来源

## 当前结论

- 全部 15 条都是 `source: survey`,见 `src/d2d_link/data/spec/ucie_survey.yaml`;没有一条读过规范原文。`grep -c "source: survey" src/d2d_link/data/spec/ucie_survey.yaml` = 15
  (文件头注释不再含该字串,测试断言这条命令的计数)。
- 综述来源是公开材料的记忆与转述(Das Sharma 2022 的 UCIe 综述、Consortium 白皮书、Hot Chips 34 概览),**数值本身未经核对**,
  每条 note 都写了"未核实"。最不可靠的三条:收端眼高 40 mV、眼宽 0.75 UI(眼罩表的速率档与封装归属不明)、1e-15 的 retry 口径。
- 升级流程:用户把原文贴进 `cairn/Reference/`(只追加)→ 对应条目改 `source: spec`、加 `quote` 与 `section` → `tests/test_spec_sources.py`
  自动要求 quote 非空 → LOG 记一条。
- **分档(0.13.5;0.13.10 定了优先级)**:目标按 `<package>.<key>@<rate>` → `<package>.<key>` → `<key>@<rate>` → `<key>` 查表(`spec.survey_tiered`)。
  封装压过速率:标准与先进封装是两套电气规范,封装自己的数在每个速率都成立,除非该封装另给了那个速率的数;只给速率的条目是封装没说话时的退路。
  原文的眼罩若按速率档 / 封装给数,就加对应的分档条目(如 `standard.rx_eye_width_ui@32`,`source: spec`),只接管那一档;
  没写到的档继续落到综述的通用值。报表的 Targets 表多一列 table key,GUI 的未核实输入卡按这个 key 取出处。
  今天没有分档条目:综述的眼罩不带速率与封装,不为凑表复制同一个未核实的数(铁律 5)。

## 规范数字进入模型的地方(里程碑 3)

- `standard.bump_pitch_um` / `advanced.bump_pitch_um` 的中值是耦合线串扰估计的默认 lane 间距(`channel/coupled.py::trace_pitch_um`),
  报表与示例打印 `pitch 115 um (source: survey)`;配置里显式给 `channel.trace_pitch_um` 时标 `config`。
- `data_rates_gtps` 是示例 07 的扫描轴。

## 决策记录

- 规范数字不进代码:`TargetConfig` 字段默认 None,运行时按 package 与速率分档解析成 `(value, source)`(0.13.5 起 `target_keys` 给出答话的表 key),结果行打印 `source: xxx`。
  配置里显式写的值标 `source: config`,是配置自己的主张。
- `PACKAGE_RLGC` 是模型参数,不是规范数字,不进这张表;reach / pitch / 模块宽度进表。
- 段 2 起模型参数有自己的表 `src/d2d_link/data/spec/model_presets.yaml`(30 条,全部 `source: model`,带 cite 与 note):R_dc、R_skin、tanδ、G、Z0、
  w、h、ε_r、行为级 FEXT 电平,两种封装各一套。L、C 由 Z0 与 Hammerstad ε_eff(w, h, ε_r)推出 —— 之前 `PACKAGE_RLGC` 自带的 L、C 隐含
  ε_eff 3.94 / 5.75,与叠层的 ε_r 3.5 / 3.3 矛盾(体检 #3)。`grep -c "source: model"` = 30(0.13.3 起含第二邻串扰偏移 −12 dB;0.13.11 起含时钟路径抖动:数据 / 时钟路径白抖 200 fs、树 100 fs、路径漫游 200 fs、漫游拐角 1 MHz,各两种封装 —— 2026-11-05 检索未找到片上 D2D 路径的公开实测值,cite 里写了最近的参照与没读到的原文);`tests/test_spec_sources.py` 守着两张表互不混放。
- **眼罩分档的线索(2026-11-05,未核实,未采用)**:一篇 2025 年分析 UCIe 48/64 GT/s 链路的论文(ResearchGate 395249532,检索摘要)写
  "4–16 GT/s 要求 EH/EW = 40 mV / 0.75 UI,24–32 GT/s 为 40 mV / 0.65 UI"。这是二手转述,不是原文;如属实,x1(0.709)与 x16 模块(0.693)
  会过、x5(0.575)仍不过。采用的话加 `rx_eye_width_ui@24` / `@32`(source: survey,cite 此文),会动判定 —— 待用户决定。
- 敏感性:`tools/budget_report.py --sensitivity` 对每条估计 ±20%(dB 值与剖面整体平移 ±3 dB;0.13.3 起含配置里的抖动值;眼罩目标 ±10 mV / ±0.05 UI)重跑,表里标出翻转结论的参数。
  0.13.3 重跑:x1 名义裕度 −0.055、x16 模块 −0.051 —— **只有眼宽目标翻转**(0.70 UI 时 +0.013 / +0.017);离翻转最近的估计是 PLL 剖面 −3 dB(−0.024 / −0.031)
  与数据路径白抖 −20 %(−0.037 / −0.032)。x5 耦合 −0.214,什么都不翻(最近的是介质厚 24 µm −0.140、bump 间距 138 µm −0.154)。
  0.13.6(FEXT 改成攻击方导数)后:x16 模块 −0.076,眼宽目标 0.70 也不翻(−0.010),最近的是串扰 −33 dB / 剖面 −3 dB(−0.057);x5 −0.233(介质 24 µm −0.178);x1 不变。
