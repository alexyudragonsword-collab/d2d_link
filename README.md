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

| 示例 | 问题 | 答案(0.12.5,`examples/expected/`;更早的数在括号里注明版本) |
|---|---|---|
| `00_single_lane_eye.py` | 这条链路的抖动预算与眼 | 发端 PLL 带内 226.5 fs(0.13.7 起剖面本身由 pll_simulator 算到 16 GHz,平在 −145 dBc/Hz 底噪);经前向时钟,**泄漏 223.4 fs** 经 30 ps 树的延时 / 带宽到达采样器 —— 树 ≈ 1 UI,在 fs/2 附近反相,把 PLL 跟不上的底噪加倍。残余 365.5 fs = 泄漏 223 + 数据路径 200 + 时钟路径 184 + 树 100(功率和)。眼高 204.1 mV / 眼宽 0.709 UI @ 1e-27,对 32 GT/s 的综述目标 40 mV / 0.65 UI 裕度 +164.1 mV / **+0.059 UI,过**(0.14.0 起 24 / 32 GT/s 用 0.65 UI 分档,二手转述未核实;0.13 对 0.75 UI 时 −0.041 不过)。时域 40 万符号 0 误码 |
| `01_tracking_bandwidth_sweep.py` | 残余随跟踪带宽 | 相关 = 1、理想树:残余 0.000 fs;无跟踪 282.84 = √(200² + 200²);带宽 ∞ → 0。白路径抖动下 100 MHz 以下几乎不动(365.6 → 360.8 fs),半程点 4.2 GHz;ρ 0 → 385.1 fs;眼宽 0.709 → 0.887 UI |
| `02_reach_sweep.py` | 走线能到多长 | 对 0.65 UI(0.14.0)**reach 35 mm**(0.669 UI;40 mm 0.642 不过),对综述 25 mm 1.40×。0.13 对 0.75 UI 时没有长度通过(5 mm 0.745 UI,30 ps 时钟树泄漏单独就让它不过),理想树时信道 reach 25 mm |
| `03_stat_vs_time.py` | 统计 / 时域在 1e-6 处的一致性 | 噪声主导 1e-6:时域 / 统计 1.50(30 误码 / 2e7);抖动主导 1e-6:1.12(16 误码 / 2e7);混合 1e-5:0.90(18 / 2e6)。三点都在 0.5–2× 内(两引擎都钉在调噪声的相位上采样) |

## 里程碑 2:多 lane 模块与收端本地时钟

`configs/standard_32g_x16_module.yaml`:x16、20 mm、3 ps 随机 skew(1/16 UI 步长 deskew)、邻 lane FEXT(封装预设 −30 dB @ Nyquist,
模型估计)、200 fs 路径漫游、收端本地 PLL(Wu 2019 SPLL 剖面,1 MHz 环路,锁到前向时钟)、2 MHz 跟踪器带 4 UI 延迟与 1/64 UI 相位插值器、
物理 lane 5 死 → 降宽到上半 x8。

| 示例 | 问题 | 答案(0.12.5) |
|---|---|---|
| `04_local_pll_bandwidth.py` | 本地 PLL 的环路自然频率(−3 dB = 2.48 f_n) | 1 kHz:257.0 fs = √(226.5² + 119.9² + 杂散 19.0²)(两个独立时钟,本地 PLL 的 62 kHz 杂散全过);10 THz:0。发端泄漏与本地噪声随带宽**同向**下降;折中只来自环路前的时钟路径噪声(300 fs 白噪:最优 2.5e7 Hz,182.9 fs)。理想 PI 331.5 fs、眼宽 0.744 UI;PI 步长 1/64 UI 到 360.3 fs / 0.734 UI,1/16 UI 到 654.1 fs / 0.690 UI |
| `05_module_xtalk_repair.py` | 整个模块能不能过 | x16 降宽后 8 lane **过**:最差 lane 逻辑 4 眼宽 0.693 对 0.65 UI(0.14.0;0.75 UI 时不过);串扰费 2.2 mV / 0.041 UI(0.13.6 起 FEXT 是攻击方的导数,吃边沿不吃中心),−20 dB 时 0.591 UI 不过。示例里给 x64 加上行为级 FEXT 后,两死 lane 备用修复 64/64 lane 在用、**不过**:最小眼宽 0.599 UI(bundled x64 配置不开串扰时 0.710 UI 过);配置声明的 1/16 UI deskew 步长在跟踪器下就是 PI 步长(0.13.0),邻数 0..4 |
| `06_m2_consistency.py` | 新机制上统计 / 时域 | 本地 PLL 1.22(0.13 起抖动单独已到 2.5e-5,噪声调到下限,123 误码)、量化 + 延迟跟踪器 0.90、漫游 + 噪声 0.78、x3 串扰中间 lane 0.96、先进封装 + CTLE + DCD 0.78;五点都在 0.5–2× 内 |

