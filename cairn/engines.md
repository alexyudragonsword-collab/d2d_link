---
type: project_topic
status: active
summary: "统计引擎(主)与时域引擎(校核)各自怎么算、为什么能到 1e-27、2× 判据在哪些点上量过。"
tags: [statistical, time-domain, ber]
contains: [decision, lesson]
created: "2026-10-12"
updated: "2026-10-12"
related: [architecture-invariants.md, forwarded-clock.md]
authoring_mode: ai_generated
---
# 双引擎

## 当前结论

**统计引擎**(`engine/statistical.py`)在 LTI + 高斯下精确:

- 采样值 = 主光标 + Σ c_k b_k + 噪声。最大的 `sim.stat_enumerate_cursors`(默认 12)个光标按 2^M 个 ±1 组合**枚举**,
  其余并成方差;误码率 = 组合上高斯尾(`erfc`)的平均。不用 FFT 卷积 PDF —— 那在峰值 1e-16 以下没有精度,到不了 1e-27。
- 采样抖动在相位轴上做:残余 σ_j(`ForwardedClock.budget`,闭式)作高斯,BER(φ) = Σ_j w_j BER0(φ + δ_j),δ 均匀网格、
  步长 ≤ σ/4 且是浴盆网格的整数细分、范围 ±12σ。DDR 占空比误差是两个相位平均。
- 采样相位:目标 BER 处眼开区间的中点(眼居中跟踪器);配置可固定。眼高用同一套尾和二分求;眼宽按 log BER 内插。
- 枚举 10 与 16 个光标差 < 5%(25 mm、噪声 40 mV)。

**时域引擎**(`engine/timedomain.py`)不近似统计引擎假设的任何东西:同一脉冲(fftconvolve)、同一噪声(采样点上加)、
同一抖动谱(`ForwardedClock.synthesize` 的逐符号残余);分块含过去 n_tail 与未来 n_pre 符号。PRBS 按 t 位一步向量化。

## 2× 判据量到的点(25 mm、32 GT/s、`tests/test_engines.py`)

| 工作点 | 统计 BER | 时域 BER(误码数) | 比 |
|---|---|---|---|
| 噪声主导,50 mV | 7.09e-4 | 6.48e-4(259 / 4e5) | 0.91 |
| 抖动主导,两路 3 ps、无跟踪 | 1.17e-4 | 1.00e-4(100 / 1e6) | 0.85 |
| 噪声 40 mV | 4.13e-5 | 2.25e-5(9 / 4e5) | 0.54(9 个误码的散布) |

示例 03(2e7 符号):噪声主导 1e-6 处 1.23(24 误码)、抖动主导 1e-6 处 1.22(16 误码)、混合 1e-5 处 0.87(17 误码 / 2e6)。

## 决策记录

- 眼高定义:上下两个半眼各自在目标 BER 处的边界之和(`vref_offset_v` ≠ 0 时不对称)。
- 噪声加在采样点(每符号一个高斯样本),两边口径一致;没有建接收带宽对噪声的整形。

## 教训

- Gauss–Hermite 节点在抖动主导时偏 2.19×,见 `engineering-pitfalls.md`。
- 时域分块越界,见同文件。
