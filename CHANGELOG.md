# 更新日志 / Changelog

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/),按里程碑而非逐条提交组织。

---

## [0.3.0] — 2026-10-13 — 里程碑 3:串扰的耦合线估计、速率档扫描、时序预算报表

### 新增
- **耦合线串扰估计**(`channel.xtalk: coupled`,`channel/coupled.py`):从走线几何算远端串扰幅度 —— lane 间距默认取规范表里该封装的
  **bump 间距中值**(`source: survey`,100–130 → 115 µm;25–55 → 40 µm),线宽 / 介质厚度 / εr 取 `PACKAGE_STACKUP` 预设(模型估计,可逐项覆盖)。
  一阶耦合微带模型:耦合系数 κ = 1/(1 + (s/h)²),奇偶模速度差 (1 − ε_eff/ε_r)(Hammerstad ε_eff;均匀介质 → 本阶无 FEXT),
  X/H|_Nyq = 2π f_n · κ · (1 − ε_eff/ε_r) · len/(2v),封顶 −3 dB;第二邻 lane 取 2 倍间距。形状仍是 `fext` 模式的 k·(jf/fn)/(1 + jf/fn),只换幅度。
- **时序预算报表** `tools/budget_report.py config.yaml [-o x.md] [--json x.json]`:逐项抖动预算(fs 与 UI)、目标与来源、串扰参数、逐 lane 眼与裕度、
  lane 映射;示例 07 用它写出 32 GT/s 标准封装的报表。
- **示例 07**:规范表全部速率档(4–32 GT/s,source: survey)× 标准 25 mm / 先进 2 mm,x5 模块中间 lane,耦合串扰。
- 统计引擎:浴盆窗口**自适应** —— 目标 BER 处的开眼区碰到 ±0.5 UI 窗口边缘时向该侧再扩 0.5 UI(每侧最多一次)。平顶脉冲(短线、低速)
  的"峰值"落在平顶末端、整只眼在一侧,原来只读到半只眼(先进封装 4 GT/s 眼宽 0.516 → 0.982 UI)。未触边的配置逐位不变。
- 测试 +9(`test_coupled` 8、ρ < 1 多块平均 1、自适应窗口 1;127 → 137)。

### 数字
- 耦合线估计:标准封装 25 mm、115 µm 间距、h 30 µm → 最近邻 **−18.6 dB** @ 16 GHz(10 mm 时 −26.6);先进封装 2 mm、40 µm、h 4 µm → −56.9 dB。
  比 M2 的行为级预设(−30 / −24 dB)标准封装强 11 dB、先进封装弱 33 dB。
- 速率档(示例 07,x5 模块中间 lane):标准封装 25 mm 在 4–24 GT/s 全过,**32 GT/s 不过**(眼宽 0.671 < 0.75 UI,眼高 137.5 mV 仍远超 40 mV;
  −18.6 dB 的 FEXT 是主因,示例 05 用 −30 dB 预设时同一模块能过)。先进封装 2 mm:六档全过,眼宽 0.982(4 GT/s)→ 0.786(32 GT/s),眼高 317 → 298 mV;窗口修正前 4–16 GT/s 被截成 0.50–0.75 UI。
- 预算报表(标准 32 GT/s):总 327.0 fs,其中发端泄漏 120.5、本地 PLL 48.1、量化 140.7 fs。
- 指纹:对 M2 基线,旧值逐位相同;新键只有时域结果的 `bursts`。

## [0.2.0] — 2026-10-12 — 里程碑 2:多 lane 模块与收端本地时钟

### 新增
- **收端本地 PLL**(`clocking.local_pll_*`):从 pllsim 剖面(或白噪)来,II 型二阶环路**锁到前向时钟**(schema 拒绝没有环路带宽的
  本地 PLL,铁律 2);前向相位走 H、本地噪声走 1 − H。环路带宽 → ∞ 残余 → 0,→ 0 残余² = 发端 + 本地两路带内功率。
  这是原始简报里"本地时钟也从剖面来 / 带宽 → 0 时两路独立抖动之和"的物理实现;M1 的白路径噪声版是它的退化情形。
- **路径漫游**(`*_wander_s`、`wander_corner_hz`):一阶整形、按块网格归一到 RMS;MHz 级跟踪器因此有了意义(500 fs @ 1 MHz 角经 20 MHz
  跟踪剩 111 fs,同 RMS 白噪剩 95%)。
