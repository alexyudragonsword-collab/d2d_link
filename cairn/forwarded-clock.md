---
type: project_topic
status: active
summary: "前向时钟模型的方程、带宽/相关度/树延时三个极限、闭式与合成的一致性,以及有意不建的部分。"
tags: [forwarded-clock, jitter, core-mechanism]
contains: [decision, lesson]
created: "2026-10-12"
updated: "2026-10-12"
related: [architecture-invariants.md, engines.md]
authoring_mode: ai_generated
---
# 前向时钟:收端看到的是差

## 当前结论

模型(`src/d2d_link/clock/forwarded.py`,单位秒,按 UI 采样):

```
t_data[k] = c[k] + n_d[k] + w_d[k]                             每 lane 一份 n_d(白)、w_d(漫游)
t_in[k]   = ρ c[k] + sqrt(1−ρ²) c'[k] + n_k[k] + w_k[k]       每模块一份
t_pll     = h_pll ⊛ t_in + (1 − h_pll) ⊛ ℓ                     本地 PLL 锁到前向时钟(里程碑 2)
t_rx[k]   = (h_tree ⊛ t_pll)[k − τ] + n_t[k]                   树:延时 τ + 一阶低通 f_tree
Δ[k]      = t_data[k] − t_rx[k]
θ[k]      = θ[k−1] + α (Δ[k − d] − θ[k−1])                    跟踪器,α = 1 − exp(−2π f_track UI),延迟 d
ε[k]      = Δ[k] − Q(θ[k])                                     Q:相位插值器步长 pi_step_ui
```

- 本地 PLL(`local_pll_*`):二阶 II 型环路,H(s) = (2ζω_n s + ω_n²)/(s² + 2ζω_n s + ω_n²),ω_n = 2π·`local_pll_bw_hz`。
  前向相位走 H、本地振荡器噪声 ℓ 走 1 − H。**永远锁定**:配了本地 PLL 就必须给带宽(schema 拒绝自由运行)。
  带宽 → ∞ 残余 → 0(ℓ 完全被压掉);带宽 → 0 残余² = 发端 PLL 带内功率 + 本地 PLL 带内功率(两个独立时钟)。
  这才是原始简报里"跟踪带宽 → 0 时残余 → 两路独立抖动之和"的物理含义;M1 的白路径噪声版只是它的退化情形。
- 漫游 w(`*_wander_s` + `wander_corner_hz`):一阶整形 S0/(1 + (f/fc)²),在块网格上归一到给定 RMS。是 MHz 级跟踪器存在的理由:
  500 fs 漫游(1 MHz 角)经 20 MHz 跟踪器剩 111 fs,同样 RMS 的白噪只剩 95%。
- 跟踪器延迟 d:L(z) = α z^{−d}/(1 − (1−α) z^{−1});d ≥ 1 且 α → 1 时变微分器(白噪残余 √2 倍)。
- 量化 Q:均匀 ±step/2,方差 step²/12,与线性预算功率相加(合成验证 5% 内);统计引擎在相位轴上把高斯核与宽 step 的矩形卷积。

- `c` 是 PLL 的定时抖动(pllsim 剖面:S_φ/(2πf0)²,f0 用剖面自己的载波;或白噪 `pll_rj_s`),`c'` 是同谱的独立实现,
  ρ = `clocking.correlation`。ρ = 1、理想树、无路径噪声时 Δ ≡ 0 —— 这是铁律 2 的零点,测试要求闭式与合成都恰为 0。
- 三个极限(`tests/test_forwarded_clock.py`):f_track → ∞(α = 1)残余 0;无跟踪器(α = 0)残余² = σ_d² + σ_k²(+ σ_t²);
  ρ = 0 时残余 = √2 × PLL 带内 RMS(两个独立时钟)。
- 树的延时把共模部分按 |1 − e^{−jωτ}| 泄漏(微分器),树带宽按 |1 − H_tree| 泄漏高频共模;两者在 ρ = 1 时是残余的唯一共模来源。
- 闭式(`ForwardedClock.budget`)与合成(`synthesize`)用**同一张 FFT 网格**(块长 `sim.jitter_block`,频带 [fs/N, fs/2]),
  统计引擎与时域引擎因此看同一段谱。全开(ρ 0.9、三路噪声、树 40 ps / 12 GHz、2 MHz 跟踪)时合成 RMS 与闭式差 < 5%。

## 决策记录

- **跟踪器默认零延迟**:θ 用当前 Δ 更新。有延迟的一阶环路在 α → 1 时变成微分器(残余 = Δ[k] − Δ[k−1],白噪声下功率反而翻倍),
  与"带宽 → ∞ 残余 → 0"的验收矛盾;作为"差的低频部分被跟掉"的行为级抽象,零延迟是正确的。里程碑 2 起延迟(`track_delay_ui`)
  与量化(`pi_step_ui`)是可配项,默认 0 保持 M1 逐位不变。
- **剖面 f0 不从数据率推**:10.24 GHz 的 SSPLL 剖面驱动 16 GHz DDR 前向时钟,秒数按剖面载波算(分频/倍频保秒数)。
  `clocking.pll_f0_hz` 只改相位到秒的比例,不改曲线。
- **白噪声路径项按每边 RMS 给**(`*_rj_s`),一侧 PSD = 2σ²/fs;与剖面在同一网格上相加。

## 教训

- 2026-10-12:ρ = 0 时合成 RMS 比闭式高 8%(285 vs 263 fs),ρ = 1 的三路噪声情形差 0.1%。原因是 1/f² 主导的剖面在
  块长 2^18 UI 下最低几个 bin 各是单次 χ²(2) 抽样,一次实现的 RMS 散布本来就有百分之十几(Halo `docs/clock_profile.md` 同一现象)。
  测试对纯共模泄漏用 5% 容差且选 τ ≠ 0 的高通情形;对 ρ < 1 不做严格 RMS 断言。

## 开放问题

- 前向时钟的占空比误差只做了偶/奇采样相位偏移(`dcd_ui`),没有建占空比的随机部分。
- 树带宽对**数据边沿**的等效滤波没有建(只滤了时钟相位)。
- 本地 PLL 的环路是线性 II 型二阶;锁定范围、周跳、分频比对相噪的折算都没有建(秒数按剖面载波算)。
