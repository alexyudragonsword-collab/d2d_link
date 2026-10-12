# 用法

```bash
pip install -e ".[touchstone,plot,test]"
python examples/00_single_lane_eye.py        # 单 lane:预算、眼、两引擎
python examples/01_tracking_bandwidth_sweep.py
python examples/02_reach_sweep.py
python examples/03_stat_vs_time.py           # 1e-6 处的一致性比,约 3–5 分钟
pytest -q
```

## 三行

```python
from d2d_link.config import load_config
from d2d_link.engine import run_link

res = run_link(load_config("configs/standard_32g_x1.yaml"))
print(res.summary())      # 每 lane:BER、眼高/眼宽对目标(带 source)、残余抖动
```

## 配置就是一切(铁律 1)

`configs/*.yaml` 镜像 `d2d_link.config.schema.LinkConfig` 的嵌套结构;未知键报错。扫描用 `dataclasses.replace`
或 `apply_overrides(cfg, {"channel.length_mm": 30.0})`。

| 段 | 关键字段 |
|---|---|
| `package.kind` | `standard` / `advanced`:选 RLGC 预设与规范表的 reach / pitch / 模块宽度行 |
| `channel` | `kind: analytic`(`length_mm`,RLGC 可逐项覆盖)或 `touchstone`(`file`,经 vendored Halo 读法) |
| `lanes` | `count`、`skew_ps` / `skew_sigma_ps`、`deskew_step_ps`、`spare_count`、`failed`、`repair` |
| `clocking` | `pll_profile`、`correlation`、`data_path_rj_s`、`clock_path_rj_s`、`tree_delay_ps`、`tree_bw_hz`、`tree_rj_s`、`track_bw_hz`、`dcd_ui` |
| `tx` / `rx` | `swing_vpp`、`bw_hz`;`noise_rms_v`、`ctle.*`、`sampling_phase_ui`、`vref_offset_v` |
| `sim` | `osr`、`n_symbols`、`seed`、`pattern`、`engine`、统计引擎的枚举 / 网格参数 |
| `target` | 留空 = 规范表(带 `source: survey`);写了 = 配置自己的主张 |

`d2d_link.config.form.SECTIONS` 按 Halo 的方式声明了每个字段的表单行(标签、类型、显示比例);GUI 这一轮不做,
测试保证它与 schema 双向一致。

## 两个引擎(铁律 3)

- `run_statistical(cfg)`:主引擎,BER 到 1e-27,眼高 / 眼宽在目标 BER 处,浴盆,残余抖动预算。
- `run_time(cfg, phase_ui=...)`:时域校核,`sim.n_symbols` 个符号;`sim.engine: both` 时 `run_link` 两个都跑并给出比。

## 规范数字(铁律 5)

```bash
grep "source: survey" data/spec/ucie_survey.yaml     # 所有未核实的数字
```

## 工具

| 命令 | 作用 |
|---|---|
| `python tools/run_examples.py --smoke` | 每个示例以 2 万符号跑一遍(CI) |
| `python tools/run_examples.py --save new/` 然后 `python tools/example_drift.py compare new/` | 全尺寸输出与 `examples/expected/` 逐行比,列出文档里仍引用旧值的行 |
| `python tools/fingerprint.py record a.json` / `compare a.json b.json` | 重构前后逐位比对(铁律 6) |
| `python tools/vendor_check.py --strict --siblings Halo_Serdes=... pll_simulator=...` | vendored 文件与钉住的上游一致 |
