# 更新日志 / Changelog

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/),按里程碑而非逐条提交组织。

---

## [0.12.6] — 2026-11-03 — 段 14:第三次体检的工程修复(指纹逐位相同)

### 修复
- **每周深测下周一会红**:`test_engines_deep.py` 调好噪声后钉住相位(不钉时统计引擎移到 +0.22 UI,期望 3.4 个误码对门槛 15)。`slow` 标记与 docstring 的时长改对(1e9 符号 ~40 min)。
- **指纹 CI(铁律 6)**:放行条件改为推送带来的**每个**提交里有 `(numbers-move` 标记(只看 head 时,段 11 快进 main 红过;head 写了又会豁免更早未声明的变动);
  推送不再被 `cancel-in-progress` 取消(性能轮 III 的 run 被取消后没人比对);新分支首推与 force-push 跟 main 的 merge base 比,不再静默跳过,找不到 base 报错。
- **`example_drift accept` 拦截**:引用该示例的表格里还有旧值时拒绝写入(`--force` 越过);段 12 的 README "194.7 mV" 就是这样漏的。派生数检查进测试;比较短语识别 UI / mV / fs / ps。
- GUI:worker 死后的提交不再永远 queued(提交时遇到坏池就重建一次;每个死池只重建一次);坏的场景 yaml 在 Compare with 与场景栏都只报错不抛异常;速率编辑先校验再写、
  osr 由文件的速率与 osr 经 `with_data_rate` 算出(与编辑历史无关);This page 卡跟住运行中的任务;无活 lane 时 `worst` 报清楚的原因。
- 打包:`gui/assets/*.js` 进 package-data(非 editable 安装丢了键盘激活),测试守每个 asset 后缀。
- 文档:README 194.7 → 194.6、表头版本;CHANGELOG 0.12.4 的误引(≤ 2.2 mV、292.3 → 311.3);cairn/gui.md 三处过期(加更正说明);receiver.md 69.07 / 0.87;USAGE 重复行;错字。
  ROADMAP:已结的 P2 #1 移到边界,P1 #2 的前后矛盾改正。
- 测试 +9(GUI 6、drift 2、package asset 1),弱断言三处改实(`A and B or C`、`passes in (True, False)`、main() 的 shutdown)。

## [0.12.6 之前] — 段 13:结构性探针进测试(只加测试)

- `tests/test_structure.py`:对 `configs/` 下每个配置检查因果(LC 到达前一个 UI 的能量 < 0.6 % 主光标,今天最大 0.30 %;串扰脉冲同样)、无源(|H| ≤ 1、H(0) 实正)、
  网格顶残余响应 < 0.15(今天最大 0.076)、脉冲窗末尾 < 2e-3 主光标(防循环卷绕;今天 6.3e-4)、全部波特采样和 = 直流(1e-3 内)与光标窗和(1e-2 内)、
  ISI PMF 与抖动求积是概率测度且求积方差等于预算(3 % 内)。30 项 1.3 s。两个曾经活过所有一致性测试的模型错误(非因果走线、网格砖墙)各对应其中一条。

---

## [0.12.5] — 2026-11-03 — 性能轮 III(指纹逐位相同)

### 变更
- 一个浴盆要的所有 ISI 模型一次建(`StatisticalEngine.prefetch` → `isi_models`):各相位的亚 bin 核的分块在**一个**二维数组上建(行 = 所有相位的所有块,末宽 33),
  16 步的 Python 开销从每模型一次变成每批一次;眼边离网格那一步的 ~50 个节点模型也成批建。
- `read_cursors` 直接索引代替 `np.interp` 的二分搜索,脉冲峰值在 `LinkResponse` 里算一次(每次调用扫 16k 样本找峰值占了这个函数的大半)。
- `_shift_add` 第一份半权拷贝对零数组用赋值代替加法。
- cProfile 下 x16 模块 28.0 → 23.8 s(−15 %);空闲机器 x1 1.0 s、x5 耦合 13.9 s、x16 18.3 s(轮 II 后 1.3 / 13.6 / 19.3,机器噪声 ±10 %)。
  三处都是同一算术换批量 / 换索引:指纹 3194 项逐位相同。剩下的热点是每模型 45 次 `_shift_add`(6 s,Python 开销界)、块核相卷(3.6 s)、`log10_tail`(4 s)—— 再往下要 C 扩展或 numba,不做。
