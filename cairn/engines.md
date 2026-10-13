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

- 采样值 = 主光标 + Σ c_k b_k + 噪声。ISI 分布在电压网格(`sim.stat_isi_bin_v`,默认 50 µV)上**精确**地逐光标移位相加:
  每个光标(本 lane 的与邻 lane 串扰的同等对待)把分布分成两份半权重、各移 ±c_k,分数移位按线性内插分到相邻两格(均值精确,
  方差每光标最多多 f(1−f)·bin²)。一个光标也不丢、不并方差。唯一近似是 bin,bin 减半就是收敛检验(段 1):x5 耦合中间 lane
  349 个光标,bin 100/50/20/10 µV → 眼宽 0.6844/0.6848/0.68488/0.68490 UI,眼高 138.5/138.8/138.83/138.84 mV。
  旧的"枚举最大 12 个 + 高斯余项"在同一点给 0.671 UI / 137.5 mV 且随 M 不收敛(8/12/16 → 0.613/0.671/0.683)—— 悲观 0.014 UI。
- 误码率 = 分布各格 × 高斯尾,在 **log 域**求和(`log_ndtr` + logsumexp 的 numpy 实现;scipy 的 `logsumexp` 每次调用开销 0.5 ms,
  被调用两万次时占一半运行时间)。`StatResult.log10_ber` 是原始量,`ber = 10**log10_ber`(低于 1e-308 为 0.0,排名只看 log10)。
  不用 FFT 卷积 PDF —— 那在峰值 1e-16 以下没有精度,到不了 1e-27;也不用线性域 `erfc` —— 1e-27 链路每个 lane 自家眼中心的 BER
  都在 10^-400 量级,`erfc` 下溢成恰好 0.0,最差 lane 永远是 lane 0(段 0 体检的头号问题)。
- 决策阈值处的尾对每个 ISI 模型只算一次并缓存(浴盆相邻相位的抖动偏移落在同一细网格上):x1 一个 lane 2.8 s(旧枚举 3–4 s);
  段 3 的眼边求根落在细网格之外(模型不命中缓存),每 lane 多约 1.8 s → 4.6 s,段 4 把求根相位贴到细网格上。
- 采样抖动在相位轴上做:残余的高斯部分 σ_j(`ForwardedClock.budget().gaussian_s`,闭式)作高斯核,BER(φ) = Σ_j w_j BER0(φ + δ_j),
  δ 均匀网格、步长 ≤ σ/4 且是浴盆网格的整数细分(不细于 base/256)、范围 ±12σ(+2 个保护节点);PI 量化是矩形核、剖面杂散是反正弦核
  (段 3,远小于 σ 的并入方差),三者卷积。DDR 占空比误差(收端 `dcd_ui` + 有本地 PLL 时的发端 `tx_dcd_ui`)是两个相位平均。
  深处(1e-100 以下)的浴盆数值由核最外的节点决定,不是物理量;眼宽边界的 1e-27 处不受影响(段 3 已验证)。
- 采样相位:目标 BER 处最宽开眼区的中点(眼居中跟踪器);配置可固定。眼高用同一套尾和二分求。眼宽的两条边(段 3 起)在**真实浴盆上**
  用安全的 regula falsi(Illinois)求 BER = 目标的相位(容差 1e-5 UI,每条边约 5 次求值),不再在两个网格点之间按 log BER 内插:
  眼边外侧的网格点可能低一百个数量级、由抖动核最外的节点决定,内插出的边随网格密度与核的范围漂 2e-3 UI(16 点网格)。
  现在 16 与 128 点网格的眼宽相同到 1e-5(x1 0.77408 UI)。窗口 ±0.5 UI,开眼区触边时向该侧再扩 0.5(M3);
  BER 对相位**不**周期(偏 1 UI 采到邻符号,0.5)。
- 相位参考(段 1):`LinkResponse.main_index` 是脉冲**半幅宽的中点**,不再是峰值样本 —— 峰值在平顶脉冲上三次把窗口带偏
  (M1 左缘、M1 argmin、M3 末端)。bundled 配置的 `phase_ui` 因此整体平移(x1:−0.0198 → 见 LOG),眼高 / 眼宽不变。
- 眼宽**硬上限 1 UI**:一个符号的眼不可能比符号宽,读出 > 1 的是无发端极点的短线在带边的 Gibbs 振铃(0–1 mm 无 `tx.bw_hz` 时
  原始读数 1.026 UI)。截断后 `extras["eye_width_clipped"] = True`、原值在 `eye_width_raw_ui`、`summary()` 打 "(clipped)"。

**时域引擎**(`engine/timedomain.py`)不近似统计引擎假设的任何东西:同一脉冲(fftconvolve)、同一噪声(采样点上加)、
同一抖动谱(`ForwardedClock.synthesize` 的逐符号残余);分块含过去 n_tail 与未来 n_pre 符号。PRBS 按 t 位一步向量化。
段 4:超过 2^24 符号时抖动按块流式合成(`synthesize_blocks`),2.5e9 符号不再需要 20 GB;`sim.time_mode: samples` 只算采样值
(每符号的光标按它自己的采样瞬间线性内插后与符号序列点乘,与波形路径的 `np.interp` 同一算术,误码逐个相同、样本差 1e-12 V),
唯一近似是 `time_cursor_floor`(默认 1e-6 × 主光标)—— 但 25 mm 有损线的脉冲尾在 130 UI 内都高于它,光标一个不少,所以**不比 FFT 波形快**
(1e6 符号 9 s 对 6 s);只在短记忆信道上(先进 2 mm、floor 1e-4:47 个光标,1.5 s 对 5.9 s)有意义。结论:FFT 波形路径在 numpy 里已接近最优,
"快 10–50×"的预期不成立。

