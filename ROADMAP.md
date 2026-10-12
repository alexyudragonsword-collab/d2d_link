# 待办与路线图 / Roadmap

已完成的演进见 [`CHANGELOG.md`](CHANGELOG.md)。这份文件只记**尚未做的**;每条附证据(在哪测到的、数字、复现方式)。
优先级按「是否影响结论的可信度」排序。

> 约定:`[P1]` 会让某类结论不可信;`[P2]` 影响能力上限;`[P3]` 可选扩展;`[边界]` 有意不做,仅记录范围。

---

## P1 — 结论的可信度

1. **规范数字全部未核实**(铁律 5)。16 条 `source: survey`(`grep "source: survey" data/spec/ucie_survey.yaml`),
   其中直接决定结论的两条是收端眼宽 0.75 UI 与眼高 40 mV:示例 02 的 reach(30 mm)由**眼宽**判定,35 mm 时眼高还有 163 mV、
   眼宽 0.747 UI;如果眼罩表的 0.75 UI 不是 32 GT/s 标准封装的值,reach 结论整个要重算。原文贴进 `cairn/Reference/` 后改
   `source: spec` 并重跑示例 02。

## P2 — 一致性与能力

3. **树带宽只滤时钟相位,没有等效地滤数据边沿**;树延时在闭式里是精确的 e^{−jωτ},在合成里是块内循环卷绕(块长 2^18 UI,
   τ ≤ 100 ps ≈ 3 UI,影响可忽略,但没有量)。
4. **ρ < 1 时合成 RMS 对闭式散布 8%**(ρ = 0:285 vs 263 fs,块长 2^18)。1/f² 剖面最低几个 bin 的单次 χ²(2) 抽样所致;
   要么多块平均,要么在测试里用更长的块。目前测试对 ρ < 1 不做严格断言。
5. **Touchstone 路径只测了合成的无损 4 端口**(`tests/test_channel.py`);没有真实封装 S 参数文件。接口留着,数据没有。

## P3 — 能力扩展

6. 串扰只有 FEXT 的行为级耦合(k·(jf/fn)/(1 + jf/fn)·H,幅度按封装预设 −30 / −24 dB @ Nyquist,是**模型估计**不是规范数字),
   没有 NEXT、没有耦合线的真实频响;耦合幅度的来源待一个实测或场求解的耦合线模型(`PACKAGE_XTALK_DB`)。
7. 占空比误差的随机部分、前向时钟的四分之一速率变体(`clocking.scheme` 目前只有 `forwarded_ddr`)。
8. 桌面 GUI 与 Android:`config/form.py::SECTIONS` 已按 Halo 的方式声明了全部字段;Halo 的 `config_bridge` / Dash 表单可以直接搬。

## 边界(有意不做)

- 均衡器与 CDR 的深度(Halo_Serdes 的领域);本库只有一个可选的 1 级 CTLE 行为模型。
- 协议层:flit、CRC、retry 只留 `target.ber` 一个参数位(规范表另有 `raw_ber_with_retry`,未用)。
- 规范条文的转述:原文没有就写"未核实"。
