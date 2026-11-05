---
type: project_topic
status: active
summary: "lane 间串扰怎么建:FEXT 的行为级 / 耦合线估计、带状线为什么没有一阶 FEXT、反向 lane 的 NEXT、单端多端口 Touchstone 的读法,以及哪些数只是估计。"
tags: [crosstalk, fext, next, stripline, touchstone]
contains: [decision, lesson]
created: "2026-10-13"
updated: "2026-11-05"
related: [architecture-invariants.md, engines.md, spec-sources.md]
authoring_mode: ai_generated
---
# 串扰

## 当前结论

三条路径,同一个引擎接口(`LinkResponse.xtalk_pulses[key]`,key 是邻接距离 1 / 2 或 `"next"`;统计引擎把串扰光标当独立 ±1 干扰项,
时域给每个攻击 lane 自己的 PRBS):

- **`xtalk: fext`**(M2):行为级 —— 幅度 `xtalk_adjacent_db`(预设 −30 / −24 dB,`source: model`),形状 j·sin(2πfτ)(0.13.6;此前 k√2·u/(1+u),见下)。
- **`xtalk: coupled`**(M3):一阶耦合微带估计 —— κ = 1/(1 + (s/h)²)、速度失配 (1 − ε_eff/ε_r)、幅度随耦合长度线性增长、Nyquist 处取值、
  sin(2πf_Nτ) 不超过 0 dB(0.13.6 前线性取值、上限 −3 dB)。标准封装 25 mm:**−18.7 dB**(之前 −18.6),先进 2 mm −56.9 dB。bump 间距是 `source: survey`,叠层是 `source: model`。