- 测试 +1(批量模型与单个逐位相同;直接索引与 `np.interp` 逐位相同)。

---

## [0.12.4] — 2026-11-03 — 段 12:波形网格顶频不随速率缩(示例 07 的低速档数字会变)

### 修正
- **速率扫描的低速档偏低是网格砖墙,不是 RC**:`config.with_data_rate(cfg, rate)` 改速率时缩放 `sim.osr`,网格顶 osr·f_N 保持(32 GT/s 配置的 512 GHz);
  示例 07、GUI `rate_sweep` 任务与标题句的速率控件都走它。先进 2 mm 4 GT/s:主光标 182.3 → 189.5 mV,眼 292.3 → 311.3 mV;8 GT/s +0.6 mV;标准 25 mm 低速档 ≤ 2.2 mV(更正:初稿写 ≤ 1.6 mV、眼 293 → 311,第三次体检对出)。
- `LinkResponse.grid_top_response`(|H_total(f_max)| / |H_total(0)|)进 `extras` 与报告 `link` 段(`grid_top_ghz` 一并);> 0.2 时 `link_response` 告警。
- ROADMAP P2 #1 改写:段 2 的"RDL 线 RC 主导、Z0 只是高频渐近"归因撤回,RC 的真实量级(H(0) 0.9615)记入;终端口径不改。
- 测试 +3(`with_data_rate`、网格顶测量与告警、GUI 速率编辑带 osr)。bundled 配置都在 32 GT/s,指纹 3100 项逐位相同,新增 94 个 `x.grid_top_response` 键。

---

## [0.12.3] — 2026-11-03 — 段 11:Touchstone 耦合项带外(bundled 指纹逐位相同)

### 修正
- `channel/touchstone_se.py`:单端多端口文件的耦合项在文件带边以上不再填 0,而是沿直通路径的衰减延拓(`model.extend_band_like`:X(f) = X(f_edge)·H(f)/H(f_edge))。
  有损耦合的合成 3 lane 文件(FEXT −20 / −30 dB × 线)截到 50 GHz:中间 lane 对全带文件从差 −3.5 mV / +0.010 UI 到 +0.1 mV / +0.005 UI;截到 100 GHz 差 +0.1 mV / +0.001 UI。
  按耦合项自身斜率延拓是 +0.006 UI,沿直通略好且有物理依据(耦合形状在带边饱和,衰减与直通共享)。ROADMAP P2 #3 相应改写。
- 文档引用数核对(9b 之后):`cairn/engines.md` 网格无关性一行标注 0.11 的数;其余历史数字都已带版本标注。
- 测试 +1(`test_touchstone_coupling_follows_the_through_path_past_the_band`)。bundled 配置没有 Touchstone 信道,指纹逐位相同。

---

## [0.12.2] — 2026-11-03 — 性能轮 II(指纹只差末位)

### 变更
- **亚 bin 光标的核分块构造**(`engine/statistical.py::small_kernel`):480 个 3 抽头核不再逐个 `np.convolve`(每次 6 µs 开销,占模块运行时间一半),
  而是切成 16 个一块、每块的核在二维数组上一次建成、再把块核卷到一起;单个 480 光标的核 1.12 → 0.48 ms。
- **先核后链**(`_assemble`):大光标的移位相加链从核出发,不再把 2400 bin 的链与 960 抽头的核做 2.3 M 次乘加的卷积。
- 数字:x1 每 lane 2.6 → 1.5 s;x5 耦合模块 48 → 15 s;x16 模块 50 → 23 s(cProfile 下量;空闲机器见 LOG)。
  两处都是同一组因子换了结合顺序:指纹 `fp_10` → `fp_11` 3100 项中 134 变(93 项是浴盆 / 光标数组的摘要),数值最大相对差 6.5e-14(`ber`,它是 10^log10 的反对数)、相位 5e-15、眼高 / 眼宽 / log10 BER ≤ 2e-16;眼高 / 眼宽 / 相位 / log10 BER 没有一个在打印精度上变。
