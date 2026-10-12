# Project Cairn 日志

本文件按倒序记录实质性进展 —— 最新条目在本行正下方。每条保持简短(数字原值、被推翻的判断、下一步),
结论沉淀进 `cairn/<topic>.md`。

## 2026-10-12 · 里程碑 1:标准封装 32 GT/s 单 lane 前向时钟 DDR 的时序预算(ccr-a2094794-9qa40v)

- 数字(`configs/standard_32g_x1.yaml`,25 mm):信道 −2.95 dB @ 16 GHz;PLL 带内 186.2 fs,采样器残余 295.3 fs
  (树泄漏 59.4 / 数据路径 199.9 / 时钟路径 183.6 / 树 100.0);眼 209.8 mV / 0.772 UI @ 1e-27,目标 40 mV / 0.75 UI 全是 survey。
  reach 30 mm vs 综述 25 mm(1.20×),判定项是**眼宽**不是眼高(35 mm:0.747 UI,163 mV)。
  跟踪带宽曲线在白路径抖动下 100 MHz 以下几乎平(295.4 → 291.0 fs),半程 4.16 GHz;相关 = 1 残余恰 0,无跟踪 282.84 = √(2×200²)。
  统计 / 时域(示例 03):噪声主导 1e-6 处 1.23(24 误码 / 2e7)、抖动主导 1e-6 处 1.22(16 / 2e7)、混合 1e-5 处 0.87(17 / 2e6)。
- 被推翻的判断:(1) 抖动平滑用 Gauss–Hermite 21 节点 —— 抖动主导点时域 / 统计 2.19×,改均匀网格(≤ σ/4,±12σ)后 0.85×;
  (2) 采样相位取浴盆 argmin —— BER 恰为 0 的平坦区里 argmin 是第一个索引(−0.30 UI),时域在那里反而数到误码,改为眼开区间中点;
  (3) 脉冲峰值用 argmax —— 平顶脉冲取到左缘,眼宽只剩 0.52 UI,改为平顶中点;(4) 时域分块只带历史符号 —— 块尾 5–6 个符号采样点越界,
  误码全是满幅反号,补未来符号后 0 误码;(5) 示例 03 抖动主导点硬编码 2.2 ps 只到 9.4e-8、2e7 符号 0 误码,改为按目标 1e-6 二分求抖动。
  详见 `cairn/engineering-pitfalls.md`。
- 规范数字:16 条全部 `source: survey`,是公开综述的记忆与转述、未经核对;眼宽 0.75 UI 直接决定 reach 结论(ROADMAP P1 #1)。
- 验证:`pytest -q` 103 passed;`ruff check` 干净;vendor_check 6 文件(5 verbatim、1 adapted)无漂移;fingerprint 两次 record compare 逐位相同;
  四个示例全尺寸跑通并 `accept` 进 `examples/expected/`。
- 下一步(ROADMAP):规范原文到手后升级 `source: spec` 并重跑示例 02;加有色的路径抖动项让跟踪带宽曲线在 MHz 段有意义;跟踪器延迟与量化。
- 上下文:库新建;方法照搬 Halo_Serdes(双引擎、expected/drift、fingerprint)、pll_simulator(时钟剖面)、polar_tx(vendor 规矩)、Project Cairn。

## 2026-10-12 · Project Cairn 初始化

- 初始化 Project Cairn 结构:`AGENTS.md`(六条铁律)、`CLAUDE.md`、`.cairn/config.yaml`(`git_policy: track`、`language: zh`、
  provider 暂缓对接)、本文件、根目录 `ROADMAP.md` / `CHANGELOG.md`。
- 历史迁移模式:`start_fresh`(新库)。
