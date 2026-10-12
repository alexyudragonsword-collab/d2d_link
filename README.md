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

`configs/standard_32g_x1.yaml`:25 mm 有损走线(解析 RLGC,−2.95 dB @ 16 GHz),发端 PLL 相噪来自 pll_simulator 导出的
Markulic 2016 SSPLL 剖面(带内 186 fs),数据 / 时钟路径各 200 fs 白抖动,收端时钟树 30 ps / 20 GHz / 100 fs,2 MHz 相位跟踪。

| 示例 | 问题 | 答案(2026-10-12,`examples/expected/`) |
|---|---|---|
| `00_single_lane_eye.py` | 这条链路的抖动预算与眼 | PLL 的 186 fs 一分不到采样器;残余 295 fs = 树泄漏 59 + 数据路径 200 + 时钟路径 184 + 树 100(功率和)。眼高 209.8 mV / 眼宽 0.772 UI @ 1e-27,对综述目标 40 mV / 0.75 UI 裕度 +169.8 mV / +0.022 UI。时域 40 万符号 0 误码 |
| `01_tracking_bandwidth_sweep.py` | 残余随跟踪带宽 | 相关 = 1、理想树:残余 0.000 fs;无跟踪 282.84 = √(200² + 200²);带宽 ∞ → 0。白路径抖动下 100 MHz 以下几乎不动(295 → 291 fs),半程点 4.2 GHz;ρ 0 → 339 fs |
| `02_reach_sweep.py` | 走线能到多长 | 30 mm 是最后通过的长度(35 mm 眼宽 0.747 < 0.75 UI,眼高还有 163 mV);综述 reach 25 mm,比 1.20× |
| `03_stat_vs_time.py` | 统计 / 时域在 1e-6 处的一致性 | 噪声主导 1e-6:时域 / 统计 1.23(24 误码 / 2e7);抖动主导 1e-6:1.22(16 误码 / 2e7);混合 1e-5:0.87(17 / 2e6)。三点都在 0.5–2× 内 |

见 [`docs/USAGE.md`](docs/USAGE.md)、[`docs/clock_profile.md`](docs/clock_profile.md);结论与被推翻的判断在 `cairn/LOG.md`。

## 规范数字

本库拿不到 UCIe 规范原文。速率档、BER 目标、bump 间距、reach、模块宽度、眼罩全部在 `data/spec/ucie_survey.yaml`,
每条 `source: survey` 并注明综述出处与"未核实";引擎只按 key 取,结果行打印 `source: xxx`。

```bash
grep "source: survey" data/spec/ucie_survey.yaml
```

## 布局

| 目录 | 内容 |
|---|---|
| `src/d2d_link/config/` | frozen `LinkConfig`、YAML 加载、表单字段声明(`form.py`) |
| `src/d2d_link/clock/` | 剖面读取、**前向时钟模型**(闭式预算 + 逐符号合成) |
| `src/d2d_link/channel/` | 解析 RLGC 走线 / Touchstone → 脉冲响应 |
| `src/d2d_link/engine/` | 统计引擎(主)、时域引擎(校核)、lane 映射与修复、链路判定 |
| `src/d2d_link/spec/` | 规范数字表的读取 |
| `src/d2d_link/vendor/` | Halo_Serdes 的 S 参数读法 / RLGC / 响应转换,pll_simulator 的相噪合成与积分;完整 SHA 钉住,`tools/vendor_check.py` 守 |
| `tools/` | `fingerprint.py`、`example_drift.py`、`run_examples.py`、`vendor_check.py` |
| `cairn/` | 项目知识:铁律论证、前向时钟、双引擎、规范来源、坑;`LOG.md` 每轮数字与被推翻的判断 |

## 不做

均衡器与 CDR 的深度(Halo);协议层(flit / CRC / retry 只留 `target.ber` 参数位);规范条文的转述。
