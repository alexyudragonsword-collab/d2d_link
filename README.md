# d2d_link

die-to-die / UCIe 短距并行链路的行为级仿真框架:前向时钟、多 lane、几乎不均衡、无 FEC 下的极低 BER、lane repair。
它是 [Halo_Serdes](https://github.com/alexyudragonsword-collab/Halo_Serdes) 的姊妹库而不是扩展:Halo 是长距串行 SerDes
(CTLE/FFE/DFE/CDR、ADC-based、FEC),这里的核心机制是**前向时钟对发端 PLL 相噪的跟踪** —— 数据与时钟共享同一个 PLL,
收端看到的是两者之差经跟踪带宽滤波后的残余(`AGENTS.md` 铁律 2)。

六条铁律(`AGENTS.md`)每条有测试守着:配置是唯一真值;前向时钟跟踪是核心机制;统计引擎是主引擎(1e-27 时域到不了);
多 lane 从第一天就在;规范数字只用原文(拿不到就 `source: survey`);重构用数值指纹证明逐位不变。

## 安装与三行

```bash
pip install -e ".[touchstone,plot,test]"
pytest -q                                           # 约 5–6 分钟(1e-6 一致性点占 2 分钟)
python examples/00_single_lane_eye.py
```

```python
from d2d_link.config import load_config
from d2d_link.engine import run_link

print(run_link(load_config("configs/standard_32g_x1.yaml")).summary())
```

## 里程碑 1:标准封装、32 GT/s、1 lane、前向时钟 DDR 的时序预算

`configs/standard_32g_x1.yaml`:25 mm 有损走线(解析 RLGC,L / C 由 50 Ω 与叠层 ε_eff 2.54 推出,预设 `source: model`,皮肤效应带内电感,Djordjevic–Sarkar 色散介质,−2.75 dB @ 16 GHz),发端 PLL 相噪来自 pll_simulator 导出的
Markulic 2016 SSPLL 剖面(100 Hz..f0/2 186 fs,由 pll_simulator 算到 16 GHz 226.5 fs),数据 / 时钟路径各 200 fs 白抖动,收端时钟树 30 ps / 20 GHz / 100 fs,2 MHz 相位跟踪。

| 示例 | 问题 | 答案(当前版本的 `examples/expected/`;更早的数在括号里注明版本) |
|---|---|---|
| `00_single_lane_eye.py` | 这条链路的抖动预算与眼 | 发端 PLL 带内 226.5 fs(0.13.7 起剖面本身由 pll_simulator 算到 16 GHz,平在 −145 dBc/Hz 底噪);经前向时钟,**泄漏 223.4 fs** 经 30 ps 树的延时 / 带宽到达采样器 —— 树 ≈ 1 UI,在 fs/2 附近反相,把 PLL 跟不上的底噪加倍。残余 365.5 fs = 泄漏 223 + 数据路径 200 + 时钟路径 184 + 树 100(功率和)。眼高 224.3 mV / 眼宽 0.783 UI @ 1e-15(0.17.0 起 32 GT/s 的原始 BER 目标按 封装 × 速率 查表:`standard.raw_ber_target@32` = 1e-15,source: spec),对目标 40 mV / 0.65 UI 裕度 +184.3 mV / **+0.133 UI,过**(1e-27 时 204.1 mV / 0.709 UI、+0.059 UI;0.14.0 起 24 / 32 GT/s 用 0.65 UI 分档,0.16.1 起核实;0.13 对 0.75 UI、1e-27 时 −0.041 不过)。时域 40 万符号 0 误码 |
| `01_tracking_bandwidth_sweep.py` | 残余随跟踪带宽 | 相关 = 1、理想树:残余 0.000 fs;无跟踪 282.84 = √(200² + 200²);带宽 ∞ → 0。白路径抖动下 100 MHz 以下几乎不动(365.6 → 360.8 fs),半程点 4.2 GHz;ρ 0 → 385.1 fs;眼宽 0.783 → 0.911 UI(1e-15;1e-27 时 0.709 → 0.887) |
| `02_reach_sweep.py` | 走线能到多长 | 对 0.65 UI @ 1e-15(0.17.0)**reach 50 mm**(0.661 UI;55 mm 0.622 不过),对规范表 25 mm 2.00×,刚好在 2× 判据边上(1e-27 时 reach 35 mm、0.669 UI,1.40×)。0.13 对 0.75 UI、1e-27 时没有长度通过(5 mm 0.745 UI,30 ps 时钟树泄漏单独就让它不过),理想树时信道 reach 25 mm |
| `03_stat_vs_time.py` | 统计 / 时域在 1e-6 处的一致性 | 噪声主导 1e-6:时域 / 统计 1.50(30 误码 / 2e7);抖动主导 1e-6:1.12(16 误码 / 2e7);混合 1e-5:0.90(18 / 2e6)。三点都在 0.5–2× 内(两引擎都钉在调噪声的相位上采样) |

## 里程碑 2:多 lane 模块与收端本地时钟

`configs/standard_32g_x16_module.yaml`:x16、20 mm、3 ps 随机 skew(1/16 UI 步长 deskew)、邻 lane FEXT(封装预设 −30 dB @ Nyquist,
模型估计)、200 fs 路径漫游、收端本地 PLL(Wu 2019 SPLL 剖面,1 MHz 环路,锁到前向时钟)、2 MHz 跟踪器带 4 UI 延迟与 1/64 UI 相位插值器、
物理 lane 5 死 → 降宽到上半 x8。

| 示例 | 问题 | 答案(当前版本) |
|---|---|---|
| `04_local_pll_bandwidth.py` | 本地 PLL 的环路自然频率(−3 dB = 2.48 f_n) | 1 kHz:257.0 fs = √(226.5² + 119.9² + 杂散 19.0²)(两个独立时钟,本地 PLL 的 62 kHz 杂散全过);10 THz:0。发端泄漏与本地噪声随带宽**同向**下降;折中只来自环路前的时钟路径噪声(300 fs 白噪:最优 2.5e7 Hz,182.9 fs)。理想 PI 331.5 fs、眼宽 0.811 UI;PI 步长 1/64 UI 到 360.3 fs / 0.802 UI,1/16 UI 到 654.1 fs / 0.759 UI(1e-15;1e-27 时 0.744 / 0.734 / 0.690) |
| `05_module_xtalk_repair.py` | 整个模块能不能过 | x16 降宽后 8 lane **过**:最差 lane 逻辑 2 眼宽 0.764 对 0.65 UI @ 1e-15(1e-27 时逻辑 4、0.693;0.75 UI 时不过);串扰费 2.1 mV / 0.038 UI(0.13.6 起 FEXT 是攻击方的导数,吃边沿不吃中心),−20 dB 时 0.661 UI **也过**(1e-27 时 0.590 不过)。示例里给 x64 加上行为级 FEXT 后,两死 lane 备用修复 64/64 lane 在用、**过**:最小眼宽 0.671 UI(1e-27 时 0.601 不过;bundled x64 配置不开串扰时 0.777 UI);配置声明的 1/16 UI deskew 步长在跟踪器下就是 PI 步长(0.13.0),邻数 0..4 |
| `06_m2_consistency.py` | 新机制上统计 / 时域 | 本地 PLL 1.22(0.13 起抖动单独已到 2.5e-5,噪声调到下限,123 误码)、量化 + 延迟跟踪器 0.90、漫游 + 噪声 0.78、x3 串扰中间 lane 0.91、先进封装 + CTLE + DCD 0.78;五点都在 0.5–2× 内 |

## 里程碑 3:串扰的耦合线估计、速率档扫描、预算报表

`channel.xtalk: coupled` 用规范表里的 bump 间距(source: spec)和封装叠层预设(模型估计)算 FEXT 幅度:标准封装 25 mm **−18.7 dB**,
先进封装 2 mm −56.9 dB。`tools/budget_report.py` 把一条链路的时序预算写成报表。

| 示例 | 问题 | 答案(当前版本) |
|---|---|---|
| `07_rate_sweep.py` | 哪个速率档在哪种封装上过 | 标准 25 mm:**4–24 GT/s 过,32 GT/s 差 0.007 UI 不过**(最差 lane 2:32 GT/s 215.2 mV / 0.643 UI 对 0.65 UI;24 GT/s 241.0 mV / 0.734 UI 过;12 GT/s 起目标 1e-15,0.17.0;1e-27 时 32 GT/s 193.2 mV / 0.572 UI、24 GT/s 220.6 mV / 0.681 UI;0.14.1 起受害方直通带 cos(2πfτ);0.13 对 0.75 UI 时 24 GT/s 起不过);先进 2 mm(本示例的模块配置带 1/64 UI PI,16 GT/s 起 1e-15):六档全过,眼宽 0.960 → 0.821 UI(1e-27 时 32 GT/s 0.756) |

## 段 6:串扰物理(0.8.0)

`channel.routing`(微带 / 带状线)、`channel.xtalk_next`(反向 lane 的近端串扰,K_b = κ(1 + ε_eff/ε_r)/4,0.13.3 前是 κ/4)与单端 2N 端口 Touchstone 读法(`xtalk: touchstone`);
机制与数字见 `cairn/crosstalk.md`。

| 示例 | 问题 | 答案(当前版本) |
|---|---|---|
| `08_crosstalk_physics.py` | 串扰估计靠什么假设 | 同一 x5 / 25 mm 模块:微带 FEXT −18.7 dB → 中间 lane 215.2 mV / 0.643 UI,差 0.007 UI 不过(1e-15,0.17.0;1e-27 时 193.2 mV / 0.572 UI;0.14.1 受害方直通带 cos 项前 0.575);**带状线一阶 FEXT 为 0 → 220.5 mV / 0.787 UI,过**(1e-27 时 200.3 mV / 0.717 UI):32 GT/s 标准封装 x5 的判定又成了布线假设(到 0.11 也是;0.12–0.13 对 0.75 UI 两种布线都不过)。边缘 lane 加反向 lane 的 NEXT(−31.2 dB,两瓣 8.5 UI;0.13.3 前 κ/4 少算一半耦合时 −36.0 dB):眼宽 0.704 → 0.686 UI(1e-27 时 0.633 → 0.613;0.14.7 起反向 lane 也算一条耦合线,此前 0.615)。0.14.9 起反向 lane 相位取 8 个里最差的:边缘 lane 随相位只差 ≤ 0.0011 UI。用解析线合成的 6 端口文件读回:与解析路径眼高差 0.02 mV(0.14.4 起文件 lane 数等于模块物理线数时每个 lane 读自己的直通与邻线;读法就位,真实 S 参数仍缺) |

见 [`docs/USAGE.md`](docs/USAGE.md)、[`docs/clock_profile.md`](docs/clock_profile.md);结论与被推翻的判断在 `cairn/LOG.md`。

## 段 7:收端机制(0.9.0)

`rx.bw_hz`(收端前端一阶极点,数据边沿的"树带宽")、`rx.noise_at: sampler | input`(噪声在采样点还是在前端输入 —— CTLE 的噪声代价由此而来)、
`rx.training_ber`(训练在哪个 BER 上居中)与 `rx.training_dwell_symbols`(眼监视器每相位数多少符号,0.15.7:居中误差按 3σ 计);默认值全部保持旧行为,bundled 配置指纹逐位相同。机制与数字见 `cairn/receiver.md`。

| 示例 | 问题 | 答案(当前版本) |
|---|---|---|
| `09_receiver_front_end.py` | 接收机自己花掉多少 | x1 25 mm(1e-15,0.17.0;1e-27 时的数在括号里):前端 48 / 32 / 24 GHz 眼高 224.3 → 219.6 / 209.1 / 194.8 mV(204.1 → 199.0 / 188.0 / 173.2,噪声在采样点);同一 3 mV 改到输入:171.3 / 178.3 / 174.2 mV(131.7 / 145.1 / 144.8;窄前端省噪声,32 GHz 附近最好)。35 mm + 32 GHz 前端的 CTLE:噪声在采样点 6 dB 最好 290.5 mV,在输入也是 6 dB 最好 252.1 mV(270.7 / 216.0)。训练 1e-3 居中:x1 偏 −0.0010 UI(眼宽 −0.002;1e-27 时 −0.0016 / −0.003),x5 耦合中间 lane 偏 −0.007 UI、眼宽 0.643 → 0.630(0.572 → 0.555)。时域滤噪声:采到 68.5 对闭式 69.07 mV |

## 段 8:浏览器 GUI(0.11.0)

`pip install -e ".[gui]"` 后 `d2d-link-gui configs/standard_32g_x16_module.yaml`:页面就是时序预算报表,标题句里的值是控件,改一个就入队重跑。
段落:Verdict、What flips the verdict(敏感性 tornado)、Clock-path jitter、Eye & bathtub per lane、Lanes and repair(物理 lane 平面图 + Inspector)、
Crosstalk、Receiver、Sweeps(tracker 带宽 / 本地 PLL / reach);右栏队列(进程池,进度与剩余时间)、Data rate × package、导出(Markdown 与 CLI 同文)、
未核实输入;Compare with 并排两场景;结果按配置哈希缓存到磁盘。GUI 不含仿真逻辑(铁律 1,`tests/test_gui.py` 用 AST 守);见 `docs/gui.md`、`cairn/gui.md`。

## 时钟树与模块抖动预算的设计扫描(0.13.1–0.13.2)

0.13.0 起 bundled 配置全部不过,原因是时钟树把 PLL 的高频底噪加倍送到采样器。示例 10 不改模型,只问:树要多短、PLL 底噪要多低才过;示例 11 问 x16 模块(树长对它不起作用)能承受多少抖动、从哪里省。
底噪变体把剖面的 −145 dBc/Hz 白底换掉、带内形状不动,是设计目标而不是实测 PLL。

| 示例 | 问题 | 答案(当前版本) |
|---|---|---|
| `10_clock_tree_design.py` | 树要多短、底噪要多低 | **对 0.65 UI(0.14.0)x1 与 x16 模块在扫过的每一点都过**(−145…−155 dBc/Hz、树 0–40 ps、四种树带宽、两种口径);1e-15(0.17.0)下 x1 最窄 0.781 UI、x16 模块最差 0.764 UI,连 0.75 UI 也都过。下面是 0.13 时(对 0.75 UI、1e-27)的设计边界,只在两个目标都改回去时适用:x1(20 GHz 树、底噪平延)−145 dBc/Hz 时树 ≤ 2.7 ps 才过,−150 时 ≤ 11.9 ps,−155 时 40 ps 内都过;10 GHz 树在 −150 时 40 ps 内都过,平坦树在 −155 时只到 9.0 ps(慢树不再跟高频,底噪只过一次而不是加倍)。**x16 模块**:1 MHz 本地 PLL 重定时,泄漏与树延时无关(0 / 30 ps 都是 176.4 fs) |
| `11_module_jitter_budget.py` | x16 模块能承受多少抖动、从哪省 | 统计引擎只看残余的一个高斯 σ:最差 lane(逻辑 2)眼宽到 0.65 UI @ 1e-15(0.17.0)对应 **σ\* = 586.0 fs**,今天 331.5 fs,余量 483 fs(功率;扫描的 g 因此延到 2.0);24 种组合全过。1e-27 时 σ\* = 400.6 fs、余量 225 fs(0.14.0);对 0.75 UI、1e-27(0.13)时 σ\* = 233.9 fs、要去掉 235 fs,单个杠杆都不够,24 中 7 过。本地 PLL 带宽几乎不动(0.1 / 10 MHz:327.1 / 334.8 fs)。第 4 节在 σ\* 两侧各取两点(0.14.6 起:组合全过时取单项加大到 1.08 / 1.15 σ\* 的设计;1.15 σ\* 已在曲线范围外,只给上界),曲线范围内全模块与预测差 ≤ 0.0006 UI —— 无论 σ 从哪一项来 |
| `12_eye_width_attribution.py` | 眼宽输给了谁 | 每个 bundled 配置最差 lane 的眼宽缺口按 串扰 / 抖动 / PI 步长 拆(Shapley,各份相加正好是缺口;`budget_report.py --attribution`)。1e-15(0.17.0)下缺口都变小(ISI 与噪声单独的眼也更宽):x1 0.128 UI 全是抖动;x16 模块 0.168 = 抖动 67 % + 串扰 26 % + PI 6 %;x16 repair 0.188 = 抖动 70 % + PI 30 %,x64 spare 0.194 = 71 % / 29 %;**x5 耦合 0.268 = 串扰 55 % + 抖动 41 % + PI 4 %,串扰成了最大的一份**。只有 x5 不过(差 0.0067 UI),单关三项里任一项都能过,连 PI 步长(0.652 UI);x64 + FEXT 0.671 UI 过(1e-27 时不过)。1e-27 时:x1 0.178,x16 模块 0.220 = 73 / 22 / 5 %,x16 repair 与 x64 spare 77 / 23 %,x5 0.316 = 串扰 48 % + 抖动 48 % |
| `13_sensitivity.py` | 哪些估计决定判定 | 每个 bundled 配置的 `budget_report.py --sensitivity`(±20 %、dB ±3 dB、目标 ±10 mV / ±0.05 UI;0.15.2 起平坦前端也是一项:一侧换成 2 f_N = 32 GHz 一阶极点):1e-15(0.17.0)下**四个过的配置什么都不翻**:x1 +0.205、x16 模块 +0.175、x16 repair +0.144、x64 spare +0.195(离翻最近的都是目标 0.70 UI:+0.119 / +0.091 / +0.063 / +0.109;前端 32 GHz +0.159 / +0.137 / +0.109 / +0.182);**x5 −0.010 被 8 项翻**:数据路径白抖 −20 %(+0.004)、Z0 60 Ω(+0.005)、发端 PLL −3 dB(+0.005)、r_skin −20 %(+0.008)、ε_r 2.8(+0.025)、bump 间距 138 µm(+0.043)、介质 24 µm(+0.057)、目标 0.60 UI(+0.072)。1e-27 时:x1 +0.091、x64 +0.093 不翻,x16 模块 +0.066 被目标 0.70 UI 翻,x16 repair +0.028 被前端 32 GHz、PLL +3 dB 与目标 0.70 UI 翻,x5 −0.121 什么都不翻。约 6 分钟(四核并行) |
| `14_repair_margin.py` | x16 repair 的薄余量靠什么 | 没有本地 PLL:残余 365.5 fs 里 Tx PLL 经 30 ps 树的泄漏占 37 % 功率,另有 1/16 UI(1.95 ps)PI 步长。1e-15(0.17.0)下余量 +0.144、**不再薄**:bundled 扛得住 PLL 剖面 **+6.8 dB**(1e-27 时 +1.5 dB);单个杠杆:PI 1/32 UI → +7.9 dB、1/64 UI → +8.3 dB,数据路径白抖 100 fs → +7.3 dB,树 15 ps → +9.4 dB、0 ps → > 12 dB,加 x16 的本地 PLL → +9.3 dB(1e-27 时 +3.4 / +4.1 / +3.0 / +4.1 / > 12 / +4.9 dB);跟踪器 5 MHz 不动(配置里没有漫游) |
| `15_quarter_rate_clock.py` | 四分之一速率前向时钟会怎样 | `forwarded_qdr`(方案本身有公开出处:教程 slide 54 / 57,24 / 32 GT/s 可取 rate/4;建模 source: model):边沿间内插不再跟 fs/2 附近的相噪,30 ps 树的翻倍消失(x1 泄漏 223.4 → 156.1 fs),但边沿采样把时钟路径在 fs/2 − f 的噪声折回来(151.8 fs,0.15.1):残余 365.5 → 334.2 fs、眼宽 0.783 → 0.798 UI(1e-15;1e-27 时 0.709 → 0.729);x16 模块不变。I/Q 偏差 0.02 / 0.06 UI 费 0.018 / 0.058 UI;4 相发生器白抖动 100 / 200 fs(0.15.8)→ 眼宽 0.791 / 0.772 UI(1e-27 时 0.720 / 0.694) |

## 规范数字

速率档、BER 目标、bump 间距、reach、模块宽度、眼罩共 16 条(眼宽按速率区间分档),全部在共享库 spec_sources 的 `ucie.yaml`(0.16.0 起 vendored 在 `src/d2d_link/vendor/spec_sources/data/ucie.yaml`,0.16.1 起 pin 在 spec_sources@bbc0ccb;`d2d_link.spec` 按旧键名读)。
0.16.1 起其中 15 条是 `source: spec`:spec_sources 对照公开原文(Hot Chips 2023 UCIe 教程、UCIe 1.0 白皮书)核实,带原句与页码;剩下 `standard.lane_repair` 一条仍是 `source: survey`(降到 x8 两份原文都没写)。引擎只按 key 取,结果行打印 `source: xxx`。
UCIe 规范本身的下载许可禁止把规范交给 AI 系统,本库不收规范原文(见 `cairn/spec-sources.md`)。
**眼罩的口径比规范严**:原文的眼罩判的是信道自己的眼(无噪、无抖的行为级 TX/RX),本库拿含时钟路径残余抖动、收端噪声与串扰的眼去比;0.17.0 起报表 Targets 节写明这一点(issue #2 第 1 点,用户选保留)。
**发送摆幅取下限**:bundled 配置都用 0.4 V,是原文的最小摆幅(另强烈建议上限 < 0.85 V);判定按最坏情况(issue #2 第 3 点)。
**0.14.0 起眼宽目标分档:4–16 GT/s 0.75 UI、24–32 GT/s 0.65 UI**(0.14.5 起是一条区间 `@24-32`,28 GT/s 也取 0.65;表外且不在区间里的速率退回 0.75 并告警)(0.14.0 时出自二手转述;0.16.1 起核实:教程 slide 61 'Channel Specification')。**0.17.0 起原始 BER 目标按 封装 × 速率 查表**(`ucie.raw_ber_by_rate`,source: spec;issue #2 第 2 点):标准封装 12 GT/s 起、先进封装 16 GT/s 起 1e-15,其余 1e-27;32 GT/s 的 bundled 配置都按 `<package>.raw_ber_target@32` = 1e-15 判,表外速率退回 1e-27 并告警。按它 bundled 配置里 x1、x16 模块、x16 repair、x64 spare 都过,只有 x5 耦合不过(0.643 UI,差 0.007)。敏感性(示例 13):x1 +0.205、x16 模块 +0.175、x16 repair +0.144、x64 spare +0.195 什么都不翻;**x5 −0.010 被 8 项翻**(最近:数据路径白抖 −20 % +0.004、Z0 60 Ω +0.005、发端 PLL −3 dB +0.005)。1e-27 时(0.14.2–0.16.1):x1 +0.091、x64 +0.093 不翻,x16 模块 +0.066 被目标 0.70 UI 翻,x16 repair +0.028 被目标 0.70 UI(−0.045)与 PLL +3 dB(−0.034)翻,x5 −0.121 什么都不翻。目标按 封装 × 速率档 分档查表(0.13.5):原文的分档数字一来,加 `standard.rx_eye_width_ui@32` 这样的条目即可,报表写明用的是哪一档。

```bash
grep "source: survey" src/d2d_link/vendor/spec_sources/data/ucie.yaml
```

## 布局

| 目录 | 内容 |
|---|---|
| `src/d2d_link/config/` | frozen `LinkConfig`、YAML 加载、表单字段声明(`form.py`) |
| `src/d2d_link/clock/` | 剖面读取、**前向时钟模型**(发端 PLL、本地 PLL、树、跟踪器;闭式预算 + 逐符号合成) |
| `src/d2d_link/channel/` | 解析 RLGC 走线 / Touchstone → 脉冲响应;FEXT / NEXT 串扰脉冲;收端前端与噪声整形(段 7) |
| `src/d2d_link/engine/` | 统计引擎(主)、时域引擎(校核)、lane 映射与修复、链路判定 |
| `src/d2d_link/spec/`、`src/d2d_link/data/` | 规范数字表的读取;规范表、模型预设与随库的时钟剖面(package data,配置里仍写 `data/...`) |
| `src/d2d_link/vendor/` | Halo_Serdes 的 S 参数读法 / RLGC / 响应转换,pll_simulator 的相噪合成与积分;完整 SHA 钉住,`tools/vendor_check.py` 守 |
| `src/d2d_link/report.py`、`src/d2d_link/gui/` | 时序预算报表(dict / Markdown / 敏感性);浏览器 GUI(Dash,零仿真逻辑) |
| `tools/` | `fingerprint.py`(`fingerprint_walk.py` 在 CI 里逐提交归属数字变动)、`example_drift.py`、`run_examples.py`、`vendor_check.py`、`budget_report.py`(报表的 CLI)、`export_profile_to_nyquist.py`(pll_simulator 剖面算到 16 GHz) |
| `cairn/` | 项目知识:铁律论证、前向时钟、双引擎、串扰、收端、规范来源、坑;`LOG.md` 每轮数字与被推翻的判断 |

## 不做

均衡器与 CDR 的深度(Halo);协议层(flit / CRC / retry 只留 `target.ber` 参数位);规范条文的转述。
