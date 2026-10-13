# 更新日志 / Changelog

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/),按里程碑而非逐条提交组织。

---

## [0.7.0] — 2026-10-13 — 段 4:性能与深一致性(指纹逐位相同)

### 新增
- **深一致性点**:`tests/test_engines.py::test_one_in_a_million_point_within_2x`(1e-6,2.5e7 符号,套件内,~3 min);
  `tests/test_engines_deep.py`(`pytest -m slow`,默认排除):1e9 符号的 3e-8 点,每周由 `examples-full.yml` 的 `deep` 作业跑;
  `D2D_DEEP_SYMBOLS=2500000000 D2D_DEEP_BER=1e-8` 是真正的 1e-8 / 25 误码点(≈ 5 h,手动)。
- **流式抖动合成**:`ForwardedClock.synthesize_blocks()` 逐块产出;`run_time` 在 > 2^24 符号时流式消费(`_JitterFeed`),2.5e9 符号不再要 20 GB。
- **`sim.time_mode: samples`**:只算采样值(每符号光标按自己的采样瞬间线性内插,与波形路径 `np.interp` 同一算术;误码逐个相同,样本差 1e-12 V),
  `sim.time_cursor_floor`(默认 1e-6 × 主光标)是唯一近似。诚实结论:有损线的脉冲尾 130 UI 内都高于 1e-6,光标一个不少,
  **不比 FFT 波形快**(1e6 符号 9 s 对 6 s);短记忆信道(先进 2 mm、floor 1e-4)快 4×。无眼图轨迹。
- `run_link` 对邻接与残余 skew 相同的 lane 复用统计结果(x16 内侧 6 lane 一次算完);时域 `extras["mode" | "n_cursors_used"]`。

### 修改(逐位不变)
- 统计引擎:`_shift_add` 对 |c| < bin 的光标把两次相同加法合成 `a + a`(精确)、`log10_tail` 标量路径不 reshape、`_logsumexp` 一维快路径、
  `errstate` 只进一次、模型缓存上限 5 万。x1 每 lane 4.6 → 4.2 s。指纹 `fp_p3` → `fp_p4a` 2698 项逐位相同。
- `pytest` 默认 `-m 'not slow'`;`tools/run_examples.py` 默认超时 2400 s(段 3 已提)。

### 没做(会动数字,记入 ROADMAP P2 #0)
- 眼边求根相位贴细网格(省 ~1.8 s/lane,边差 ~1e-5 UI)、`half_eye` 60 → 30 步、方案里"快 10–50×"的只采样时域(理由见上)。
- 方案里的 `width_degrade` 非 2 幂、攻击 lane 按逻辑编号播种:前者 UCIe 的宽度只有 16 / 64 与其一半,非 2 幂是实验配置,不改;后者会动有串扰的时域数字,留给下一次。

---

## [0.6.0] — 2026-10-13 — 段 3:时钟模型保真(杂散、真反馈跟踪器、PLL 带宽口径、漫游频带、块缝、发端 DCD;附带眼边求根)

### 修改(模型)
- **杂散进两个引擎**(`clock/forwarded.py::spur_terms`):剖面 `spurs` 是确定性正弦相位项,发端杂散共模经 |E(1 − ρG)| 泄漏
  (ρ < 1 时另一项经 |E√(1−ρ²)G|,相位独立),本地 PLL 杂散经 |E·H_tree·(1 − H_pll)|。闭式 `JitterBudget.spur_s` = √(ΣA²/2)、
  `gaussian_s` 单列、`total_s` 功率相加;统计引擎把每条残余幅度作**反正弦核**与高斯核卷积(`jitter_quadrature(..., sinusoid_amplitudes_ui)`,
  远小于 σ 的并入方差);合成逐块加正弦、相位按全局边沿序号连续(无杂散的剖面不消耗随机数,实现逐位不变)。
- **跟踪器真反馈**:θ[k] = θ[k−1] + α(Δ[k−d] − θ[k−1−d]),L(z) = α z^{−d}/(1 − z^{−1} + α z^{−(d+1)});d = 0 与此前完全相同。
  `tracker_stability_margin(α, d)` ≤ 0 时 `ForwardedClock` 构造拒绝(此前 M2 的写法只延迟估计值,永不失稳)。