- ROADMAP P1 #2 的 x5 耦合敏感性用 0.12 重跑:名义裕度 −0.161,**仍然没有任何单个 ±20 % 的估计能翻转 FAIL**;最接近 0 的是介质厚 24 µm 的 −0.095、眼宽目标 0.70 UI 的 −0.101、bump 间距 138 µm 的 −0.107(0.11:−0.054 / −0.061 / −0.071);17 次运行 3 min 59 s(0.11 的 6 min 7 s)。

---

## [0.12.1] — 2026-11-03 — 段 10:GUI 健壮性(指纹逐位相同)

### 修复
- **每秒整页重绘**:回调主体搬到 `App.handle`,`render_keys()` 给页面 / 右栏 / 抽屉各一把渲染键,什么都没变的 tick 全部 `no_update`(HTTP 204);
  跑任务时每秒只重绘队列卡;标签页隐藏时轮询暂停(`wake` 5 s + 客户端回调)。
- **失败有反馈**:当前配置的运行失败 → 页面红色横幅(错误原文)+ This page 状态;旧结果只置灰保留。`current_result` 对"不是当前配置的结果"一律标 stale。
  worker 进程死掉(`BrokenProcessPool`)时进程池重建、任务标 failed 并说明。
- **磁盘缓存带版本号**:`{"version", "result"}`,别的版本或没有版本键的文件忽略(0.12.0 动了每一只眼,旧缓存会端旧数)。
- **编辑被拒说原因**:转换与 schema 校验都包进 `apply_edit`,`edit_error` 显示在抽屉底部与 This page 卡;int 字段拒绝非整数(`lanes.count` 4.5 以前静默成 4)。
- 场景栏按配置哈希找文件自己的运行(以前按 label,带 override 的运行冒充文件的结果);Queue 的 ✕ 只给排队中的任务(进程池无法中断已开始的);
  导出按钮改模式 id;`atexit` / `main` 的 `finally` 调 `shutdown()`。
- 可访问性:可点 Div 加 `role=button tabIndex=0`、Enter / 空格激活(`assets/keys.js`)、`:focus-visible` 轮廓;窄于 1100 px 单栏。
- `d2d_link.__version__` 与 pyproject 对齐(0.12.0 漏了),加测试。

### 测试
- `tests/test_gui.py` +8:tick 不重绘 / 点选 / 编辑 / 丢弃走 `App.handle`;失败路径;编辑拒绝;场景匹配;导出;缓存版本;`workers=1` 进程池(排队、取消、进度);`main()` 参数。
  套件 21 项 GUI 测试 19 s。无头 Chromium 实跑:0 条控制台错误,下载、抽屉、点选、键盘 Enter 开场景都通过。

---

## [0.12.0] — 2026-11-02 — 段 9b:可信度 C(数字会变:走线因果化、脉冲窗、Touchstone 带外、训练窗、报告标签)

### 修正(会动结论)
- **解析走线因果化**:`ChannelModel.from_rlgc` 在 L 上加皮肤效应的内电感 r_skin/(2π√f)(表面阻抗 (1 + j) r_skin√f 的虚部;vendored `skin_effect_rlgc`
  只给实部,H(f) 违反因果、丢掉有损线的群延时色散)。x1 25 mm:到达前能量 6.5 % → 1 % 主光标,IL −2.80 → −2.77 dB,σ_ISI 11.8 → 15.2 mV,
  **眼 215.6 mV / 0.774 UI → 209.7 mV / 0.761 UI**(眼宽裕度 +0.024 → +0.011)。`channel.skin_inductance: false` 复现旧模型。
  **示例 02 的 reach 35 mm → 25 mm**(30 mm 眼宽 0.747 UI 不过;对综述 25 mm 的比 1.40× → 1.00×)。
  **示例 05 的 x16 / 20 mm 模块(−30 dB 预设)从 PASS 变 FAIL**:最差 lane 5 眼宽 0.753 → 0.740 UI。x5 耦合模块更深地 FAIL(中间 lane 0.691 → 0.633 UI,裕度 −0.118 → −0.161);
  **示例 07 标准封装 24 GT/s 起不过**(之前 32 GT/s 起);**示例 08 带状线 x5 也不过**(0.761 → 0.748 UI)—— 到 0.11 为止「32 GT/s 标准封装的判定是布线假设」不再成立。
  上游 Halo_Serdes 同一问题,报告文本在会话 scratchpad `halo_upstream_skin_inductance.md`。
