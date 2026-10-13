---
type: project_topic
status: active
summary: "六条铁律为什么存在、靠哪个测试执行、边界在哪。"
tags: [invariants, architecture]
contains: [decision]
created: "2026-10-12"
updated: "2026-10-13"
related: [forwarded-clock.md, engines.md, spec-sources.md]
authoring_mode: ai_generated
---
# 架构铁律:论证与执行

`AGENTS.md` 列出六条;这里写每条**为什么**、**靠什么守**、**不管什么**。

## 1 配置是唯一真值

- 为什么:D2D 链路的结论随封装、速率、lane 数、时钟方案四个维度变,任何一个散落在示例或脚本里,扫描和对比就不可信。
- 怎么守:`LinkConfig` 冻结(`tests/test_config.py::test_frozen`);未知键报错;`config/form.py::SECTIONS` 与 schema 字段双向一致
  (`test_form_declares_every_field_and_nothing_else`),将来 GUI 从它生成而不新增逻辑;`tests/test_invariants.py` 静态扫描引擎层
  代码(去掉注释与字符串后)不含速率 / BER 目标 / reach 字面量,示例必须 `load_config(`。
- 边界:`PACKAGE_RLGC` 是模型参数预设(不是规范数字),放在 schema 里,可被 channel 字段逐项覆盖。

## 2 前向时钟的抖动跟踪是核心机制

- 为什么:见 `forwarded-clock.md`。一句话:数据和前向时钟出自同一个 PLL,收端看到的是差;把前向时钟当一个"同 RMS 的独立时钟"
  会把 186 fs 的 PLL 抖动全部算进预算,结论就错了一个数量级。
- 怎么守:`tests/test_forwarded_clock.py` —— 相关 = 1 残余恰为 0(闭式与合成都为 0);跟踪带宽 ∞ → 0;无跟踪 → 两路独立功率和;
  闭式与合成 5% 内。`tests/test_local_pll.py`(里程碑 2)—— 本地 PLL 环路带宽 ∞ → 残余 0(本地噪声全压掉),→ 0 → 发端 + 本地
  两路功率和;没有环路带宽的本地 PLL 被 schema 拒绝。`tests/test_invariants.py::test_law2_*` 静态保证配置里除 `clocking.local_pll_*`
  外没有任何收端时钟字段、`clock/forwarded.py` 之外没有第二处合成相噪。

## 3 统计引擎是主引擎

- 为什么:1e-27 = 1e27 个 bit 里 1 个错;时域永远到不了。统计引擎用电压网格上精确的 ISI 分布 + log 域解析高斯尾
  (`log_ndtr`),不走 FFT 卷积(FFT 卷积在峰值 1e-16 以下没有精度),也不走线性域 `erfc`(1e-308 以下下溢成 0.0,
  段 0 体检发现它让最差 lane 永远是 lane 0)。
- 怎么守:`tests/test_engines.py` 三个 ~1e-4 工作点(噪声主导、抖动主导、混合)加一个 1e-6 点(2.5e7 符号)时域 / 统计在 0.5–2× 内;
  `tests/test_engines_deep.py`(`slow`,每周 `examples-full.yml` 的 `deep` 作业)跑 1e9 符号的 3e-8 点;`run_link` 默认只跑统计。
- 边界:2× 判据只对 LTI + 高斯成立;串扰(M2 起)按独立 ±1 干扰项进入,仍在该范围内;驱动器非线性不在模型里。
  诚实的尺度(段 4):波形路径每 1e6 符号约 6 s,1e-8 的 25 个误码要 2.5e9 符号 ≈ 5 h,只能手动触发;"1e-9" 在这个引擎上不可达。
  `sim.time_mode: samples` 只算采样值(逐光标内插求和),与波形路径同一算术,但有损走线的脉冲尾在 130 UI 内都高于主光标的 1e-6,
  光标数不减,因此并不更快;它只在短记忆信道(先进封装 2 mm,floor 1e-4 时 47 个光标,快 4×)上有意义。

## 4 多 lane 从第一天就在

- 怎么守:`tests/test_lanes.py` —— `lane_map` 三种修复模式;`lanes.count = 1` 的结果与 x4 模块的 lane 0 逐位相同;无跟踪器时
  残余 skew 把 lane 推离眼中心、最差 lane 按裕度取到它;有跟踪器时残余 skew 为 0、两 lane 相同;两个 bundled 配置(x16 降宽、
  x64 备用 lane)跑通。
- 里程碑 2:lane 间 FEXT 串扰(`channel.xtalk`)按**物理**邻接取邻 lane,死 lane 与闲置备用 lane 静默,修复后的重映射改变邻接
  (`tests/test_xtalk.py`);单 lane 的结果不受串扰设置影响。

## 5 规范数字只用原文

- 怎么守:`src/d2d_link/data/spec/ucie_survey.yaml` 每条带 `source`;`tests/test_spec_sources.py` 核对 `grep "source: survey"` 的行数等于
  未核实条目数,`source: spec` 必须带 `quote`,引擎代码里没有 1e-27 / 25.0 / 0.75 字面量。
- 边界:综述来源本身的可靠性不在测试范围 —— 见 `spec-sources.md` 的逐条备注。
- 延伸(段 2):规范不管、仿真又必须有的数(走线 R / tanδ / Z0、叠层 w / h / ε_r、行为级串扰电平)是**模型估计**,在
  `src/d2d_link/data/spec/model_presets.yaml` 里每条 `source: model` + cite + note;`grep -c "source: model"` = 18。L、C 不在表里,由 Z0 与
  Hammerstad ε_eff 推出,信道延时与串扰估计共用一个介电常数。`tools/budget_report.py --sensitivity` 把每条 ±20% 看结论翻不翻 ——
  "哪些猜测决定结论"不再靠记忆。

## 6 数值指纹

- 怎么守:`tools/fingerprint.py record / compare`(Halo 方法);`tests/test_fingerprint.py` 保证 compare 能抓到任何一处变化、
  引擎两次运行逐位相同。重构 PR 必须附 compare 输出。