- **`local_pll_bw_hz` → `local_pll_fn_hz`**(它是 ω_n/2π,不是带宽);loader 读到旧键给 DeprecationWarning 并沿用;
  `local_pll_bw_3db_hz()` 报 −3 dB 带宽(2.48 f_n @ ζ = 1)。bundled 配置、示例、测试已改名。
- **漫游 RMS 的频带**:S0 由解析积分在 [`wander_floor_hz`, fs/2] 上归一(新字段,默认 fs/`jitter_block`,与闭式频带下沿一致),
  不再在块网格上求和;网格求和比积分多约 4%,bundled 的漫游项因此动 ~2%(x16 模块 clock_wander 81.4 → 83.7 fs 量级)。
- **发端占空比误差** `tx_dcd_ui`:对数据与前向时钟共模,直接用前向时钟边沿采样时抵消,有本地 PLL 重生成时钟时全部显现
  (`ClockingConfig.sampling_dcd_ui`);收端 `dcd_ui` 语义不变。
- **眼宽的边在真实浴盆上求根**(`StatisticalEngine.eye_edge`,regula falsi,容差 1e-5 UI):段 3 调试中发现两个网格点之间按 log BER 内插
  的边会被外侧那个点(低一百个数量级、由抖动核最外节点决定)带偏,眼宽随网格密度与核范围漂 —— 16 点网格 2e-3 UI,64 点 1e-3 UI。
  现在 16 与 128 点的眼宽相同到 1e-5。**体检里"短线眼宽 > 1 UI"(1.008–1.026)就是这个内插误差**:真实边给 0.993–0.995 UI;
  上限 1 UI 的截断保留,测试改为强制宽开口。
- 抖动核的相位网格不细于 base/256(fs 级杂散曾把网格逼细一千倍),范围多 2 个保护节点。

### 新增
- `ForwardedClock.block_step_ratio`(块边界一步 RMS / 块内一步 RMS,时域 `extras["block_step_ratio"]`):x16 模块 ≈ 2,分块合成有可测的缝,记入 ROADMAP。
- 报表:杂散行、`local_pll_fn_hz` / `local_pll_bw_3db_hz` / `spur_terms`;示例 04 打 f_n 与 −3 dB,"两个独立时钟"那行加上杂散项。
- 测试(+10,`tests/test_clock_fidelity.py`):杂散闭式 vs 合成 5%、本地 PLL 杂散经 1 − H、反正弦核归一与方差、杂散主导链路两引擎 1e-4 处 2× 内、
  延迟在反馈里(临界、失稳拒绝、峰化 > 1.03×、d = 0 不变)、−3 dB、旧键告警、漫游频带解析归一且与块长无关、块缝度量、Tx DCD 门控;
  统计:眼宽与相位网格无关(16 vs 128 点 2e-4 内)。

### 数字(与 0.5.0 比)
- x1:眼宽 0.775 → 0.774 UI(边求根),眼高 215.6 mV 不变;每 lane 2.8 → 4.6 s(求根相位不命中模型缓存,段 4 处理)。
- bundled 剖面的杂散很小:Wu19 本地 PLL 四条在 x16 模块采样器处残余 0.003–2.4 fs(`spur_s` 1.8 fs);示例 04 的 1 kHz 环路让 62 kHz 杂散全过,
  205.9 → 206.8 fs(杂散 19 fs)。x16 模块 2 MHz / 4 UI 跟踪器真反馈与旧写法差 0.04%。
- 示例 05:x16 八 lane 眼宽 −0.001 UI(边求根),最差 lane 5 228.4 mV / 0.753 UI,仍过;x64 最差 lane 54,眼宽 min 0.755。示例 07:标准 32 GT/s 中间 lane
  143.2 / 0.693 → 143.1 mV / 0.691 UI 仍不过;先进六档全过(4 GT/s 眼宽 0.979 → 0.960:粗网格上内插误差最大)。示例 03 三点、06 五点仍全在 0.5–2× 内
  (06 本地 PLL 点 1.03 → 0.80:杂散相位的随机数改变了噪声实现,40 → 31 误码)。`tools/run_examples.py` 默认单例超时 900 → 2400 s(05 / 07 现在各约 15 min,段 4 的性能目标)。

---