- **脉冲窗与光标数进配置**:`channel.n_freq` 默认 2048 → 8192(时间窗 128 → 512 UI),`sim.stat_cursor_reach`(每侧 256,旧写死 64)、
  `sim.stat_cursor_floor`(1e-6 × 峰值,旧 1e-9)。x1:+0.8 mV / +5e-4 UI;8192 → 16384 再变 < 2e-4 UI。
- **Touchstone 带外延拓** `channel/model.py::extend_band`:直通路径在文件带边以上按最后十倍频的 log|H| 斜率(不升)与群延时延拓,两种读法都走;
  耦合项带外仍填 0。有损 25 mm 线截到 50 GHz 的文件:眼宽对闭式 −0.013 → +0.002 UI。
- **训练窗**:`bathtub_around_the_eye(target, training_ber)` 对训练 BER 的开眼也扩窗(5 mm / 60 GHz / 100 fs:训练中心 −0.020 → −0.030 UI,真值 −0.030)。
- `rx.bw_hz ≤ sim.osr · f_N / 4`(跨字段校验):闭式噪声积到 ∞、脉冲与时域到网格 f_max,1 THz 极点差 1.8×。
- 报告层 `crosstalk` 段对 `xtalk: touchstone` 给文件自己的 Nyquist 耦合(`adjacent_source: file`),不再是预设 −30 dB 的 "model";
  lane 的 `extras["xtalk_adjacent_db"] / ["xtalk_source"]`。
- `StatResult.sigma_sampling_s` = √(高斯预算² + PI 步长²/12);`summary()` 与 GUI Inspector 打 "(+ PI step: … fs at the sampler)"(x5:296.5 → 328.2 fs)。

### 测试
- 新增 8 项:走线因果(提前一 UI 处能量 < 0.5 %)、窗 / 光标收敛、Touchstone 50 GHz 截断 + 砖墙对照、报告标签、`rx.bw_hz` 上限、训练窗、
  **低噪声 ISI 支撑一致性**(10 µV 噪声、1e-6,统计对时域 `samples` 1e6 符号 3 % 内)、`sigma_sampling_s`。
- `test_spur_dominated_link_both_engines_agree` 改为在调噪声的那个相位上跑时域(重跑统计会重新居中,误码数掉到 23 个)。

### 指纹与示例
- `fp_9a` → `fp_9b`:3100 项中 1557 变,全部在上面六条里;逐配置的新旧值见 LOG。10 个示例全部重跑并接受;README 的示例行同步。
- 示例 03 / 06:调好噪声后两引擎都钉在调噪声的那个相位上(`rx.sampling_phase_ui`),不再让统计引擎在加大的噪声下重新居中(关着的眼会把采样点挪到脉冲最高处,BER 低 3×、误码只剩 12 个);
  示例 07 的表列最差 lane 而不是中间 lane(24 GT/s 中间 lane 过、lane 1 不过);示例 08 的布线结论句按结果生成。

---

## [0.11.1] — 2026-11-02 — 段 9a:第二次体检后的卫生轮(指纹逐位相同,一处并列规则除外)

### 修复
- **CI 在 main 上红了四次**(0.10.0 起):`tests/test_spec_sources.py` 用了 3.11+ 的 `tomllib`(3.10 两个作业失败)—— 改为文本匹配;
  示例 08 带状线模块五条 lane 结果完全相同,`LinkResult.worst` 按浮点末位挑 lane,本机 1、CI 2 —— 裕度按 1e-9 取整后再比、并列取编号小的
  (示例 08 该行的最差 lane 变为 0,期望输出重新接受)。
- README 的一致性证据数字过期:示例 03 行 1.23 / 1.22 / 0.87 → 1.18 / 0.96 / 0.88,示例 06 行 → 0.80 / 0.72 / 0.75 / 0.84 / 0.83,40 mm 的 0.739 / 150 → 0.738 / 150.4;
  `cairn/engines.md` 里程碑 2 的表同步;"pytest 约 2 分钟" → 5–6 分钟。
