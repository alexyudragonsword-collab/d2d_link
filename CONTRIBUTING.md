# 参与贡献

这个库的产品是**结论**:这条 D2D 链路在这个封装、速率、lane 数、时钟方案下够不够 1e-27。所以对改动的要求是可证明:
要么证明没让任何数悄悄变(`tools/fingerprint.py`),要么说清楚哪些数变了、为什么(CHANGELOG + `examples/expected/`)。

## 先读

1. `AGENTS.md`:六条铁律。2. `cairn/architecture-invariants.md`:每条靠什么执行。3. `cairn/engineering-pitfalls.md`。4. `ROADMAP.md`。

## 推送前

```bash
ruff check src/ tests/ examples/ tools/
pytest -q                                   # 约 2 分钟
python tools/run_examples.py --smoke
```

| 改了什么 | 再做什么 |
|---|---|
| 引擎 / 时钟 / 信道 / 配置 —— 任何本不该改数的改动 | 基线上 `python tools/fingerprint.py record before.json`,改完 `record after.json`,`compare`;重构必须逐位相同 |
| 可能改示例输出的改动 | 全尺寸 `python tools/run_examples.py --jobs 2 --save new/`,`python tools/example_drift.py compare new/`,改文档后 `accept new/` |
| `src/d2d_link/vendor/` | 不要原地改;从上游重新拷贝并更新 header 的完整 SHA,跑 `tools/vendor_check.py --strict --fail-on-skip --siblings ...` |
| 新配置字段 | schema 加字段 + `__post_init__` 校验 + `config/form.py::SECTIONS` 加一行(测试要求双向一致) |
| 规范数字 | 只改 `data/spec/ucie_survey.yaml`;没有原文就 `source: survey` + 出处 + "未核实" |

## 约定

- 代码注释、docstring、图表文字用英文;`README.md`、`docs/`、`CHANGELOG.md`、`ROADMAP.md`、`cairn/` 用中文。
- 注释写为什么,不写是什么。
- 新算法配闭式单测(解析 BER、退化情形、恒等式),涉及两个引擎的在 LTI + 高斯下要在 2× 内。
