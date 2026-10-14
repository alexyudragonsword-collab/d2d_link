# 待办与路线图 / Roadmap

已完成的演进见 [`CHANGELOG.md`](CHANGELOG.md)。这份文件只记**尚未做的**;每条附证据(在哪测到的、数字、复现方式)。
优先级按「是否影响结论的可信度」排序。

> 约定:`[P1]` 会让某类结论不可信;`[P2]` 影响能力上限;`[P3]` 可选扩展;`[边界]` 有意不做,仅记录范围。

---

## P1 — 结论的可信度

1. **规范数字全部未核实**(铁律 5)。15 条 `source: survey`(`grep -c "source: survey" src/d2d_link/data/spec/ucie_survey.yaml`),
   其中直接决定结论的两条是收端眼宽 0.75 UI 与眼高 40 mV:示例 02 的 reach(35 mm,0.5.0)由**眼宽**判定,40 mm 时眼高还有 150 mV、
   眼宽 0.739 UI;如果眼罩表的 0.75 UI 不是 32 GT/s 标准封装的值,reach 结论整个要重算。原文贴进 `cairn/Reference/` 后改
   `source: spec` 并重跑示例 02。

2. **串扰的耦合线估计是一阶猜测,却决定了 32 GT/s 标准封装的结论**。`channel/coupled.py`:κ = 1/(1 + (s/h)²)、速度差 (1 − ε_eff/ε_r)、
   线性长度增长;h = 30 µm 微带、ε_r 3.5 全是 `PACKAGE_STACKUP` 的模型值。给出 −18.6 dB(示例 07),模块因此在 32 GT/s 不过;
   示例 05 的 x16 / 20 mm 模块在 M2 的行为级 −30 dB 预设下能过(另一个模块)。封装的耦合线 S 参数拿不到(用户确认)。
   段 6 已给出带状线选项(同几何一阶 FEXT 为 0,模块因此能过 —— 结论是微带假设的产物)、反向 lane 的 NEXT 与单端多端口文件读法
   (`xtalk: touchstone`),见 `cairn/crosstalk.md`;真实文件到了用它对比 `coupled`,目标 6 dB 内。段 2 的敏感性报告:
   复现:`python tools/budget_report.py configs/standard_32g_x5_coupled.yaml --sensitivity`。段 8 G1 实跑的结果:**没有任何单个 ±20 % 的估计能翻转这个 FAIL**
   (名义裕度 −0.118;最接近 0 的是眼宽目标取 0.70 UI 的 −0.054、介质厚 24 µm 的 −0.061、bump 间距 138 µm 的 −0.071)。能翻转它的是布线假设(带状线,示例 08)。

## P2 — 一致性与能力

0. **性能**(性能轮 0.10.0 之后):统计引擎每 lane 2.5 s(x1)/ ~8 s(349 光标的串扰 lane),x5 耦合模块 21 s、x16 模块 29 s(空闲机器;并行三个任务时量到 40 / 64 s),示例 05 / 07 231 / 313 s;
   剩下的热点(x1 每 lane 2.5 s 里 `_shift_add` 0.65 s、`log10_tail` 0.6 s)要把尾按模型批量算,收益约 0.5 s/lane。
   时域波形路径每 1e6 符号约 6 s,1e-8 的 25 误码点要 2.5e9 符号 ≈ 5 h(手动触发);`samples` 模式在有损线上不更快(脉冲尾 130 UI 内都 > 1e-6 主光标)。
   分块合成的缝(`block_step_ratio` ≈ 2,x16 模块)未折算到 BER。

1. **先进封装的 RDL 线在低 GHz 是 RC 主导的,"Z0 = 50 Ω" 只是高频渐近值**(段 2 发现):预设 R_dc 2000 Ω/m + R_skin 给 2 GHz 处 R ≈ 3100 Ω/m,
   与 ωL ≈ 3200 Ω/m 同量级;终端按 50 Ω 匹配时低速档出现反射与幅度损失(示例 07 先进 2 mm 4 GT/s 主光标 178 mV,8 GT/s 起 187 mV)。
   需要决定:(a) 终端按实际 |Z0(f)| 匹配,或 (b) 用 RDL 的实测 / 场解 RLGC(拿不到),或 (c) 在 `--sensitivity` 里把 R_dc 列为低速档的决定参数。
   复现:`python tools/budget_report.py` 对 `advanced_32g_x64_spare.yaml` 把 `data_rate_gtps` 改 4,看 lane 表眼高;对比 `channel.rdc_ohm_m: 200`。

2. **bundled 配置的接收机仍是平坦前端、噪声在采样点**(段 7 给了字段,没有给基线数字):`rx.bw_hz` 没有规范值,是设计的主张。
   示例 09:x1 的眼高随前端 48 / 32 / 24 GHz 从 215.6 → 208.8 / 196.5 / 179.9 mV(噪声在采样点),噪声改到输入(同一 3 mV)则 137.9 / 150.5 / 148.7 mV;
   32 GT/s 标准封装的判定是否随之翻转没有查(x5 中间 lane 裕度 −0.059 UI,前端极点只会更差)。需要用户给接收机带宽与噪声口径,再改基线并重跑示例。
   复现:`python examples/09_receiver_front_end.py` 的第一张表;配置里写了 `rx.bw_hz` 后 `budget_report.py --sensitivity` 把它列为 config 旋钮。
3. **Touchstone 路径只测了合成的无损 4 端口**(`tests/test_channel.py`);没有真实封装 S 参数文件。接口留着,数据没有。

## P3 — 能力扩展

1. 串扰:NEXT 的反向 lane 相位是固定配置值(`lanes.reverse_phase_ui`),没有随机相位平均;回程模块的时钟与本模块无关的建模没有;
   单端 Touchstone 文件里距离 d 的左右两个邻 lane 取较强的一条(引擎按距离索引攻击 lane);带状线只做了一阶(FEXT = 0)。
2. 前向时钟的四分之一速率变体(`clocking.scheme` 目前只有 `forwarded_ddr`)。随机占空比误差有意不加(与白抖动不可区分,段 3 / 段 7 两次确认)。
3. 收端(段 7 之后还没有的):训练的 deskew 分辨率与眼监视器的样本数(`rx.training_ber` 只给了居中的 BER,没有给它的统计误差)、前端的非线性与失调、噪声在时域里的符号间相关对簇统计的影响(波形路径已带相关,`error_bursts` 没有按它解读)。
3. Android:段 8 的浏览器 GUI(`d2d_link.gui`,Dash)在手机上只差一个跑在服务器上的后端;本机 APK 要把 numpy / scipy 打进 Chaquopy,未排期。
   GUI 本身还没有的:多用户共享(缓存与 worker 没按用户隔离)、真实 bump map(平面图是一维物理编号)、深色主题(有意不做)。

## 边界(有意不做)

- 均衡器与 CDR 的深度(Halo_Serdes 的领域);本库只有一个可选的 1 级 CTLE 行为模型。
- 协议层:flit、CRC、retry 只留 `target.ber` 一个参数位(规范表另有 `raw_ber_with_retry`,未用)。
- 规范条文的转述:原文没有就写"未核实"。