- 派生数登记:`examples/derived.yaml`(README 的"串扰费 22 mV / 0.018 UI"),`example_drift derived` 从此把关。
- 铁律 6 进 CI:`fingerprint` 作业在 **push** 上也比对(基线 = 分支上一个 head,同一 runner),差异无 `numbers-move`(PR 标签或 head 提交信息里的词)即红;
  base 路径不再写死;两个工作流加 `permissions: contents: read`。
- 过期文字:USAGE "GUI 这一轮不做"、`form.py` "No GUI ships"、USAGE 示例列表补 08 / 09、ROADMAP P3 编号与 Touchstone 行、docs/gui.md 参数表补
  `--port/--host/--no-autorun`、`--also` 帮助文本与未知任务名的友好报错、`cairn/gui.md` 日期。

### 体检记录
- 第二次体检(2026-11-02)全文在会话 scratchpad `health_check_2026-11-02.md`,结论进 ROADMAP:P1 新增"解析走线非因果"(段 9b 修)。

---

## [0.11.0] — 2026-10-13 … 10-14 — 段 8 G1:浏览器 GUI 骨架(指纹逐位相同)

### 新增
- **`d2d_link.report`**:`budget_rows` / `report` / `to_markdown` / `sensitivity*` 从 `tools/budget_report.py` 搬进包(CLI 只剩入口);数字不变。
- **`d2d_link.gui`**(`pip install d2d-link[gui]`,`d2d-link-gui config.yaml`):Dash ≥ 3 浅色页面,"报告即界面" —— 标题句里的封装 / 速率 / 长度 / lane 数 /
  串扰 / 布线是控件,改一个入队重跑;段落 Verdict(三格 + 逐 lane 眼宽条 + "时序还是幅度判定"一句)、Clock-path jitter(fs 与方差占比)、
  Lanes & repair(按裕度排序的表)、Crosstalk、Receiver;左栏场景(`configs/*.yaml`,带上次判定与耗时)与目录;右栏本页来源、队列(进程池 2 个 worker,
  可取消,ETA)、导出(Markdown 与 CLI 逐字同文、JSON、overrides YAML)、未核实输入(survey 条目 + cite);抽屉 "All fields" 由 `form.SECTIONS` 生成,
  带来源标签(yaml / default / model / survey / override),只写 overrides。
- 测试(+8,`tests/test_gui.py`,不开浏览器):铁律 1 的 AST import 守卫、worker 结果可 JSON 且与示例 00 同数、各段含报表数字、导出同文、
  state 的 override / 来源分类、队列缓存命中、app 建页与编辑、每个 bundled 配置可打开。CI 新作业 `gui`(只有它装 Dash)。
- 文档:`docs/USAGE.md` GUI 段、`cairn/gui.md`;ROADMAP P1 #2 改为实跑事实(x5 耦合没有单个 ±20 % 估计能翻转 FAIL,裕度 −0.118);
  x16 / x5 耗时改为空闲机器的 29 / 21 s。

### G2(同一版本内追加)
- **lane 平面图**(Lanes & repair 段):每个物理 lane 一格,眼按比例画成六边形(宽 = UI,高 = 对 ±主光标的比例)叠目标 mask(虚线框),
  死 bump 斜纹、闲置半区 / 备用灰、最差 lane 琥珀、不过的红;点一格(或表里一行)选中,它的攻击 lane 虚线圈出,右栏 **Inspector** 显示该 lane 的
  眼对目标子弹条、浴盆、采样相位 / 抖动 / 噪声 / 光标数 / 串扰 / skew 残余 / 训练偏移。worker 结果里新增每 lane 的攻击 lane 物理编号(`engine.lanes.aggressors_of`)。
- **What flips the verdict 段**:敏感性是一个任务(`sensitivity` kind,1 + 2 × 旋钮次运行,`report.sensitivity(progress=)` 回报进度),按钮入队;
  完成后一句结论("没有单个 ±20 % 估计能翻转" / "N 个估计翻转")+ tornado(各旋钮低 / 高侧的最差 lane 裕度,名义线与判定边界)+ 表;
  导出的 Markdown 自动带上 `sensitivity_markdown`。
