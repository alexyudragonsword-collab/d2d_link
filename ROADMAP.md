# 待办与路线图 / Roadmap

已完成的演进见 [`CHANGELOG.md`](CHANGELOG.md)。这份文件只记**尚未做的**;每条附证据(在哪测到的、数字、复现方式)。
优先级按「是否影响结论的可信度」排序。

> 约定:`[P1]` 会让某类结论不可信;`[P2]` 影响能力上限;`[P3]` 可选扩展;`[边界]` 有意不做,仅记录范围。

---

## P1 — 结论的可信度

1. **规范数字全部未核实**(铁律 5)。15 条 `source: survey`(`grep -c "source: survey" data/spec/ucie_survey.yaml`),
   其中直接决定结论的两条是收端眼宽 0.75 UI 与眼高 40 mV:示例 02 的 reach(35 mm,0.5.0)由**眼宽**判定,40 mm 时眼高还有 150 mV、
   眼宽 0.739 UI;如果眼罩表的 0.75 UI 不是 32 GT/s 标准封装的值,reach 结论整个要重算。原文贴进 `cairn/Reference/` 后改
   `source: spec` 并重跑示例 02。

2. **串扰的耦合线估计是一阶猜测,却决定了 32 GT/s 标准封装的结论**。`channel/coupled.py`:κ = 1/(1 + (s/h)²)、速度差 (1 − ε_eff/ε_r)、
   线性长度增长;h = 30 µm 微带、ε_r 3.5 全是 `PACKAGE_STACKUP` 的模型值。给出 −18.6 dB(示例 07),模块因此在 32 GT/s 不过;
   示例 05 的 x16 / 20 mm 模块在 M2 的行为级 −30 dB 预设下能过(另一个模块)。封装的耦合线 S 参数拿不到(用户确认),所以下一步是
   带状线选项与 NEXT 的合成模型(段 6)。段 2 已把预设带上 `source: model`(`data/spec/model_presets.yaml`)并给了敏感性报告:
   复现:`python tools/budget_report.py configs/standard_32g_x5_coupled.yaml --sensitivity`,看 "Sensitivity" 段里标 **yes** 的参数。

## P2 — 一致性与能力

0. **体检(2026-10-13)挂起的模型问题**,按已批准的分段方案处理(段 1、2、3 已做,见 CHANGELOG 0.4.0 / 0.5.0 / 0.6.0):
   段 4 —— 铁律 3 只在 ~1e-4 被测,1e-6 只在示例 03,1e-9 没跑过;分块合成的缝(`block_step_ratio` ≈ 2,x16 模块)未折算到 BER;
   统计引擎每 lane 4.6 s(x1;段 3 的眼边求根落在细网格外多 1.8 s)/ ~10 s(349 光标的串扰 lane),x64 模块约 12 min;
   `half_eye` 的 60 步二分、逐相位 `log_ndtr` 与求根相位的模型缓存未命中是热点。

1. **先进封装的 RDL 线在低 GHz 是 RC 主导的,"Z0 = 50 Ω" 只是高频渐近值**(段 2 发现):预设 R_dc 2000 Ω/m + R_skin 给 2 GHz 处 R ≈ 3100 Ω/m,
   与 ωL ≈ 3200 Ω/m 同量级;终端按 50 Ω 匹配时低速档出现反射与幅度损失(示例 07 先进 2 mm 4 GT/s 主光标 178 mV,8 GT/s 起 187 mV)。
   需要决定:(a) 终端按实际 |Z0(f)| 匹配,或 (b) 用 RDL 的实测 / 场解 RLGC(拿不到),或 (c) 在 `--sensitivity` 里把 R_dc 列为低速档的决定参数。
   复现:`python tools/budget_report.py` 对 `advanced_32g_x64_spare.yaml` 把 `data_rate_gtps` 改 4,看 lane 表眼高;对比 `channel.rdc_ohm_m: 200`。

2. **树带宽只滤时钟相位,没有等效地滤数据边沿**;树延时在闭式里是精确的 e^{−jωτ},在合成里是块内循环卷绕(块长 2^18 UI,
   τ ≤ 100 ps ≈ 3 UI,影响可忽略,但没有量)。
3. **Touchstone 路径只测了合成的无损 4 端口**(`tests/test_channel.py`);没有真实封装 S 参数文件。接口留着,数据没有。

## P3 — 能力扩展

1. 串扰只有 FEXT(行为级幅度或一阶耦合线估计,见 P1 #2),没有 NEXT、没有耦合线的真实频响与反射。
2. 占空比误差的随机部分、前向时钟的四分之一速率变体(`clocking.scheme` 目前只有 `forwarded_ddr`)。
3. 桌面 GUI 与 Android:`config/form.py::SECTIONS` 已按 Halo 的方式声明了全部字段;Halo 的 `config_bridge` / Dash 表单可以直接搬。

## 边界(有意不做)

- 均衡器与 CDR 的深度(Halo_Serdes 的领域);本库只有一个可选的 1 级 CTLE 行为模型。
- 协议层:flit、CRC、retry 只留 `target.ber` 一个参数位(规范表另有 `raw_ber_with_retry`,未用)。
- 规范条文的转述:原文没有就写"未核实"。
