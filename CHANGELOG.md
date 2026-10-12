# 更新日志 / Changelog

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/),按里程碑而非逐条提交组织。

---

## [0.1.0] — 2026-10-12 — 里程碑 1:标准封装、32 GT/s、1 lane、前向时钟 DDR 的时序预算

### 新增
- **配置层**(`config/`):frozen `LinkConfig`(封装、速率、lane、时钟方案、发端、收端、仿真、目标),严格键的 YAML 加载与
  dotted 覆盖,`form.py::SECTIONS` 按 Halo 的方式声明全部表单字段(GUI 不做,字段声明留着,测试保证与 schema 双向一致)。
- **规范数字表**(`data/spec/ucie_survey.yaml` + `spec/`):16 条,全部 `source: survey`,每条带出处与"未核实";引擎按 key 取,
  结果打印 `source: xxx`。`grep "source: survey"` 一次列全。
- **前向时钟模型**(`clock/forwarded.py`,铁律 2):数据与前向时钟共享发端 PLL 的定时抖动(pllsim 剖面或白噪),`correlation`、
  数据 / 时钟 / 树三路独立白抖动、树延时与带宽、逐 lane 一阶零延迟相位跟踪器;闭式预算与逐符号合成同一张 FFT 网格。
  相关 = 1 残余恰为 0;跟踪带宽 ∞ → 0;无跟踪 → 独立功率和;全开情形闭式 / 合成 < 5%。
- **信道**(`channel/`):解析有损传输线(长度、介损、趋肤;标准 / 先进封装 RLGC 预设,可逐项覆盖),Touchstone 经 vendored Halo 读法;
  发端一阶带宽,可选 1 级 CTLE 行为模型;统一到 `sim.osr` 的脉冲响应。
- **统计引擎**(`engine/statistical.py`,主引擎):枚举最大 12 个 ISI 光标 + 高斯余项,解析 `erfc` 尾,到 1e-27 不受 FFT 精度限制;
  抖动在相位轴上以 ≤ σ/4 步长、±12σ 梯形积分;DDR 占空比误差;眼高 / 眼宽在目标 BER 处;采样相位取眼开区间中点。
- **时域引擎**(`engine/timedomain.py`,校核):分块(含过去 / 未来符号)fftconvolve,逐符号前向时钟残余采样,采样点高斯噪声,
  PRBS15/31 向量化;眼图折叠与采样值分布。
- **多 lane 层**(`engine/lanes.py`,铁律 4):逐 lane skew(显式或随机)、deskew 步长的残余、`none` / `spare` / `width_degrade`
  三种修复、公共前向时钟、最差 lane 判定;`lanes.count = 1` 与 x4 的 lane 0 逐位相同。
- **示例 00–03** 与 `examples/expected/`;**工具** `fingerprint.py`(铁律 6)、`example_drift.py`、`run_examples.py`、`vendor_check.py`
  (polar_tx 规矩,`--strict`,完整 SHA);**CI** lint + 测试(3.10 / 3.12)+ 示例冒烟 + vendor 漂移 + examples-full。
- **vendored**:Halo_Serdes@c13da1e6 `channel/touchstone.py`、`channel/analytic.py`、`channel/response.py`(adapted:一行 import)、
  `core/waveform.py`;pll_simulator@00e48a2f `core/colored.py`、`core/jitter.py`。

### 数字(标准封装 25 mm,`configs/standard_32g_x1.yaml`)
- 信道 −2.95 dB @ 16 GHz,主光标 163.3 mV / 200 mV。PLL 带内 186.2 fs,采样器残余 295.3 fs(树泄漏 59.4、数据路径 199.9、
  时钟路径 183.6、树 100.0,功率和)= 0.0095 UI。
- 眼高 209.8 mV / 眼宽 0.772 UI @ 1e-27,对综述目标 40 mV / 0.75 UI 裕度 +169.8 mV / +0.022 UI。
- reach 扫描:30 mm 最后通过,35 mm 眼宽 0.747 UI 不过(眼高 163 mV 仍远超 40 mV);综述 25 mm,比 1.20×。
- 跟踪带宽:白路径抖动下 100 MHz 以下几乎不动(295.4 → 291.0 fs),1 GHz 253.6,半程 4.16 GHz,∞ → 0。
- 统计 / 时域(示例 03):噪声主导 1e-6 处 1.23(24 误码 / 2e7 符号)、抖动主导 1e-6 处 1.22(16 / 2e7)、混合 1e-5 处 0.87(17 / 2e6);
  测试三点(可测 BER 1e-4 量级)0.91 / 0.85 / 混合。

### 测试
- 103 项(`pytest -q`),每条铁律至少一个文件:`test_config` / `test_invariants`(1)、`test_forwarded_clock`(2)、
  `test_engines`(3)、`test_lanes`(4)、`test_spec_sources`(5)、`test_fingerprint`(6),加剖面、信道、统计、时域、vendor、
  drift 工具、示例可导入。