- **跟踪器延迟与相位插值器量化**(`track_delay_ui`、`pi_step_ui`):L(z) = α z^{−d}/(1 − (1−α)z^{−1});量化在时域真做 round,
  统计引擎把高斯核与 step 宽矩形卷积,`quantisation_sigma_s` = step/√12 与合成 5% 内吻合。
- **lane 间 FEXT 串扰**(`channel.xtalk: fext`):X/H = k·(jf/f_n)/(1 + jf/f_n),幅度按封装预设(`PACKAGE_XTALK_DB` −30 / −24 dB @ Nyquist,
  **模型估计**)或显式给;邻 lane 按**物理**邻接(±1、±2),死 lane 与闲置备用 lane 静默,修复重映射改变邻接;攻击 lane 的相对 skew
  决定串扰脉冲的读取位置。统计引擎把串扰光标与 ISI 同等枚举 / 并方差;时域引擎给每个攻击 lane 独立 PRBS 与分数延迟脉冲。
- `TimeResult.error_bursts`:误码簇数(间隔 > 64 符号算新簇);慢漫游下误码成簇,Poisson 置信区间失效,簇数才是样本量。
- `configs/standard_32g_x16_module.yaml`;示例 04(本地 PLL 带宽)、05(x16 / x64 模块:skew、串扰、修复)、06(新机制上的一致性);
  `data/clock_profiles/bench_wu19_spll_frac_52m_6p253g.yaml`(本地 PLL 用)。

### 数字
- 本地 PLL(示例 04,发端 Markulic SSPLL 186.2 fs,本地 Wu19 SPLL 88.0 fs):环路 1 kHz 残余 205.9 = √(186.2² + 88.0²);10 THz 0.000 fs。
  前向时钟体系下发端泄漏与本地噪声都随环路带宽**同向**下降(132.7 → 98.3、52.7 → 26.5 fs,10 kHz → 1 GHz);折中来自环路前的时钟路径噪声:
  300 fs 白噪的最优在 2.5e7 Hz(100.9 fs,对 1e4 Hz 的 205.8 与 1e10 Hz 的 323.3)。模块配置里本地环路 1 MHz 的总残余 295.2 fs,
  10 MHz 298.1(漫游 142 → 169 fs 过来了)。跟踪器延迟 0 / 4 / 32 UI 几乎无差(294.9 / 295.2 / 296.2 fs);PI 步长 1/64 UI 加 32 fs
  (眼宽 0.780 → 0.768),1/16 UI 加到 636 fs(0.724)。
- 模块(示例 05,标准封装 x16、20 mm、lane 5 死、降宽到上半 x8):8 lane 全过,眼高 212.1–228.1 mV、眼宽 0.752–0.768 UI,
  最差 lane 眼宽 0.752 对目标 0.75(survey)只剩 0.002 UI;串扰关掉最小眼高 233.4 mV / 眼宽 0.770;预设 −30 dB 的串扰费 21 mV / 0.018 UI;
  −20 dB 时 155.2 mV / 0.688 UI,链路 FAIL。先进封装 x64、两死 lane、4 备用:64/64 通过,52 个逻辑 lane 重映射,邻 lane 数分布
  [0, 0, 2, 10, 52](0..4 个),眼高 237.2–283.2 mV,眼宽最小 0.755 UI。
- 一致性(示例 06,2e6–4e6 符号):本地 PLL 有色时钟噪声 0.92(36 误码)、量化 + 4 UI 延迟跟踪器 0.74(29)、x3 模块 −14 dB 串扰中间 lane
  0.86(56;边 lane 0.90 / 0.92)、先进封装 + CTLE + 0.06 UI DCD 0.80(31)、路径漫游 2.5 ps/路径经 2 MHz 跟踪器 + 噪声 0.82(32);五点 0.74–0.92,误码都各在自己的簇里(36 误码 35 簇等)。
  第一次 5 ps 纯漫游点 0.30×(113 误码只有几簇),见 LOG。
- M1 指纹:2016 值里 1594 个旧值**逐位相同**,422 个"None →"全是新键(每 lane 新增 3 个 extras,新配置 1 个)。

### 测试
- 103 → 127 项(`test_local_pll` 10、`test_xtalk` 7、`test_engines_m2` 4、law 2 静态测试改写,`test_examples` 参数化到 7 个示例)。

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
