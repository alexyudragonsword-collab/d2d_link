---
type: project_topic
status: active
summary: "开工前读:本库已经付过代价的坑。"
tags: [pitfalls]
contains: [lesson]
created: "2026-10-12"
updated: "2026-10-13"
related: [engines.md, forwarded-clock.md]
authoring_mode: ai_generated
---
# 工程坑(已付代价)

## 时域引擎分块时采样点越界(2026-10-12,里程碑 1)

- 现象:200k 符号 11 个误码,统计引擎说是 0;误码全在每块最后 5–6 个符号,采样值是满幅的**反号**。
- 原因:主光标在脉冲里延迟 i0 ≈ 5.8 UI(25 mm 走线的传播延时),块尾符号的采样点落在该块波形之外,`np.interp` 钳到末值。
- 改法:每块多生成 `n_pre = ceil(i0/osr) + 1` 个"未来"符号参与卷积(同时补齐前光标 ISI),历史只保留真正的过去符号。
  `tests/test_timedomain.py::test_chunking_does_not_change_the_result` 守着:块大小 7000 与 60000 误码数必须相同。

## 抖动平滑用 Gauss–Hermite 节点会在抖动主导时偏 2×(2026-10-12)

- 现象:σ_j = 0.136 UI、噪声 3 mV 时时域 / 统计 = 2.19。
- 原因:被积函数是浴盆曲线,在眼边缘近似阶跃;21 个 Hermite 节点间距约 0.5σ,跨过阶跃时权重分配粗糙。
- 改法:改为均匀网格梯形积分,步长 ≤ σ/4 且是浴盆网格的整数细分(ISI 模型按相位缓存共用),范围 ±12σ(1e-27 要 10.8σ)。
  改后同一点 0.85×。`sim.stat_jitter_sigmas` 是这个范围。

## 平顶脉冲的"峰值"取到了平顶左缘(2026-10-12)

- 现象:无 ISI 的矩形脉冲测试里眼宽只有 0.52 UI、浴盆不对称、抖动闭式差 40×。
- 原因:`argmax` 对平顶返回第一个样本,相位 0 落在平顶左缘,浴盆窗口 ±0.5 UI 只看到半只眼。
- 改法:`LinkResponse.main_index` 取 ≥ (1 − 1e-9)·max 的样本的中点。有损信道只有一个峰,结果不变。

## BER 恰为 0 的平坦区里 argmin 不是眼中心

- 现象:低噪声时浴盆大片恰为 0,`argmin` 返回第一个 0,采样相位 −0.30 UI,时域在那里反而数到误码。
- 改法:采样相位取"目标 BER 处眼开区间的中点"(眼居中跟踪器的行为);眼闭合时才退回 argmin。

## 无损理想线的脉冲会过冲 13%(Gibbs)

- 频率网格到 f_max = osr/(2 UI) 处砖墙截断;无损线就是纯延时,冲激是 sinc。物理驱动器有带宽,bundled 配置给 `tx.bw_hz = 60 GHz`;
  测试用光标之和(= DC 响应)而不是峰值来核对幅度。

## 慢漫游下的误码成簇,误码数不是样本量(2026-10-12,里程碑 2)

- 现象:纯漫游工作点(5 ps/路径、3 MHz 角、2 MHz 跟踪器)时域 113 个误码,比统计低 0.30×。
- 原因:残余抖动集中在 2–10 MHz,相干时间 ~200 ns = 6400 个符号;2e6 符号里只有几百个独立样本,3.6σ 的越界事件期望不到 1 个,
  113 个误码来自一两次越界。Poisson 区间按独立误码算,完全失真。
- 改法:`TimeResult.error_bursts`(间隔 > 64 符号算新簇)随结果报;一致性工作点让接收噪声参与,把误码去相关。
  判据:簇数 ≥ 25 才拿来比。

## 铁律 6 连求和顺序都管(2026-10-12)

- 现象:预算函数改成统一的 `rms(spectrum)` 后,M1 指纹里 `sigma_jitter_s` 末位变(…3095e-12 → …30954e-12),浴盆全变,时域相位随之变。
- 原因:`Σ(e·w)·df` 与 `Σe·df·w` 浮点结果不同;量化步长由 σ 决定,末位差一路放大。
- 改法:白噪项保持"先 Σ|E|²·df 再乘 PSD"的原顺序;新项(本地 PLL、漫游)在为零时直接写 0.0 而不走求和。
  同类:时域 padding +1 → +2 改了符号流对齐,也让指纹变;回退。重构 PR 的 compare 输出里只许出现"None → 新键"。

## 平顶脉冲第二次把眼截成一半(2026-10-13,里程碑 3)

- 现象:先进封装 2 mm 在 4–16 GT/s 眼宽 0.50–0.75 UI、眼高 320 mV,判 FAIL。
- 原因:M1 的"平顶中点"只在严格等值的平顶上生效;60 GHz 驱动极点让平顶微倾,`argmax` 又回到平顶末端,整只眼落在 −1..0 UI,
  ±0.5 窗口只看到一半。
- 走错的一步:以为 BER 对相位以 1 UI 为周期、可以把浴盆当环形找最宽开眼区 —— 实现后 ber[−0.5] = 0、ber[+0.5] = 0.5。
  BER 是判决**本符号**的误码率,偏一个 UI 采到邻符号就是 0.5,不周期。
