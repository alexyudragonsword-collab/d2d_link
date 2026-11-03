# 待办与路线图 / Roadmap

已完成的演进见 [`CHANGELOG.md`](CHANGELOG.md)。这份文件只记**尚未做的**;每条附证据(在哪测到的、数字、复现方式)。
优先级按「是否影响结论的可信度」排序。

> 约定:`[P1]` 会让某类结论不可信;`[P2]` 影响能力上限;`[P3]` 可选扩展;`[边界]` 有意不做,仅记录范围。

---

## P1 — 结论的可信度

1. **规范数字全部未核实**(铁律 5)。15 条 `source: survey`(`grep -c "source: survey" src/d2d_link/data/spec/ucie_survey.yaml`),
   其中直接决定结论的两条是收端眼宽 0.75 UI 与眼高 40 mV:示例 02 的 reach(25 mm,0.12.0;因果走线之前 35 mm)由**眼宽**判定,30 mm 时眼高还有 147.3 mV、
   眼宽 0.747 UI;如果眼罩表的 0.75 UI 不是 32 GT/s 标准封装的值,reach 结论整个要重算。原文贴进 `cairn/Reference/` 后改
   `source: spec` 并重跑示例 02。

2. **串扰的耦合线估计是一阶猜测,却决定了 32 GT/s 标准封装的结论**。`channel/coupled.py`:κ = 1/(1 + (s/h)²)、速度差 (1 − ε_eff/ε_r)、
   线性长度增长;h = 30 µm 微带、ε_r 3.5 全是 `PACKAGE_STACKUP` 的模型值。给出 −18.6 dB(示例 07),模块因此在 32 GT/s 不过;
   示例 05 的 x16 / 20 mm 模块在 M2 的行为级 −30 dB 预设下 0.11 时能过、0.12 起不过(另一个模块)。封装的耦合线 S 参数拿不到(用户确认)。
   段 6 已给出带状线选项(同几何一阶 FEXT 为 0;0.11 的非因果线上模块因此能过,0.12.0 因果化后带状线也差 0.002 UI 不过 —— 示例 08)、反向 lane 的 NEXT 与单端多端口文件读法
   (`xtalk: touchstone`),见 `cairn/crosstalk.md`;真实文件到了用它对比 `coupled`,目标 6 dB 内。段 2 的敏感性报告:
   复现:`python tools/budget_report.py configs/standard_32g_x5_coupled.yaml --sensitivity`。段 8 G1 实跑的结果:**没有任何单个 ±20 % 的估计能翻转这个 FAIL**
   (0.12.2 重跑:名义裕度 −0.161;最接近 0 的是介质厚 24 µm 的 −0.095、眼宽目标 0.70 UI 的 −0.101、bump 间距 138 µm 的 −0.107;0.11 时 −0.118 与 −0.054 / −0.061 / −0.071)。
   0.11 时布线假设(带状线,示例 08)能翻转它;0.12.0 起带状线也不过(0.748 UI),**32 GT/s 标准封装 25 mm 在本库的所有模型变体下都不过**,x16 / 20 mm 模块(−30 dB 预设)也从 PASS 变 FAIL(示例 05)。

3. **第三次体检(2026-11-03)挂出的三条会翻转 bundled 判定的建模选择**,全文在会话 scratchpad `health_check_2026-11-03.md`:
   (a) 发端 PLL 相噪在剖面最后频点(5.12 GHz)以上置零,共模泄漏的高通恰在被丢的 5–16 GHz 最大 —— 同方差摊到 fs/2 时 x1 眼宽 0.7614 → 0.7484 UI(FAIL),底噪平延 0.7163;
   (b) 有跟踪器时 `lanes.deskew_step_ps` 被忽略、`pi_step_ui` 默认 0 —— x16 repair / x64 spare 声明 1/16 UI deskew 却按理想 PI 算,按 1/16 UI 量化 0.7735 / 0.7923 → 0.7171 / 0.7357(都 FAIL);
   (c) 介质损耗常数 tanδ 无 KK 色散(与 9b 皮肤效应同类)—— Djordjevic–Sarkar 下 x1 204.85 mV / 0.7532 UI。另:行为级 FEXT 形状 √2·u/(1+u) 与耦合线一阶 j2πfτ 不符,
   x5 中间 lane 眼高差 60 mV、x16 最差 lane 换人。(a)(b) 需要用户定口径。复现:scratchpad `audit3_code/p05b_profile_white_spread.py`、`p07_deskew_ignored.py`、`p09_dielectric_causality.py`、`p04_fext_shape.py`。

## P2 — 一致性与能力