- **远端形状(0.13.6,第三次体检 P1 #4)**:弱耦合对的偶、奇模延时差 2τ,相对平均延时的直通路径,受害方远端是 **X/H = j·sin(2πfτ)** ——
  2πfτ ≪ 1 时就是攻击方的导数(耦合线一阶 j2πfτ),永不超过 1。τ 由 Nyquist 处的配置 / 估计电平定。此前的 k√2·u/(1+u)(u = jf/f_N)
  在 Nyquist 以下高 3 dB、以上饱和:它在采样点也有大的串扰,而导数在对齐攻击方的脉冲峰附近为零、在边沿最大。
  后果:**眼高涨、眼宽跌**。x5 中间 lane 137.8 / 0.590 → 193.3 mV / 0.575 UI,采样点串扰 RMS 14.3 → 3.3 mV;x16 模块最差 lane 216.2 / 0.712(lane 5)
  → 226.3 / 0.693(lane 4),串扰费从 23.2 mV / 0.022 UI 变成 2.2 mV / 0.041 UI;x64 spare 最小眼宽 0.670 → 0.599 UI。判定都不变(FAIL)。
- **受害方自己的直通(0.14.1,第四次体检)**:同一个两模图景给邻 lane 的信号留下 j·sin(2πfτ),给受害方自己的信号留下 **cos(2πfτ)**
  (偶、奇模之和的一半,cos² + sin² = 1)。此前直通只用 H。每条一位、两位以内的**物理**线都算(不论是否驱动:失效 lane、闲置 spare 照样分模),
  每对各乘一个 cos(到 τ² 阶正确,估计本身就只到这一阶);边缘 lane 少;单 lane、`none`、`touchstone`(文件自带直通)不变。
  `channel/model.py::through_factor`、`lane_response`,`engine/lanes.py::coupled_lines`;run_link 按 (一位, 两位) 线数各建一个响应。
  物理图:受害方自己的脉冲劈成两半、相隔 2τ(−18.7 dB 时 2.3 ps = 0.074 UI),所以伤眼宽多于眼高、伤边沿受串扰少的 lane 更多。
  数字:x5 中间 lane 0.5753 → 0.5715 UI(193.3 → 193.2 mV),lane 1 0.6196 → 0.5974(它的右边沿原本不被串扰限制,劈开的脉冲直接吃掉它);
  x16 模块(−30 dB)最差 lane 0.6928 → 0.6927;x64 + FEXT 最小 0.599 → 0.601。判定都不变。示例 12:x5 缺口 0.312 → 0.316,串扰份额 45 → 48 %。
- **线数与口径(0.14.7,第五次体检余项)**:`coupled_lines` 把 `reverse_adjacent` 边缘外的回程 lane 算作一位的线(回程模块更远的 lane 不建模,与 NEXT 同);每 lane 响应的 `channel` 带上 cos,插损列是耦合环境里的线(x5 中间 lane 32 GT/s −2.75 → −2.88 dB),网格顶也按它重算;单 lane 加 spare 时敏感性与归因按物理线数看串扰;单 lane 入口(`run_statistical` 等)在多 lane 行为级串扰配置上不给响应时告警。示例 08 边缘 lane 加 NEXT:0.615 → 0.613、0.650 → 0.647 UI。
- **按 lane 读文件(0.14.4)**:文件的单端 lane 数等于模块物理线数(`count + spare_count`)时,`run_link` 给每条物理 lane 读它自己的直通与邻线(`engine/lanes.py::file_per_lane`);别的 lane 数仍当代表性线组,全部读 `channel.lane`。0.14.1 起行为级路径的直通随线数不同,此前的读法让示例 08 的中间 lane 差 0.21 mV,现在 0.02 mV。
- **`xtalk: touchstone`**(段 6):单端 2N 端口文件自己的耦合项 —— 端口 1..N 是 lane 0..N−1 的近端、N+1..2N 远端;`channel/touchstone_se.py`
  对每个 2 端口子网络用 vendored 的内插与端接(其余端口按文件参考阻抗端接,这是唯一近似),距离 d 取两侧较强的那条。合成无损 3 lane 文件上
  读回 |H| = 1、耦合 Nyquist 处 0.0707 对 0.0707、lane 间互易。**真实封装 S 参数仍然没有**(ROADMAP P1 #2):读法就位,数据缺位。
  段 9b:文件带边以上直通路径不再是砖墙(`extend_band`,见 `engineering-pitfalls.md`);段 11:耦合项带外沿直通路径的衰减延拓(`extend_band_like`:X(f) = X(f_edge)·H(f)/H(f_edge),耦合形状在高频转折、自身斜率不可信,与直通共享的衰减可信)—— 有损耦合的合成 3 lane 文件截到 50 GHz,中间 lane 眼从差 3.5 mV / 0.010 UI 到差 0.1 mV / 0.005 UI,剩下的是直通路径自己的延拓误差;报告层的 crosstalk 段对这种模式
  给文件自己的 Nyquist 耦合、`adjacent_source: file`(之前打的是预设 −30 dB 的 "model" 标签)—— 数字来自 lane 的 `extras["xtalk_adjacent_db"]`。

**带状线**(`channel.routing: stripline`):均匀介质,ε_eff = ε_r,奇偶模同速,一阶 FEXT 为 0(估计给 −300 dB 下限);同几何的线更慢
(L、C 由 ε_r 推出)。NEXT 系数在带状线是 κ/2、微带 κ(1 + ε_eff/ε_r)/4(0.13.3 起;之前 κ/4,与布线无关)。**到 0.11 为止,「32 GT/s 标准封装不过」是微带假设的产物**:同几何布成带状线就过(0.761 UI)。段 9b 走线因果化后带状线也差 0.002 UI 不过(0.748 UI,示例 08),微带 0.633 UI;0.13.0(PLL 底噪、色散介质)带状线 0.717、微带 0.590 UI;0.13.6(FEXT 形状)微带 0.575 UI。结论(0.13,对 0.75 UI):标准封装 25 mm 在 32 GT/s 下本库的每个模型变体都不过,串扰只决定差多少。**0.14.0(0.65 UI 分档,二手转述未核实)起又成了布线假设**:微带中间 lane 0.575 UI 不过(0.14.1 加直通 cos 后 0.572)、带状线 0.717 UI 过(示例 08)。

**近端串扰**(`channel.xtalk_next`,段 6):模块边缘的 lane 旁边是回程模块的 lane,方向相反,它的发端在本 lane 的收端 die 上。
弱耦合对的后向波是 K_b × [p(t) − p(t − 2τ_c)],K_b = (L_m/L + C_m/C)/4,τ_c 是耦合长度的单程延时;不经有损线,只经攻击方的
驱动极点与本方的 CTLE。远端估计已隐含 L_m/L = κ、C_m/C = κ ε_eff/ε_r(两者之差就是 FEXT 的失配 κ(1 − ε_eff/ε_r)),同一对耦合在近端相加:
**K_b = κ(1 + ε_eff/ε_r)/4**(带状线 κ/2)。标准封装 25 mm:K_b = −31.2 dB,两瓣相距 2τ_c = 266 ps = 8.5 UI,峰值 5.6 mV 对 165 mV 主光标。
- **更正(0.13.3,第三次体检 B 项)**:0.8.0–0.13.2 用 K_b = κ/4,只算了一种耦合,微带少 4.7 dB(−36.0 dB、峰值 3.3 mV);示例 08 边缘 lane 眼宽 0.661 → 0.645 UI(0.13.6 的 FEXT 形状下 0.634 → 0.616)。
  bundled 配置都不开 NEXT,指纹不变。教科书式未对照 Johnson & Graham 原文(未核实),改动依据是与本库远端估计自洽。
`lanes.reverse_adjacent` 指名受害 lane,`lanes.reverse_phase_ui` 是反向 lane 符号相对本模块采样点的相位(配置选择,默认 0)。
x3 边缘 lane 加 NEXT 后眼宽下降,中间 lane 不变;−14 dB 的固定 NEXT 上两引擎 1e-4 处 2× 内。

## 决策记录

- 文件里距离 d 的两个邻 lane 耦合不同,取**较强**的那条(网格上 RMS 最大),因为引擎按距离而不是按带符号的偏移索引攻击 lane;
  要区分左右需要把 `aggressors_of` 的键改成带符号偏移,留到有真实文件时再做。
- NEXT 的反向 lane 相位取固定值而不做随机相位平均:随机相位在统计引擎里是又一个核,先用固定值并记在开放问题。
- 树带宽对**数据边沿**的等效滤波属于收端前端带宽(段 7 的 `rx.noise_at` / 接收带宽),不放在串扰里。
- 树延时的循环卷绕量化为 `ForwardedClock.tree_wrap_fraction` = τ/(block·UI):30 ps 在 2^18 UI 的块上是 3.7e-6,每块约一个边沿。

## 开放问题

- 真实封装耦合线 S 参数(用户确认拿不到);到了之后用 `xtalk: touchstone` 对比 `coupled` 估计,目标 6 dB 内。
- NEXT 反向 lane 的相位随机化;回程模块的符号率 / 时钟与本模块无关的建模;带状线的二阶 FEXT(有损、非均匀介质)。