## 里程碑 3:串扰的耦合线估计、速率档扫描、预算报表

`channel.xtalk: coupled` 用规范表里的 bump 间距(source: survey)和封装叠层预设(模型估计)算 FEXT 幅度:标准封装 25 mm **−18.7 dB**,
先进封装 2 mm −56.9 dB。`tools/budget_report.py` 把一条链路的时序预算写成报表。

| 示例 | 问题 | 答案(0.12.5) |
|---|---|---|
| `07_rate_sweep.py` | 哪个速率档在哪种封装上过 | 标准 25 mm:**4–24 GT/s 过,32 GT/s 不过**(最差 lane 2:32 GT/s 193.3 mV / 0.575 UI 对 0.65 UI;24 GT/s 220.5 mV / 0.684 UI 过 0.65 UI 分档;0.13 对 0.75 UI 时 24 GT/s 起不过);先进 2 mm(本示例的模块配置带 1/64 UI PI):六档全过,眼宽 0.960 → 0.756 UI |

## 段 6:串扰物理(0.8.0)

`channel.routing`(微带 / 带状线)、`channel.xtalk_next`(反向 lane 的近端串扰,K_b = κ(1 + ε_eff/ε_r)/4,0.13.3 前是 κ/4)与单端 2N 端口 Touchstone 读法(`xtalk: touchstone`);
机制与数字见 `cairn/crosstalk.md`。

| 示例 | 问题 | 答案(2026-10-13,0.8.0) |
|---|---|---|
| `08_crosstalk_physics.py` | 串扰估计靠什么假设 | 同一 x5 / 25 mm 模块:微带 FEXT −18.7 dB → 中间 lane 193.3 mV / 0.575 UI 不过;**带状线一阶 FEXT 为 0 → 200.3 mV / 0.717 UI,过**(0.14.0 的 0.65 UI 分档):32 GT/s 标准封装 x5 的判定又成了布线假设(到 0.11 也是;0.12–0.13 对 0.75 UI 两种布线都不过)。边缘 lane 加反向 lane 的 NEXT(−31.2 dB,两瓣 8.5 UI;0.13.3 前 κ/4 少算一半耦合时 −36.0 dB):眼宽 0.634 → 0.616 UI。用解析线合成的 6 端口文件读回:与解析路径眼高差 0.02 mV(读法就位,真实 S 参数仍缺) |

见 [`docs/USAGE.md`](docs/USAGE.md)、[`docs/clock_profile.md`](docs/clock_profile.md);结论与被推翻的判断在 `cairn/LOG.md`。

## 段 7:收端机制(0.9.0)

`rx.bw_hz`(收端前端一阶极点,数据边沿的"树带宽")、`rx.noise_at: sampler | input`(噪声在采样点还是在前端输入 —— CTLE 的噪声代价由此而来)、
`rx.training_ber`(训练在哪个 BER 上居中);默认值全部保持旧行为,bundled 配置指纹逐位相同。机制与数字见 `cairn/receiver.md`。

| 示例 | 问题 | 答案(2026-10-13,0.9.0) |
|---|---|---|
| `09_receiver_front_end.py` | 接收机自己花掉多少 | x1 25 mm:前端 48 / 32 / 24 GHz 眼高 204.1 → 199.0 / 188.0 / 173.2 mV(噪声在采样点);同一 3 mV 改到输入:131.7 / 145.1 / 144.8 mV(窄前端省噪声,32 GHz 附近最好)。35 mm + 32 GHz 前端的 CTLE:噪声在采样点 6 dB 最好 270.7 mV,在输入也是 6 dB 最好 216.0 mV。训练 1e-3 居中:x1 偏 −0.0016 UI(眼宽 −0.003),x5 耦合中间 lane 偏 −0.009 UI、眼宽 0.575 → 0.557。时域滤噪声:采到 68.5 对闭式 69.07 mV |

## 段 8:浏览器 GUI(0.11.0)