- **Eye & bathtub per lane 段**:所有 lane 的浴盆叠在一条轴上(log10 BER 截到 −60,目标虚线、采样相位菱形),选中 lane 在前。
- **Data rate × package 卡**(右栏):`rate_sweep` 任务 —— 当前配置在规范表的每个速率档各跑一次,格子 = 最小眼高 / 最小眼宽,红绿 = 过不过,
  一句"first failing rate"。
- 队列显示任务进度(n / total runs)与按进度估的剩余时间;`d2d-link-gui --also sensitivity,rate_sweep` 启动时就把它们排进队列。
- 测试 +3(敏感性与速率扫描任务内联、G2 各段与图、lane 选择与额外任务)。

### G3(同一版本内追加)
- **Sweeps 附录 A–C**:`sweep` 任务 kind(`params.axis`:`track_bw` / `local_pll_fn` / `reach`,每点一次 `run_link` + 闭式时钟残余),各一个按钮入队;
  完成后一句结论(残余减半的带宽 / 最宽眼的 f_n / 最后通过的长度)+ 眼宽与残余双轴曲线 + 表。x1 的 tracker 带宽扫描 12 点 18 s,
  眼宽 0.774(无跟踪器)→ 0.913 UI(10 GHz),与示例 01 同数。
- **Compare with**(左栏下拉):选另一个场景,它的运行自动入队,落地后在 Verdict 下方并排判定 / 损耗 / 时钟残余 / 最差 lane 眼与裕度,逐 lane 眼宽条左右对照。
- **磁盘缓存**:`JobManager(cache_dir)` 把每个结果按 (kind, 配置哈希, 参数) 存 JSON,默认 `~/.cache/d2d_link/gui`(`--cache DIR` / `--no-cache`),
  重启后同一配置秒开。`--compare PATH` 启动参数。
- 文档:`docs/gui.md`(启动参数、页面各段、耗时表、不做的);README 段 8;`cairn/gui.md` G3。测试 +2。

---

## [0.10.0] — 2026-10-13 — 性能轮(数字会变的那次;变化全部 ≤ 3.5e-7 UI / 2.4e-8 V)

### 变更
- **眼边求根贴细网格**:先在抖动核的细网格上二分到一格(这些相位的 ISI 模型浴盆已经建过,只花尾的钱),再做一步离网格的 Illinois,
  末了在几个 1e-3 UI 宽的括号里按 log 线性取边。x1 的边与 24 步求根同到 1e-7 UI;每 lane 省 ~1.8 s。无抖动(网格步 > base/4)时仍跑到 1e-5 UI 的完整 Illinois:一格里可能藏着几百个数量级的悬崖(段 3 的 1.026 UI 伪影)。
- **`half_eye` 用 Illinois 代替 60 步二分**:在 g(h) = √(−log₁₀ tail) 上做安全的 regula falsi(高斯尾在 log 域对 h 是二次的,g 近似线性),
  约 6 次求值到 0.1 µV;旧二分 60 次。
- **亚 bin 光标合成一个 3 抽头核**再与分布卷一次(核可交换;x1 的 130 个光标约 45 % 走这条路,`_shift_add` 调用 59.9k → 33.3k)。
- 用时:x1 每 lane 4.2 → 2.5 s;x5 耦合模块 80 → 40 s;x16 模块 64 s;示例 05 / 07 约 15 min → 231 / 313 s。
- **`data/` 进包**:规范表、模型预设与随库的时钟剖面搬到 `src/d2d_link/data/`,`pyproject` 声明为 package data;配置里仍写 `data/clock_profiles/x.yaml`,
  `resolve_data_file` 先找包内、再找仓库根、再找工作目录(`spec.SURVEY_FILE` / `PRESETS_FILE` 指向包内)。`pip install` 后不再依赖仓库路径(段 8 GUI 的前置)。
  文档里的 `grep` 命令路径同步;新测试 `test_data_ships_inside_the_package`。