- 改法:`bathtub_around_the_eye` —— 开眼区碰到窗口边就向该侧再扩 0.5 UI(每侧最多一次);未触边的配置逐位不变。
  `tests/test_statistical.py::test_bathtub_window_follows_a_flat_topped_eye`。

## Touchstone 文件没有直流点(段 6,2026-10-13)

- 现象:任何 `channel.kind: touchstone` 信道的 H(0) = 0,脉冲带长负尾;合成的 25 mm 文件眼 182 → 60 mV。M1 起存在,无示例使用,测试只查带内 |H|。
- 原因:vendored `interp_s2p` 对带外传输项填 0(PyBERT 的保守做法,针对高频),而本库的网格从 DC 开始,DC 也在带外。
- 修法:`channel/model.py::fill_dc` —— 带内最低两点按 √f 外推 log|H| 到 DC,上限 1、不低于最低点,实数;两种读法都走它。
- 教训:读取路径的测试要看到**光标和 / 主光标**,不只看带内幅度;合成测试文件要用有损线,无损线在带边振铃(69 个 1.5 mV 光标)会掩盖真正的缺陷。


## 解析走线非因果:√f 皮肤电阻没有配套的内电感(段 9b,2026-11-02)

- 现象:x1 25 mm 的脉冲在 LC 到达之前就有能量(到达时刻 6.5 % 主光标、提前一整个 UI 处 2 %);σ_ISI 偏低 3.4 mV;眼 215.6 mV / 0.774 UI 虚高到
  209.7 / 0.761;示例 02 的 "reach 35 mm、1.40×" 是它的产物。M1 起存在,第一次体检的 8 条高严重度和所有探针都盯幅度(|H|、光标和),没有一个看"到达前的能量"。
- 原因:vendored `analytic.skin_effect_rlgc` 给 R = R_dc + R_skin√f、L 常数。表面阻抗是 (1 + j)·R_skin√f:电阻的 √f 项必然带一个同大小的
  内电抗,即 L_int = R_skin/(2π√f)。只取实部的 H(f) 违反 Kramers–Kronig,相位是纯 LC 延时,幅度却随 f 下降,逆变换非因果;同时丢掉有损线的
  群延时色散 —— 后光标 ISI 的主要来源。
- 修法:`ChannelModel.from_rlgc` 在 L 上加 `r_skin / (2π√f)`(DC 点电抗为零,不需要值),不改 vendor;`channel.skin_inductance: false` 复现旧模型。
  `tests/test_channel.py::test_analytic_line_is_causal` 守"提前一个 UI 处的能量 < 0.5 % 主光标"。上游 Halo_Serdes 同一问题,报告见 LOG。
- 教训:**模型级的检查要看守恒 / 因果 / 互易这类结构性质**,不只看数值与另一引擎的一致 —— 两个引擎共用同一个脉冲,铁律 3 永远抓不到脉冲本身的错。

## 脉冲时间窗与光标数是仿真参数,不该写死(段 9b)

- 现象:`channel.n_freq = 2048` 给 128 UI 的循环窗,窗末尾仍有主光标的 3.5e-3;`read_cursors` 的 `n_max = 64` 写死,统计引擎丢掉 +64 UI 之后的 62 个光标
  (RSS 0.86 mV)而时域引擎全保留。两个误差部分抵消,x1 净 0.8 mV / 5e-4 UI。
- 修法:`n_freq` 默认 8192(512 UI),`sim.stat_cursor_reach`(256)与 `sim.stat_cursor_floor`(1e-6 × 峰值,旧 1e-9)进 `SimConfig`;
  收敛测试 `test_pulse_window_and_cursor_reach_are_converged`(8192 → 16384:眼宽 < 2e-4 UI、眼高 < 0.3 mV)。
- 坑:窗变长后 1e-9 的光标门限把串扰脉冲 1e-8 的尾全留下,x16 模块 29 → 84 s;门限 1e-6(0.2 µV 对 50 µV 的 bin)眼不变到 1e-3 mV,回到 50 s。

## Touchstone 带外砖墙(段 9b)

- 现象:有损文件截到 50 GHz,眼宽比闭式同一条线少 0.016 UI(x1 裕度的三分之二);100 GHz 截断眼高 +7 mV。vendored `interp_s2p` 把带外传输项填 0,
  本库网格到 512 GHz。ROADMAP 一直写"只测过无损文件",无损线带边本来就振铃,看不出砖墙。
- 修法:`channel/model.py::extend_band` —— 直通路径带边以上 log|H| 按最后十倍频的斜率线性延拓(不升)、相位按同一段的群延时延拓。50 GHz 截断眼宽差 +0.002 UI,100 GHz −0.0002。
  段 11 补上耦合项(`extend_band_like`:沿直通路径的衰减,X(f_edge)·H(f)/H(f_edge));9b 时给耦合项留的 0 填充在有损耦合的合成文件上量出 −3.5 mV / +0.010 UI,
  按耦合项自己的斜率延拓 +0.006 UI、沿直通 +0.005 UI(眼高差 0.1 mV),取后者。`test_touchstone_band_is_extended_past_the_file`、`test_touchstone_coupling_follows_the_through_path_past_the_band`。