`pip install -e ".[gui]"` 后 `d2d-link-gui configs/standard_32g_x16_module.yaml`:页面就是时序预算报表,标题句里的值是控件,改一个就入队重跑。
段落:Verdict、What flips the verdict(敏感性 tornado)、Clock-path jitter、Eye & bathtub per lane、Lanes and repair(物理 lane 平面图 + Inspector)、
Crosstalk、Receiver、Sweeps(tracker 带宽 / 本地 PLL / reach);右栏队列(进程池,进度与剩余时间)、Data rate × package、导出(Markdown 与 CLI 同文)、
未核实输入;Compare with 并排两场景;结果按配置哈希缓存到磁盘。GUI 不含仿真逻辑(铁律 1,`tests/test_gui.py` 用 AST 守);见 `docs/gui.md`、`cairn/gui.md`。

## 时钟树与模块抖动预算的设计扫描(0.13.1–0.13.2)

0.13.0 起 bundled 配置全部不过,原因是时钟树把 PLL 的高频底噪加倍送到采样器。示例 10 不改模型,只问:树要多短、PLL 底噪要多低才过;示例 11 问 x16 模块(树长对它不起作用)能承受多少抖动、从哪里省。
底噪变体把剖面的 −145 dBc/Hz 白底换掉、带内形状不动,是设计目标而不是实测 PLL。

| 示例 | 问题 | 答案(2026-11-04,0.13.1) |
|---|---|---|
| `10_clock_tree_design.py` | 树要多短、底噪要多低 | **对 0.65 UI(0.14.0)x1 与 x16 模块在扫过的每一点都过**(−145…−155 dBc/Hz、树 0–40 ps、四种树带宽、两种口径)。下面是对 0.75 UI(0.13)时的设计边界,目标改回 0.75 时仍适用:x1(20 GHz 树、底噪平延)−145 dBc/Hz 时树 ≤ 2.7 ps 才过,−150 时 ≤ 11.9 ps,−155 时 40 ps 内都过;10 GHz 树在 −150 时 40 ps 内都过,平坦树在 −155 时只到 9.0 ps(慢树不再跟高频,底噪只过一次而不是加倍)。**x16 模块**:1 MHz 本地 PLL 重定时,泄漏与树延时无关(0 / 30 ps 都是 176.4 fs) |
| `11_module_jitter_budget.py` | x16 模块能承受多少抖动、从哪省 | 统计引擎只看残余的一个高斯 σ:最差 lane(逻辑 4)眼宽到 0.65 UI(0.14.0)对应 **σ\* = 401.5 fs**,今天 331.5 fs,余量 226 fs(功率);24 种组合全过。对 0.75 UI(0.13)时 σ\* = 233.9 fs、要去掉 235 fs,单个杠杆都不够(最大是数据路径白抖 200 → 100 fs,282.7 fs),24 中 7 过。本地 PLL 带宽几乎不动(0.1 / 10 MHz:327.1 / 334.8 fs)。全模块点与预测一致(按构造:引擎只看 σ) |
| `12_eye_width_attribution.py` | 眼宽输给了谁 | 每个 bundled 配置最差 lane 的眼宽缺口按 串扰 / 抖动 / PI 步长 拆(Shapley,各份相加正好是缺口;`budget_report.py --attribution`)。**抖动处处最大**:x1 0.178 UI 全是它;x16 模块缺口 0.220 = 抖动 73 % + 串扰 22 % + PI 5 %;x16 repair 与 x64 spare 抖动 77 %、PI 步长 23 %;x5 耦合 0.312 = 抖动 51 % + 串扰 45 %。对 0.65 UI(0.14.0)只有 x5 与 x64 + FEXT 不过:x5 单关串扰或单关抖动都能过,x64 + FEXT 单关任一项都过 |

## 规范数字

本库拿不到 UCIe 规范原文。速率档、BER 目标、bump 间距、reach、模块宽度、眼罩共 17 条(眼宽按速率分档),全部在 `src/d2d_link/data/spec/ucie_survey.yaml`,
每条 `source: survey` 并注明综述出处与"未核实";引擎只按 key 取,结果行打印 `source: xxx`。
**0.14.0 起眼宽目标分档:4–16 GT/s 0.75 UI、24 / 32 GT/s 0.65 UI**(后者来自一篇 2025 年分析论文的转述,二手、未核实,用户决定采用)。按它 bundled 配置里 x1、x16 模块、x16 repair、x64 spare 都过,只有 x5 耦合不过。敏感性(0.14.0):x16 模块只在目标抬到 0.70 UI 时翻(−0.010),x1 与 x5 什么都翻不了。目标按 封装 × 速率档 分档查表(0.13.5):原文的分档数字一来,加 `standard.rx_eye_width_ui@32` 这样的条目即可,报表写明用的是哪一档。

```bash
grep "source: survey" src/d2d_link/data/spec/ucie_survey.yaml
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
