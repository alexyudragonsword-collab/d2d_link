# d2d_link 协作规则

> 本项目使用 Project Cairn:`AGENTS.md` 是规则与导航入口,`cairn/` 是项目知识/状态层。同目录 `CLAUDE.md` 只有一行 `@AGENTS.md`,使 Claude Code 读到同一份规则;Codex 直接读本文件。

## 项目一句话

die-to-die / UCIe 短距并行链路的行为级仿真框架:前向时钟、多 lane、几乎不均衡、无 FEC 下的极低 BER 与 lane repair。它是 Halo_Serdes 的姊妹库而不是扩展 —— Halo 是长距串行 SerDes(均衡、CDR、FEC),这里的核心机制是前向时钟对发端相噪的跟踪。

## Init 配置

- 毕业 provider:暂缓对接(首次毕业时再接知识库)
- 知识库索引 / 毕业目标:尚未配置

## 进入项目后的阅读顺序

1. 先读本文件(AGENTS.md)。
2. 读根目录 `ROADMAP.md`:只记没做的,每条附证据(复现方式与数字)。
3. 读 `cairn/LOG.md` 最新几条(新条目在顶部):每轮的数字原值与被推翻的判断。
4. 按任务需要读 `cairn/` 下相关知识专题文档(`cairn/forwarded-clock.md`、`cairn/engines.md`、`cairn/crosstalk.md`、`cairn/receiver.md`、`cairn/gui.md`、`cairn/spec-sources.md`)。

## 文档职责

| 文件 | 角色 | 维护方式 |
|---|---|---|
| `AGENTS.md`(根) | 规则与导航 | 很少变,≤ 65 行 |
| `CLAUDE.md`(根) | 单行 `@AGENTS.md` 存根 | 写一次,不再改动 |
| `ROADMAP.md`(根) | 待办与优先级 | 只写没做的;完成即删除并在 LOG 记一笔;发现的问题带复现方式和数字 |
| `CHANGELOG.md`(根) | 已交付的演进 | 按里程碑追加 |
| `cairn/LOG.md` | 时间序日志 | 新条目加在顶部,每条 ≤ 20 行:数字原值、被推翻的判断、下一步 |
| `cairn/<topic>.md` | 知识专题文档(当前真相) | 就地更新;坑放正文小节并用 `contains` 标注 |
| `cairn/Reference/` | 外部原始输入(规范原文贴进来放这里) | 按需创建,只追加 |

> 工程资产(配置、规范数字表、期望输出)留在代码树里;`cairn/` 只放关于它们的知识。面向使用者的 `README.md`、`docs/` 与面向协作者的 `cairn/` 读者不同,不要互相搬运。

## 项目铁律(每条都有测试守着;论证见 `cairn/architecture-invariants.md`)

1. **配置是唯一真值** —— 封装类型、速率、lane 数、时钟方案全部在一个 frozen `LinkConfig` 里,示例和 GUI 只读它(`tests/test_invariants.py::test_law1_*`)。
2. **前向时钟的抖动跟踪是核心机制** —— 数据与前向时钟共享发端 PLL 的相噪,收端看到的是两者之差经跟踪带宽滤波后的残余。禁止任何"把前向时钟当独立时钟"的捷径;相关 = 1 时残余抖动必须为零(`tests/test_forwarded_clock.py`)。
3. **统计引擎是主引擎** —— BER 1e-27 不可能时域仿真出来;时域引擎只在可测 BER 上做一致性检查,LTI + 高斯噪声下两者必须在 2× 内:~1e-4 与 1e-6 在套件(`tests/test_engines.py`),3e-8(1e9 符号)每周(`tests/test_engines_deep.py`,`pytest -m slow`),1e-8 本身要 2.5e9 符号约 5 小时、手动触发。
4. **多 lane 从第一天就在** —— lane 间 skew、公共时钟、lane repair 是配置项;单 lane 只是 `lanes.count = 1`(`tests/test_lanes.py`)。
5. **规范数字只用原文** —— 拿不到原文的数字全部标 `source: survey` 并注明出处,不编;`grep "source: survey"` 一次列全(`tests/test_spec_sources.py`)。原文贴进来后再改成 `source: spec`。规范不管的模型估计数(走线损耗、叠层、行为级串扰)标 `source: model`,`grep "source: model"` 一次列全,`budget_report.py --sensitivity` 看哪些估计决定结论。
6. **数值指纹** —— 重构必须用 `tools/fingerprint.py` 证明逐位不变(`tests/test_fingerprint.py`)。

开工前先读 `cairn/engineering-pitfalls.md`。

## 冲突仲裁

- 优先级:**知识专题文档 > LOG 历史**;结论以 `cairn/` 专题文档的最新记录为准。规则层面的冲突由本文件裁定。

## 文档协作规则

- 动手前先判断用户要的是"讨论/建议"还是"直接改文档";说"先看看/先评估"时先给分析。
- 修正过去的判断时追加更正说明,不要静默覆盖。未经确认的判断不要写成既定事实。规范条文原文没有就写"未核实"。

## 知识沉淀规则

- 每次实质性推进后,在 `cairn/LOG.md` 顶部加一条(摘要+指针);结论沉淀进 `cairn/` 专题文档。
- **完成回复闸门**:在任何完成类声明之前,先执行 Project Cairn `references/maintenance.md` 的检查点,只更新其触发矩阵要求的记录并核验,再回复。明确的只读要求禁止 Cairn 写入。
- 每个里程碑结束:CHANGELOG 一条、LOG 一条、ROADMAP 删掉做完的条目并加上过程中发现的问题。