- 指纹(`fp_p7` → `fp_perf`):872 / 3074 项变,全部由两处求根解释 —— eye_width ≤ 3.5e-7 UI、eye_height ≤ 2.4e-8 V、phase ≤ 1.6e-7 UI、
  log10 BER ≤ 1e-4(对 −296);光标 / 主光标 / σ_ISI 的 1e-9 级变化是在新相位上读出来的;时域的 4 个 BER、样本与眼迹随相位变。
  任何打印到 0.1 mV / 0.001 UI 的数字都不动;示例期望输出只变一行(示例 08 带状线的最差 lane 0 → 1:两 lane 裕度并列到 1e-7 UI)。

### 没做(记入 ROADMAP / `cairn/engines.md`)
- 尾按模型批量算(各模型网格不同,需按段 logsumexp;约 0.5 s/lane);攻击 lane 的 PRBS 播种**不改**:按物理编号是对的(见 engines.md)。

---

## [0.9.0] — 2026-10-13 — 段 7:收端机制(默认值保持旧行为;现有配置指纹逐位相同)

### 新增
- **收端前端带宽** `rx.bw_hz`:数据路径上的一阶极点(`channel/model.py::rx_response`),与发端极点、CTLE 一起进主脉冲与 FEXT / NEXT 脉冲;
  留空 = 平坦(段 1–6 的理想化)。时钟树带宽(`clocking.tree_bw_hz`)滤时钟相位,这是数据边沿的对应项 —— 关掉 ROADMAP 旧 P2 #2。
  x1 25 mm:前端 48 / 32 / 24 GHz 眼 215.6 → 208.8 / 196.5 / 179.9 mV(噪声在采样点)。
- **噪声在哪里进入** `rx.noise_at: sampler | input`:`input` 时 `noise_rms_v` 是前端输入处白噪声在奈奎斯特带内的 RMS(理想积分接收机的噪声带宽),
  采样器看到 σ · √(∫₀^∞ |H_fe H_ctle|² df / f_N)(`noise_shaping_gain`,tan 换元一次 quad,一阶极点闭式复现到 3e-10);要求有限 `bw_hz`。
  时域波形路径真的把网格白噪声滤过前端 × CTLE(块间保留滤波器状态)再按分数采样瞬间读出(`_NoiseFeed`),与积分值 1.5 % 内(网格带限 3 % 方差);
  `samples` 模式用边缘 σ。**CTLE 不再白拿增益**:35 mm / 32 GHz 前端,噪声在采样点时 6 dB 最好(222.7 mV),在输入时 4 dB 最好(179.0 mV,6 dB 168.8);
  行为级 CTLE 两极点一零点本身是低通,≤ 2 dB 峭度比不开还省噪声。`StatResult.extras` 新增 `noise_gain`、`sigma_noise_input_v`;
  `TimeResult.extras` 新增 `sigma_noise_v`、`noise_filtered`。
- **训练 BER** `rx.training_ber`:链路训练在眼监视器能看见的 BER 上找眼边并居中,浴盆不对称时中点偏离目标 BER 的中点,lane 按围绕实际采样点的
  对称开口付眼宽(`extras["training_centre_ui"]`、`extras["centre_offset_ui"]`);留空 = 目标 BER(旧行为)。x1 1e-3:偏 −0.00075 UI,眼宽 0.7741 → 0.7726;
  无抖动 8 mV 噪声的 25 mm 线偏 −0.034 UI(0.714 → 0.646);x5 耦合中间 lane 偏 −0.0235 UI、眼宽 0.691 → 0.644(有串扰的 lane 付 0.03–0.05 UI)。
- `budget_report.py`:报告新增 "Receiver" 段(前端、噪声口径与增益、CTLE、训练偏移);配置写了 `rx.bw_hz` 时 `--sensitivity` 把它列为 config 旋钮。
  表单字段同步;`docs/USAGE.md` 的 `rx` 行;新专题 `cairn/receiver.md`;示例 09 `09_receiver_front_end.py`。
- 测试(+7,`tests/test_receiver.py`):一阶极点闭式、默认不变与平坦前端、配置约束、CTLE 峭度的噪声单调性、前端极点让脉冲变慢与输入噪声缩眼、
  时域滤噪声落在积分上(采到的 RMS 3 % 内、BER 对 Q 函数 2× 内、samples 模式边缘 σ)、训练偏移按对称开口扣眼宽。

### 修复
- 段 7 自己的:第一版把训练中点当 `center`,"偏离中心"的判断永远为假、眼宽没扣;现在与目标中点比(配置固定的采样相位仍是它自己的中心)。

