---
type: project_topic
status: active
summary: "六条铁律为什么存在、靠哪个测试执行、边界在哪。"
tags: [invariants, architecture]
contains: [decision]
created: "2026-10-12"
updated: "2026-10-12"
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

- 为什么:1e-27 = 1e27 个 bit 里 1 个错;时域永远到不了。统计引擎用解析高斯尾(`erfc`)+ 枚举 ISI 组合,不走 FFT 卷积
  (FFT 卷积在峰值 1e-16 以下没有精度)。
- 怎么守:`tests/test_engines.py` 三个工作点(噪声主导、抖动主导、混合)时域 / 统计在 0.5–2× 内;`run_link` 默认只跑统计。
- 边界:非 LTI(驱动器非线性、串扰)不在本轮;将来加入时 2× 判据只对 LTI + 高斯成立。

## 4 多 lane 从第一天就在

- 怎么守:`tests/test_lanes.py` —— `lane_map` 三种修复模式;`lanes.count = 1` 的结果与 x4 模块的 lane 0 逐位相同;残余 skew 把
  lane 推离眼中心;两个 bundled 配置(x16 降宽、x64 备用 lane)跑通。
- 里程碑 2:lane 间 FEXT 串扰(`channel.xtalk`)按**物理**邻接取邻 lane,死 lane 与闲置备用 lane 静默,修复后的重映射改变邻接
  (`tests/test_xtalk.py`);单 lane 的结果不受串扰设置影响。

## 5 规范数字只用原文

- 怎么守:`data/spec/ucie_survey.yaml` 每条带 `source`;`tests/test_spec_sources.py` 核对 `grep "source: survey"` 的行数等于
  未核实条目数,`source: spec` 必须带 `quote`,引擎代码里没有 1e-27 / 25.0 / 0.75 字面量。
- 边界:综述来源本身的可靠性不在测试范围 —— 见 `spec-sources.md` 的逐条备注。

## 6 数值指纹

- 怎么守:`tools/fingerprint.py record / compare`(Halo 方法);`tests/test_fingerprint.py` 保证 compare 能抓到任何一处变化、
  引擎两次运行逐位相同。重构 PR 必须附 compare 输出。
