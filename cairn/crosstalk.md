---
type: project_topic
status: active
summary: "lane 间串扰怎么建:FEXT 的行为级 / 耦合线估计、带状线为什么没有一阶 FEXT、反向 lane 的 NEXT、单端多端口 Touchstone 的读法,以及哪些数只是估计。"
tags: [crosstalk, fext, next, stripline, touchstone]
contains: [decision, lesson]
created: "2026-10-13"
updated: "2026-10-13"
related: [architecture-invariants.md, engines.md, spec-sources.md]
authoring_mode: ai_generated
---
# 串扰

## 当前结论

三条路径,同一个引擎接口(`LinkResponse.xtalk_pulses[key]`,key 是邻接距离 1 / 2 或 `"next"`;统计引擎把串扰光标当独立 ±1 干扰项,
时域给每个攻击 lane 自己的 PRBS):

- **`xtalk: fext`**(M2):行为级 —— 幅度 `xtalk_adjacent_db`(预设 −30 / −24 dB,`source: model`),形状 k(jf/fn)/(1 + jf/fn)。
- **`xtalk: coupled`**(M3):一阶耦合微带估计 —— κ = 1/(1 + (s/h)²)、速度失配 (1 − ε_eff/ε_r)、幅度随耦合长度线性增长、Nyquist 处取值、
  上限 −3 dB。标准封装 25 mm:**−18.6 dB**,先进 2 mm −56.9 dB。bump 间距是 `source: survey`,叠层是 `source: model`。
- **`xtalk: touchstone`**(段 6):单端 2N 端口文件自己的耦合项 —— 端口 1..N 是 lane 0..N−1 的近端、N+1..2N 远端;`channel/touchstone_se.py`
  对每个 2 端口子网络用 vendored 的内插与端接(其余端口按文件参考阻抗端接,这是唯一近似),距离 d 取两侧较强的那条。合成无损 3 lane 文件上
  读回 |H| = 1、耦合 Nyquist 处 0.0707 对 0.0707、lane 间互易。**真实封装 S 参数仍然没有**(ROADMAP P1 #2):读法就位,数据缺位。

**带状线**(`channel.routing: stripline`):均匀介质,ε_eff = ε_r,奇偶模同速,一阶 FEXT 为 0(估计给 −300 dB 下限);同几何的线更慢
(L、C 由 ε_r 推出)。NEXT 系数 κ/4 与布线方式无关。**32 GT/s 标准封装不过这个结论是微带假设的产物**:同几何布成带状线就过。

**近端串扰**(`channel.xtalk_next`,段 6):模块边缘的 lane 旁边是回程模块的 lane,方向相反,它的发端在本 lane 的收端 die 上。
弱耦合对的后向波是 K_b × [p(t) − p(t − 2τ_c)],K_b = κ/4(Johnson & Graham),τ_c 是耦合长度的单程延时;不经有损线,只经攻击方的
驱动极点与本方的 CTLE。标准封装 25 mm:K_b = −36.0 dB,两瓣相距 2τ_c = 266 ps = 8.5 UI,峰值 3.3 mV 对 165 mV 主光标。
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