## [0.5.0] — 2026-10-13 — 段 2:结论可信度 B(一套几何驱动一切;数字再变一次,逐项解释在 `cairn/LOG.md`)

### 修改(模型)
- **L、C 由几何推出**(`config/schema.py::LinkConfig.rlgc`):`PACKAGE_RLGC` 只留 R_dc、R_skin、tanδ、G 与 **Z0**(50 Ω);
  L = Z0·√ε_eff / c、C = √ε_eff / (Z0·c),ε_eff 是叠层(w、h、ε_r)的 Hammerstad 值 —— 与 `channel/coupled.py` 的串扰估计共用一个
  介电常数。此前预设自带的 L、C 隐含 ε_eff 3.94 / 5.75,与叠层 ε_r 3.5 / 3.3 矛盾(体检 #3)。显式 `l_h_m` / `c_f_m` 仍可覆盖;
  新字段 `channel.z0_ohm`。标准封装 ε_eff 2.54、先进 2.38,Z0 恰为 50 Ω。
- **模型参数带来源**:`data/spec/model_presets.yaml`(18 条,全部 `source: model`,cite + note),`d2d_link.spec.preset()` 读取,
  `PACKAGE_RLGC / PACKAGE_STACKUP / PACKAGE_XTALK_DB` 由它生成;`grep -c "source: model"` = 18。两张表互不混放(loader 校验)。
- **发端带宽默认 2 × Nyquist**(`tx.bw_hz` 留空;`inf` = 理想边沿),`LinkConfig.tx_bw_hz` 解析。bundled 配置都显式 60 GHz,不受影响;
  库默认配置(测试、合成指纹例)因此变。
- **耦合长度**:`channel.coupled_length_mm`,Touchstone 信道配 `xtalk: coupled` 时必填(文件里没有走线长度);解析线默认 = `length_mm`。

### 新增
- `tools/budget_report.py --sensitivity`:对每条 `source: model` 预设与结论依赖的 `source: survey` 数(bump 间距)±20%、眼罩目标 ±10 mV /
  ±0.05 UI,列最差 lane 裕度并标出翻转 PASS/FAIL 的参数("哪些猜测决定结论")。`sensitivity()` / `sensitivity_knobs()` 可编程调用。
- 报表 JSON 增加 `channel_model`(RLGC 与 `rlgc_source: model`)、串扰 `adjacent_source`;`describe()` 增加 `stackup_source`、`coupled_length_mm`、
  `eps_eff`;示例 00 / 07 打印预设来源。
- 测试(+5):Z0 = √(L/C) = 50、c²LC = ε_eff(Hammerstad)、显式 L / Z0 / ε_r 覆盖;发端带宽默认与 `inf`;预设表 grep 计数与两表互斥;
  Touchstone + coupled 必填长度、耦合长度线性;敏感性报告在"目标贴着眼"的链路上标出 R_skin 与 Z0 翻转、R_dc 不翻转。

### 数字(与 0.4.0 比)
- 标准封装 25 mm @ 16 GHz 插损 −2.95 → **−2.80 dB**(介质损耗 ∝ √ε_eff:√2.54 / √3.94 = 0.80;导体损耗不变,Z0 本来就是 49.8 Ω);
  主光标 163.3 → 164.6 mV;x1 眼 209.8 mV / 0.772 UI → **215.6 mV / 0.775 UI**,相位 −0.0198 → −0.0078(线更快:延时 √ε_eff 比 0.80)。
- reach 扫描:每 5 mm 插损 −0.59 → −0.56 dB;**30 → 35 mm** 是最后通过的长度(35 mm 眼宽 0.747 → 0.753 UI);对综述 25 mm 的比 1.20× → 1.40×。
- 示例 05:x16 模块八个 lane 眼高 +4.6…+4.8 mV、眼宽 +0.002 UI,最差 lane 仍是逻辑 5(228.5 mV / 0.754 UI);x64 最差 lane 54 不变。
  示例 07:标准 25 mm 32 GT/s 中间 lane 138.7 mV / 0.685 UI → 143.2 mV / 0.693 UI,仍因眼宽不过;4–24 GT/s 过;先进 2 mm 六档全过。
  示例 03 / 06 八个 2× 点全部仍在 0.5–2× 内(1.18 / 0.96 / 0.88;1.03 / 0.74 / 0.75 / 0.84 / 0.83),工作点由二分重新找到。

---

## [0.4.0] — 2026-10-13 — 段 1:结论可信度 A(数字会变,逐项解释在 `cairn/LOG.md`)

### 修改(模型)
- **ISI 分布精确化**(`engine/statistical.py`):"枚举最大 12 个光标 + 高斯余项"换成电压网格上的精确移位相加分布
  (`sim.stat_isi_bin_v`,默认 50 µV;分数移位线性分到相邻两格)。一个光标也不丢。串扰眼由此收敛:x5 耦合模块中间 lane
  (349 个光标)bin 100/50/20/10 µV → 眼宽 0.6844/0.6848/0.68488/0.68490 UI;旧枚举给 0.671(M=12)且随 M 不收敛。
  `sim.stat_enumerate_cursors` 字段删除(配置文件里出现会被 loader 拒绝)。
- **log 域尾**:`log_ndtr` + logsumexp(numpy 实现;scipy 的每次调用 0.5 ms 开销占一半运行时间)。`StatResult.log10_ber` 是原始量,
  `ber` 是其反对数(1e-308 以下为 0.0);`bathtub_log10_ber` 同理。`summary()` 打 `BER 10^-436.0`。决策阈值处的尾按(模型、噪声)缓存。
- **最差 lane 按裕度**(`engine/lanes.py`):`LinkResult.worst` 取 `StatResult.margin = min(眼高裕度/目标, 眼宽裕度/目标)` 最小者;
  `log10_ber_worst` / `ber_worst`;`consistency_ratios` 用 log10 差。此前按 BER 取,1e-27 下全为 0.0,永远 lane 0。
- **偏心 lane 的眼宽**:采样点偏离眼中心(无跟踪器的 deskew 残余、固定相位)时眼宽取围绕实际采样点的对称开口
  `2·min(right − φ, φ − left)`,不再把整条浴盆的开口记给它。
- **相位参考**(`channel/model.py::LinkResponse.main_index`):脉冲半幅宽的中点,不再是峰值样本(平顶脉冲上峰值三次把窗口带偏)。
  bundled 配置的 `phase_ui` 整体平移,眼高 / 眼宽不因此改变。
- **眼宽硬上限 1 UI**:`extras["eye_width_clipped"]` / `eye_width_raw_ui`,`summary()` 与报表打 "(clipped)"。
  1 mm 无发端极点的线原始读数 1.026 UI → 1.000 (clipped)。
- **静态 skew 与跟踪器的口径**(`residual_skew_ui(cfg, skew, tracked=None)`):有每 lane 跟踪器时静态残余为 0(直流被环路跟掉),
  只剩 PI 量化;无跟踪器时保留 skew 模步长。此前两者同时计入。`standard_32g_x16_module` 八个 lane 的残余 skew 归零。
- **时域引擎的分块填充**(`engine/timedomain.py`):`n_tail` / `n_pre` 按实际相位 + skew + DCD + |抖动|max 加余量;
  采样点越界 **assert**,不再被 `np.interp` 静默钳位。

### 新增
- `StatResult.margin`、`log10_tail()`、`extras["sigma_isi_v" | "isi_bins" | "isi_bin_v" | "log10_ber_min"]`;
  `tools/budget_report.py` lane 表打 log10 BER 与 clipped;`tools/fingerprint.py` 记录 `log10_ber`。
- 测试(144 项):网格收敛(bin 100 vs 50 µV 眼宽差 < 0.002 UI)、log 域尾不下溢、眼宽 ≤ 1 UI 且有标志、最差 lane 按裕度(段 0 的 xfail 转正)、
  有跟踪器时残余 skew 为 0 且两 lane 相同。

### 数字(与 0.3.1 比;全文见 LOG)
- x1 25 mm:眼 209.8 mV / 0.772 UI 不变,相位 −0.0200 → −0.0198 UI;每 lane 2.8 s(旧 3–4 s)。
- reach 扫描:≤ 30 mm 眼高变 ≤ 0.2 mV;35–60 mm 眼高 +0.6…+3.4 mV、眼宽 +0.000…+0.007 UI(旧高斯余项在长线上悲观);30 mm 仍是最后通过的长度。
- x16 模块(fingerprint 网格):眼宽 +0.005 UI、眼高 −1…+3 mV、相位从 −0.02…−0.07 收到 −0.015 左右(skew 口径);x64:眼宽 0.8096 → 0.8155。
- 示例 03 / 06 的 2× 点逐行不变(统计 / 时域两边同一口径,工作点由二分重新找到同一处)。
- 示例 05:x16 模块最差 lane 从“永远 lane 0”(228.1 mV / 0.763 UI)变成逻辑 lane 5(223.7 mV / 0.752 UI,裕度最小);八个 lane 残余 skew 0;
  x64 最差 lane 54(物理 56)。示例 07:标准 25 mm 在 32 GT/s 的中间 lane 眼 137.5 mV / 0.671 UI → 138.7 mV / 0.685 UI,仍不过(眼宽);
  24 GT/s 0.789 → 0.791 UI;先进封装六档结论不变。

### 移除
- `IsiModel.isi_values / sigma_rest / n_enumerated`、`extras["n_enumerated" | "sigma_isi_rest_v" | "ber_min"]`、`sim.stat_enumerate_cursors`。

---

## [0.3.1] — 2026-10-13 — 段 0:卫生轮(体检后;指纹逐位相同)

### 修复
- 文档与数字:规范表是 **15** 条(此前 ROADMAP / CHANGELOG / LOG / spec-sources 都写 16);README 里"PLL 的 186 fs 一分不到采样器"改为
  "经前向时钟抵消,59.4 fs 经树的延时 / 带宽泄漏";"同一模块在 −30 dB 下能过"改为点明示例 05 与 07 是不同模块;`cairn/engines.md` 一行过期的
  测试点、`architecture-invariants.md` §3 "串扰不在本轮"、三篇专题的 `updated`;`tools/run_examples.py` docstring 的 Halo 残留;
  CHANGELOG 0.3.0 的 `test_coupled` 计数。
- 示例 02 第 47 行 `and/or` 写法永远打印字面量 `1e-27`:改为打印解析出的目标与来源(输出多了 `(source: survey)`,期望输出刷新)。
- `data/spec/ucie_survey.yaml` 文件头不再含标签字串:`grep -c "source: survey"` 恰好 = 15;测试断言的就是这条命令。
- ROADMAP:P1 #2 的复现步骤现在可跑(`configs/standard_32g_x5_coupled.yaml`,示例 07 改为加载它;先进封装的长度取规范表的 reach),
  编号连续,体检挂起的模型问题按分段方案登记在 P2 #0。

### 删除
- 死代码:`StatisticalEngine.eye_width / eye_edges`、`with_phase`、`core.prbs.prbs_bits`。

### 守卫(+4 测试,137 → 141;其中 1 项 xfail)
- 规范表:条目数 = 15、每条 survey 的 note 必含"未核实"、`grep -c` 计数;bundled 配置落在规范表包络内(摆幅等于表值、长度 ≤ reach、
  lane 数 ≤ 模块宽度、速率在速率档内)。
- 铁律 1:`config/`、`tools/`、`examples/` 里不得给字段赋规范数字(`data_rate_gtps=`、`swing_vpp=0.4`、`length_mm=25.0/2.0`、`1e-27`、眼罩);
  schema 里的两个默认值(32.0、0.4)显式放行,段 5 从表解析后移除放行。
- 最差 lane 按裕度取的测试先以 `xfail(strict)` 登记(段 1 修实现);"reach 与综述 2× 内"进测试套件。

### CI
- 测试矩阵 3.10 / 3.11 / 3.12 / 3.13;`test-floor` 作业钉 numpy 1.26 / scipy 1.11 / pyyaml 6.0 且不装可选依赖;
  `fingerprint` 作业:PR 上同一 runner 记录 base 与 head 并比对,有差异且无 `numbers-move` 标签即红,push 时只记录并存 artifact;
  pip 缓存、`concurrency` 取消;examples-full 的路径过滤加 `tools/**`。

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
- 测试 +10(`test_coupled` 7、ρ < 1 多块平均 1、自适应窗口 1、示例数 1;127 → 137)。

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
- **规范数字表**(`data/spec/ucie_survey.yaml` + `spec/`):15 条,全部 `source: survey`,每条带出处与"未核实";引擎按 key 取,
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