0. **性能**(性能轮 III,0.12.5 之后):统计引擎每 lane 1.0 s(x1),x5 耦合模块 ~14 s、x16 模块 ~18 s(空闲机器;0.11 的 128 UI 窗是 21 / 29 s),示例 05 / 07 见 LOG。
   剩下的热点(cProfile x16 23.8 s):`_shift_add` 6.3 s(每模型 45 次,Python 开销界)、块核相卷 3.6 s、`log10_tail` 4.1 s、`eye_edge` 5.3 s;numpy 层面到头,再快要 C 扩展 / numba,不做。
   时域波形路径每 1e6 符号约 6 s,1e-8 的 25 误码点要 2.5e9 符号 ≈ 5 h(手动触发);`samples` 模式在有损线上不更快(脉冲尾 130 UI 内都 > 1e-6 主光标)。
   分块合成的缝(`block_step_ratio` ≈ 1.4–2,x16 模块)未折算到 BER。


2. **bundled 配置的接收机仍是平坦前端、噪声在采样点**(段 7 给了字段,没有给基线数字):`rx.bw_hz` 没有规范值,是设计的主张。
   示例 09(0.12.0):x1 的眼高随前端 48 / 32 / 24 GHz 从 209.7 → 204.1 / 192.9 / 177.9 mV(噪声在采样点),噪声改到输入(同一 3 mV)则 135.5 / 148.8 / 148.2 mV;
   32 GT/s 标准封装的判定是否随之翻转没有查(x5 最差 lane 裕度 −0.121 UI,前端极点只会更差)。需要用户给接收机带宽与噪声口径,再改基线并重跑示例。
   复现:`python examples/09_receiver_front_end.py` 的第一张表;配置里写了 `rx.bw_hz` 后 `budget_report.py --sensitivity` 把它列为 config 旋钮。
3. **Touchstone 路径只测过合成文件**(`tests/test_channel.py`:无损 4 端口、有损 + 直流补齐、单端 6 端口、有损 50 GHz 截断 + 直通与耦合项的带外延拓);没有真实封装 S 参数文件。接口留着,数据没有。
   延拓是外推(直通按最后十倍频的斜率,耦合沿直通的衰减):合成文件上剩 0.005 UI 的直通延拓误差;真实文件的带外行为未知,文件带宽低于 4 × Nyquist 时把这一项列进该链路的不确定度。

## P3 — 能力扩展

1. 串扰:NEXT 的反向 lane 相位是固定配置值(`lanes.reverse_phase_ui`),没有随机相位平均;回程模块的时钟与本模块无关的建模没有;
   单端 Touchstone 文件里距离 d 的左右两个邻 lane 取较强的一条(引擎按距离索引攻击 lane);带状线只做了一阶(FEXT = 0)。
2. 前向时钟的四分之一速率变体(`clocking.scheme` 目前只有 `forwarded_ddr`)。随机占空比误差有意不加(与白抖动不可区分,段 3 / 段 7 两次确认)。
3. 收端(段 7 之后还没有的):训练的 deskew 分辨率与眼监视器的样本数(`rx.training_ber` 只给了居中的 BER,没有给它的统计误差)、前端的非线性与失调、噪声在时域里的符号间相关对簇统计的影响(波形路径已带相关,`error_bursts` 没有按它解读)。
5. **第三次体检的中低项**(工程,不动数):GUI 杀 worker 后提交的任务永远 queued(去重让同配置再也跑不了)、坏 yaml 让 Compare / 场景栏抛错、速率编辑先写 osr 再校验且 osr 依赖编辑历史、
   This page 卡运行中显示 not run、无活 lane 时 `worst` 抛错;wheel 缺 `gui/assets/keys.js`;派生数检查不进测试且不认 UI / mV / fs;第二邻 −12 dB 无 `source: model`;
   Tx DCD 无本地 PLL 时当作完全抵消;光标窗少读 0.6 % 直流;PI 量化箱方差 +11 %;NEXT K_b 系数;dB 旋钮 ±20 %。
4. Android:段 8 的浏览器 GUI(`d2d_link.gui`,Dash)在手机上只差一个跑在服务器上的后端;本机 APK 要把 numpy / scipy 打进 Chaquopy,未排期。
   GUI 本身还没有的:多用户共享(缓存与 worker 没按用户隔离)、真实 bump map(平面图是一维物理编号)、深色主题(有意不做)。


## 边界(有意不做)

- 先进封装 RDL 线的低频终端口径:段 12 量过,H(0) = 0.9615、|Z0(2 GHz)| ≈ 59 Ω 的反射在 2 mm 上可忽略,终端按 50 Ω 不改;R_dc 在敏感性报告里(段 2 的"RC 主导"归因已撤回,见 CHANGELOG 0.12.4)。

- 均衡器与 CDR 的深度(Halo_Serdes 的领域);本库只有一个可选的 1 级 CTLE 行为模型。
- 协议层:flit、CRC、retry 只留 `target.ber` 一个参数位(规范表另有 `raw_ber_with_retry`,未用)。
- 规范条文的转述:原文没有就写"未核实"。
