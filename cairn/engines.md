---
type: project_topic
status: active
summary: "统计引擎(主)与时域引擎(校核)各自怎么算、为什么能到 1e-27、2× 判据在哪些点上量过。"
tags: [statistical, time-domain, ber]
contains: [decision, lesson]
created: "2026-10-12"
updated: "2026-10-13"
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
- 采样相位:目标 BER 处最宽开眼区的中点(眼居中跟踪器);配置可固定。眼高用同一套尾和二分求;眼宽按 log BER 内插。
  窗口 ±0.5 UI,开眼区触边时向该侧再扩 0.5(M3);BER 对相位**不**周期(偏 1 UI 采到邻符号,0.5)。
- 枚举 10 与 16 个光标差 < 5%(25 mm、噪声 40 mV)。

**时域引擎**(`engine/timedomain.py`)不近似统计引擎假设的任何东西:同一脉冲(fftconvolve)、同一噪声(采样点上加)、
同一抖动谱(`ForwardedClock.synthesize` 的逐符号残余);分块含过去 n_tail 与未来 n_pre 符号。PRBS 按 t 位一步向量化。

## 2× 判据量到的点(25 mm、32 GT/s、`tests/test_engines.py`)

| 工作点 | 统计 BER | 时域 BER(误码数) | 比 |
|---|---|---|---|
| 噪声主导,50 mV | 7.09e-4 | 6.48e-4(259 / 4e5) | 0.91 |
| 抖动主导,两路 3 ps、无跟踪 | 1.17e-4 | 1.00e-4(100 / 1e6) | 0.85 |
| 混合:噪声 45 mV + 两路 2 ps、无跟踪 | — | ≥ 25 误码 | 0.5–2× 内(`test_mixed_noise_and_jitter_within_2x`;早期 40 mV 的 9 误码点 0.54 已换掉) |

示例 03(2e7 符号):噪声主导 1e-6 处 1.23(24 误码)、抖动主导 1e-6 处 1.22(16 误码)、混合 1e-5 处 0.87(17 误码 / 2e6)。

## 里程碑 2 的点(`tests/test_engines_m2.py`、`tests/test_xtalk.py`、示例 06)

| 工作点 | 比 | 备注 |
|---|---|---|
| 本地 PLL 有色时钟噪声(两剖面 +30 dB,噪声调到 1e-5) | 0.92(36 / 4e6) | 抖动 3.0 ps = 0.097 UI |
| 量化(1/32 UI)+ 4 UI 延迟跟踪器 | 0.74(29 / 4e6) | 量化在统计里是矩形核卷积 |
| x3 模块 −14 dB 串扰,中间 lane | 0.86(56 / 2e6),边 lane 0.90 / 0.92 | 串扰光标与 ISI 同等枚举 |
| 先进封装 2 mm + CTLE 3 dB + 0.06 UI DCD | 0.80(31 / 4e6) | |
| 漫游 2.5 ps/路径、3 MHz 角、2 MHz 跟踪 + 噪声 38 mV | 0.82(32 / 4e6,31 簇) | 第一次纯漫游 5 ps 的点 0.30(113 误码只有几簇):不是引擎不一致,慢漫游让采样点一次偏出几千符号,簇数才是样本量 |

## 决策记录

- 眼高定义:上下两个半眼各自在目标 BER 处的边界之和(`vref_offset_v` ≠ 0 时不对称)。
- 噪声加在采样点(每符号一个高斯样本),两边口径一致;没有建接收带宽对噪声的整形。
- 串扰(M2):攻击 lane 的符号与受害 lane 独立,所以串扰光标在统计里就是额外的 ±1 干扰项;时域给每个攻击 lane 独立 PRBS、
  脉冲按相对 skew 做分数延迟(线性内插,与统计读光标的方式一致)。
- 时域的 Poisson 置信区间以误码独立为前提;`error_bursts` 远小于 `n_errors` 时区间无效。

## 教训

- Gauss–Hermite 节点在抖动主导时偏 2.19×,见 `engineering-pitfalls.md`。
- 时域分块越界,见同文件。