## 2× 判据量到的点(25 mm、32 GT/s、`tests/test_engines.py`)

| 工作点 | 统计 BER | 时域 BER(误码数) | 比 |
|---|---|---|---|
| 噪声主导,50 mV | 7.09e-4 | 6.48e-4(259 / 4e5) | 0.91 |
| 抖动主导,两路 3 ps、无跟踪 | 1.17e-4 | 1.00e-4(100 / 1e6) | 0.85 |
| 混合:噪声 45 mV + 两路 2 ps、无跟踪 | — | ≥ 25 误码 | 0.5–2× 内(`test_mixed_noise_and_jitter_within_2x`;早期 40 mV 的 9 误码点 0.54 已换掉) |

示例 03(2e7 符号):噪声主导 1e-6 处 1.23(24 误码)、抖动主导 1e-6 处 1.22(16 误码)、混合 1e-5 处 0.87(17 误码 / 2e6)。

## 深一致性(段 4)

| 点 | 符号数 | 用时(本机) | 在哪 |
|---|---|---|---|
| 1e-6,噪声主导 25 mm | 2.5e7 | ~3 min | `tests/test_engines.py::test_one_in_a_million_point_within_2x`(套件) |
| 3e-8,同一链路 | 1e9 | ~1.75 h | `tests/test_engines_deep.py`(`pytest -m slow`;每周 `examples-full.yml` 的 `deep`) |
| 1e-8(25 误码) | 2.5e9 | ~5 h | 同一测试,`D2D_DEEP_SYMBOLS=2500000000 D2D_DEEP_BER=1e-8`,手动 |

统计引擎(段 4 的逐位不变优化):`_shift_add` 对 |c| < bin 的光标合并两次加法(a + a 精确)、尾的标量路径不再 reshape、
`_logsumexp` 一维快路径、模型缓存上限 5 万;`run_link` 对邻接与残余 skew 相同的 lane 复用结果(x16 内侧 6 个 lane 一次算完)。
x1 每 lane 4.6 → 4.2 s;指纹 2698 项逐位相同(`fp_p3` → `fp_p4a`)。还在的热点:眼边求根的模型不命中缓存(每 lane ~1.8 s)、
`half_eye` 60 步二分 —— 改它们都会动数字,留给下一次"数字会变"的段。

## 里程碑 2 的点(`tests/test_engines_m2.py`、`tests/test_xtalk.py`、示例 06)

| 工作点 | 比 | 备注 |
|---|---|---|
| 本地 PLL 有色时钟噪声(两剖面 +30 dB,噪声调到 1e-5) | 0.92(36 / 4e6) | 抖动 3.0 ps = 0.097 UI |
| 量化(1/32 UI)+ 4 UI 延迟跟踪器 | 0.74(29 / 4e6) | 量化在统计里是矩形核卷积 |
| x3 模块 −14 dB 串扰,中间 lane | 0.86(56 / 2e6),边 lane 0.90 / 0.92 | 串扰光标与 ISI 同等进入分布(段 1 前是同等枚举) |
| 先进封装 2 mm + CTLE 3 dB + 0.06 UI DCD | 0.80(31 / 4e6) | |
| 漫游 2.5 ps/路径、3 MHz 角、2 MHz 跟踪 + 噪声 38 mV | 0.82(32 / 4e6,31 簇) | 第一次纯漫游 5 ps 的点 0.30(113 误码只有几簇):不是引擎不一致,慢漫游让采样点一次偏出几千符号,簇数才是样本量 |

## 决策记录

- 最差 lane(段 1):按**相对裕度最小**取 —— `min(眼高裕度/目标, 眼宽裕度/目标)`,`StatResult.margin`;并列取编号小的。
  `LinkResult.log10_ber_worst` 按 log10 取最大。不能按 BER 排:见上。`consistency_ratios` 用 log10 差计算,统计 BER 不可达时才给 inf。
- 静态 skew 与跟踪器的口径(段 1):有每 lane 跟踪器(`track_bw_hz > 0`)时静态偏差是环路的直流,被完整跟掉,残余 skew = 0,
  只剩 PI 量化(已作均匀抖动项);无跟踪器时一次性 deskew 留下 skew 模步长。之前两者同时计入(双算)。
  `standard_32g_x16_module`(2 MHz 跟踪器、1/64 PI)因此每个 lane 的残余 skew 归零 —— 见 LOG 的数字。
- 时域引擎的分块填充(段 1):`n_tail` / `n_pre` 按实际采样相位 + skew + DCD + |抖动|max 加余量;采样点越界时 **assert**
  而不是让 `np.interp` 静默钳位(旧代码越界只多 1 个符号的余量,窗口扩到 ±1 UI 的眼可能踩到)。

- 眼高定义:上下两个半眼各自在目标 BER 处的边界之和(`vref_offset_v` ≠ 0 时不对称)。
- 噪声加在采样点(每符号一个高斯样本),两边口径一致;没有建接收带宽对噪声的整形。
- 串扰(M2):攻击 lane 的符号与受害 lane 独立,所以串扰光标在统计里就是额外的 ±1 干扰项;时域给每个攻击 lane 独立 PRBS、
  脉冲按相对 skew 做分数延迟(线性内插,与统计读光标的方式一致)。
- 时域的 Poisson 置信区间以误码独立为前提;`error_bursts` 远小于 `n_errors` 时区间无效。

## 教训

- Gauss–Hermite 节点在抖动主导时偏 2.19×,见 `engineering-pitfalls.md`。
- 时域分块越界,见同文件。