### 没做(记入 ROADMAP / `cairn/receiver.md`)
- bundled 配置仍是平坦前端 + 采样点噪声:前端带宽没有规范数字,是设计的主张,等用户给再改基线;随机 DCD 有意不加(与白抖动不可区分);
  训练的 deskew 分辩率与眼监视器样本数的统计误差。

---

## [0.8.0] — 2026-10-13 — 段 6:串扰物理(无实测数据版;现有配置指纹逐位相同)

### 新增
- **`channel.routing: microstrip | stripline`**:带状线均匀介质 ε_eff = ε_r,一阶 FEXT 为 0(估计给 −300 dB 下限),同几何的线更慢(L、C 由 ε_r 推出)。
  **32 GT/s 标准封装不过是微带假设的产物**:同几何布成带状线就过(示例 08)。
- **近端串扰** `channel.xtalk_next: none | coupled | fixed` + `next_db`,`lanes.reverse_adjacent` / `reverse_phase_ui`:模块边缘 lane 旁的
  反向 lane 在本 lane 的收端 die 上发射,后向波 K_b [p(t) − p(t − 2τ_c)],K_b = κ/4(coupled)或配置值(fixed),不经有损线;
  `next_response()`、`LinkConfig.next_ratio()` / `coupled_delay_s()`;引擎接口用 `"next"` 键(`xtalk_pulses["next"]`,攻击 lane 元组 `("next", 相位, 种子)`)。
  标准 25 mm:K_b −36.0 dB,两瓣 8.5 UI 相距;−14 dB 固定 NEXT 上两引擎 1e-4 处 2× 内。
- **单端多端口 Touchstone**(`channel.touchstone_mode: single_ended`、`touchstone_lanes`、`xtalk: touchstone`;`channel/touchstone_se.py`,
  vendored 读法不动):2N 端口(1..N 近端、N+1..2N 远端),每个 2 端口子网络用 vendored 的内插与端接;文件自己的耦合项成为串扰脉冲
  (`ChannelModel.xtalk_H`),距离 d 取两侧较强的那条。合成无损 3 lane 文件:|H| = 1,耦合 0.0707 对 0.0707,lane 间互易。
- `ForwardedClock.tree_wrap_fraction`(树延时在块内循环卷绕的比例:30 ps / 2^18 UI = 3.7e-6);`describe()` 增加 `routing`、`coupled_delay_ps`、
  `next_mode` / `next_db`;表单字段同步。示例 08 `08_crosstalk_physics.py`:x5 中间 lane 微带 143.1 mV / 0.691 UI(FAIL)对带状线 211.8 mV / 0.761 UI(PASS);
  边缘 lane 加 NEXT 眼宽 0.748 → 0.737;解析线合成的 6 端口文件与解析路径眼高差 0.12 mV。
- 测试(+6):带状线无一阶 FEXT 且线更慢、NEXT 脉冲(DC 抵消、1/(4τ_c) 处 2K_b、两瓣间距、只有 `reverse_adjacent` 的 lane 受害)、
  强 NEXT 两引擎 2×、单端 6 端口读回(|H|、耦合幅度、互易、配置约束)、树卷绕数、配置校验。

### 修复
- **Touchstone 信道的直流缺口**(M1 起就有,无示例使用、测试只查带内 |H|):vendored 内插把文件频带之外的传输项填 0,而本库的网格从 DC 开始,
  于是任何 Touchstone 信道的 H(0) = 0 —— 脉冲带一条长负尾,合成的 25 mm 文件把 182 mV 的眼读成 60 mV。`channel/model.py::fill_dc` 用带内最低
  两点按 √f 外推直流幅度(导体损耗的低频规律),上限 1、不低于最低点;两种读法都经过它。测试:文件路径与解析路径的光标和、主光标 2e-3 内一致。

### 没做(记入 ROADMAP / `cairn/crosstalk.md`)
- 真实封装耦合线 S 参数(用户确认拿不到);NEXT 反向 lane 的随机相位平均;文件里左右邻 lane 的区分;带状线二阶 FEXT;
  树带宽对数据边沿的等效滤波归段 7(收端前端带宽)。

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
