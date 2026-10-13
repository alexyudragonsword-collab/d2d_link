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
pytest -q                                           # 约 2 分钟
python examples/00_single_lane_eye.py
```

```python
from d2d_link.config import load_config
from d2d_link.engine import run_link

print(run_link(load_config("configs/standard_32g_x1.yaml")).summary())
```

## 里程碑 1:标准封装、32 GT/s、1 lane、前向时钟 DDR 的时序预算

`configs/standard_32g_x1.yaml`:25 mm 有损走线(解析 RLGC,L / C 由 50 Ω 与叠层 ε_eff 2.54 推出,预设 `source: model`,−2.80 dB @ 16 GHz),发端 PLL 相噪来自 pll_simulator 导出的
Markulic 2016 SSPLL 剖面(带内 186 fs),数据 / 时钟路径各 200 fs 白抖动,收端时钟树 30 ps / 20 GHz / 100 fs,2 MHz 相位跟踪。

| 示例 | 问题 | 答案(2026-10-13,0.6.0,`examples/expected/`) |
|---|---|---|
| `00_single_lane_eye.py` | 这条链路的抖动预算与眼 | PLL 的 186 fs 经前向时钟抵消,只有 59.4 fs 经树的延时 / 带宽泄漏到采样器;残余 295 fs = 泄漏 59 + 数据路径 200 + 时钟路径 184 + 树 100(功率和)。眼高 215.6 mV / 眼宽 0.774 UI @ 1e-27,对综述目标 40 mV / 0.75 UI 裕度 +175.6 mV / +0.024 UI。时域 40 万符号 0 误码 |
| `01_tracking_bandwidth_sweep.py` | 残余随跟踪带宽 | 相关 = 1、理想树:残余 0.000 fs;无跟踪 282.84 = √(200² + 200²);带宽 ∞ → 0。白路径抖动下 100 MHz 以下几乎不动(295 → 291 fs),半程点 4.2 GHz;ρ 0 → 339 fs |
| `02_reach_sweep.py` | 走线能到多长 | 35 mm 是最后通过的长度(40 mm 眼宽 0.739 < 0.75 UI,眼高还有 150 mV);综述 reach 25 mm,比 1.40×(0.5.0 前 L / C 预设隐含 ε_eff 3.94,给 30 mm / 1.20×) |
| `03_stat_vs_time.py` | 统计 / 时域在 1e-6 处的一致性 | 噪声主导 1e-6:时域 / 统计 1.23(24 误码 / 2e7);抖动主导 1e-6:1.22(16 误码 / 2e7);混合 1e-5:0.87(17 / 2e6)。三点都在 0.5–2× 内 |

## 里程碑 2:多 lane 模块与收端本地时钟

`configs/standard_32g_x16_module.yaml`:x16、20 mm、3 ps 随机 skew(1/16 UI 步长 deskew)、邻 lane FEXT(封装预设 −30 dB @ Nyquist,
模型估计)、200 fs 路径漫游、收端本地 PLL(Wu 2019 SPLL 剖面,1 MHz 环路,锁到前向时钟)、2 MHz 跟踪器带 4 UI 延迟与 1/64 UI 相位插值器、
物理 lane 5 死 → 降宽到上半 x8。

| 示例 | 问题 | 答案(2026-10-13,0.6.0) |
|---|---|---|
| `04_local_pll_bandwidth.py` | 本地 PLL 的环路自然频率(−3 dB = 2.48 f_n) | 1 kHz:206.8 fs = √(186.2² + 88.0² + 杂散 19.0²)(两个独立时钟,本地 PLL 的 62 kHz 杂散全过);10 THz:0。发端泄漏与本地噪声随带宽**同向**下降;折中只来自环路前的时钟路径噪声(300 fs 白噪:最优 2.5e7 Hz,100.9 fs)。PI 步长 1/64 UI 加 32 fs,1/16 UI 加到 636 fs |
| `05_module_xtalk_repair.py` | 整个模块能不能过 | x16 降宽后 8 lane 全过,最差 lane 是逻辑 5(眼宽 0.753 对 0.75 UI,裕度最小);串扰费 22 mV / 0.018 UI,−20 dB 时关门。x64 两死 lane 备用修复 64/64 过,邻数 0..4 |
| `06_m2_consistency.py` | 新机制上统计 / 时域 | 本地 PLL 0.92、量化 + 延迟跟踪器 0.74、x3 串扰中间 lane 0.86、先进封装 + CTLE + DCD 0.80、漫游 + 噪声 0.82;五点都在 0.5–2× 内 |

## 里程碑 3:串扰的耦合线估计、速率档扫描、预算报表

`channel.xtalk: coupled` 用规范表里的 bump 间距(source: survey)和封装叠层预设(模型估计)算 FEXT 幅度:标准封装 25 mm **−18.6 dB**,
先进封装 2 mm −56.9 dB。`tools/budget_report.py` 把一条链路的时序预算写成报表。

| 示例 | 问题 | 答案(2026-10-13,0.6.0) |
|---|---|---|
| `07_rate_sweep.py` | 哪个速率档在哪种封装上过 | 标准 25 mm:4–24 GT/s 过,32 GT/s 中间 lane 眼 143.1 mV / 0.691 UI,眼宽 < 0.75 UI 不过(0.5.0 的 log 内插边给 0.693,0.4.0 的 L / C 预设 0.685,0.3.x 的枚举模型 0.671;串扰 −18.6 dB 是主因;示例 05 的 x16 / 20 mm 模块在 −30 dB 预设下能过,是另一个模块);先进 2 mm:六档全过,眼宽 0.960 → 0.781 UI |

## 段 6:串扰物理(0.8.0)

`channel.routing`(微带 / 带状线)、`channel.xtalk_next`(反向 lane 的近端串扰,K_b = κ/4)与单端 2N 端口 Touchstone 读法(`xtalk: touchstone`);
机制与数字见 `cairn/crosstalk.md`。

| 示例 | 问题 | 答案(2026-10-13,0.8.0) |
|---|---|---|
| `08_crosstalk_physics.py` | 串扰估计靠什么假设 | 同一 x5 / 25 mm 模块:微带 FEXT −18.6 dB → 中间 lane 143.1 mV / 0.691 UI 不过;**带状线一阶 FEXT 为 0 → 211.8 mV / 0.761 UI 过**(32 GT/s 标准封装的判定是布线假设)。边缘 lane 加反向 lane 的 NEXT(−36.0 dB,两瓣 8.5 UI):眼宽 0.748 → 0.737 UI。用解析线合成的 6 端口文件读回:与解析路径眼高差 0.12 mV(读法就位,真实 S 参数仍缺) |

见 [`docs/USAGE.md`](docs/USAGE.md)、[`docs/clock_profile.md`](docs/clock_profile.md);结论与被推翻的判断在 `cairn/LOG.md`。

## 段 7:收端机制(0.9.0)

`rx.bw_hz`(收端前端一阶极点,数据边沿的"树带宽")、`rx.noise_at: sampler | input`(噪声在采样点还是在前端输入 —— CTLE 的噪声代价由此而来)、
`rx.training_ber`(训练在哪个 BER 上居中);默认值全部保持旧行为,bundled 配置指纹逐位相同。机制与数字见 `cairn/receiver.md`。

| 示例 | 问题 | 答案(2026-10-13,0.9.0) |
|---|---|---|
| `09_receiver_front_end.py` | 接收机自己花掉多少 | x1 25 mm:前端 48 / 32 / 24 GHz 眼高 215.6 → 208.8 / 196.5 / 179.9 mV(噪声在采样点);同一 3 mV 改到输入:137.9 / 150.5 / 148.7 mV(窄前端省噪声,32 GHz 附近最好)。35 mm + 32 GHz 前端的 CTLE:噪声在采样点 6 dB 最好 222.7 mV,在输入 4 dB 最好 179.0 mV(6 dB 掉到 168.8)。训练 1e-3 居中:x1 偏 −0.0008 UI(眼宽 −0.002),x5 耦合中间 lane 偏 −0.024 UI、眼宽 0.691 → 0.644。时域滤噪声:采到 68.5 对闭式 69.05 mV |

## 规范数字

本库拿不到 UCIe 规范原文。速率档、BER 目标、bump 间距、reach、模块宽度、眼罩共 15 条,全部在 `data/spec/ucie_survey.yaml`,
每条 `source: survey` 并注明综述出处与"未核实";引擎只按 key 取,结果行打印 `source: xxx`。

```bash
grep "source: survey" data/spec/ucie_survey.yaml
```

## 布局

| 目录 | 内容 |
|---|---|
| `src/d2d_link/config/` | frozen `LinkConfig`、YAML 加载、表单字段声明(`form.py`) |
| `src/d2d_link/clock/` | 剖面读取、**前向时钟模型**(发端 PLL、本地 PLL、树、跟踪器;闭式预算 + 逐符号合成) |
| `src/d2d_link/channel/` | 解析 RLGC 走线 / Touchstone → 脉冲响应;FEXT / NEXT 串扰脉冲;收端前端与噪声整形(段 7) |
| `src/d2d_link/engine/` | 统计引擎(主)、时域引擎(校核)、lane 映射与修复、链路判定 |
| `src/d2d_link/spec/` | 规范数字表的读取 |
| `src/d2d_link/vendor/` | Halo_Serdes 的 S 参数读法 / RLGC / 响应转换,pll_simulator 的相噪合成与积分;完整 SHA 钉住,`tools/vendor_check.py` 守 |
| `tools/` | `fingerprint.py`、`example_drift.py`、`run_examples.py`、`vendor_check.py`、`budget_report.py` |
| `cairn/` | 项目知识:铁律论证、前向时钟、双引擎、串扰、收端、规范来源、坑;`LOG.md` 每轮数字与被推翻的判断 |

## 不做

均衡器与 CDR 的深度(Halo);协议层(flit / CRC / retry 只留 `target.ber` 参数位);规范条文的转述。
