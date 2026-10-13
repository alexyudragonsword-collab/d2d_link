# 用法

```bash
pip install -e ".[touchstone,plot,test]"
python examples/00_single_lane_eye.py        # 单 lane:预算、眼、两引擎
python examples/01_tracking_bandwidth_sweep.py
python examples/02_reach_sweep.py
python examples/03_stat_vs_time.py           # 1e-6 处的一致性比,约 3–5 分钟
python examples/04_local_pll_bandwidth.py    # 收端本地 PLL 的环路带宽
python examples/05_module_xtalk_repair.py    # x16 / x64 模块:skew、串扰、修复
python examples/06_m2_consistency.py         # 新机制上的统计 / 时域一致性
python examples/07_rate_sweep.py             # 规范表全部速率档 × 两种封装,耦合串扰,预算报表
python examples/08_crosstalk_physics.py      # 布线方式 / 反向 lane NEXT / 单端 Touchstone 文件
pytest -q
```

## 三行

```python
from d2d_link.config import load_config
from d2d_link.engine import run_link

res = run_link(load_config("configs/standard_32g_x1.yaml"))
print(res.summary())      # 每 lane:BER(10^log10)、眼高/眼宽对目标(带 source)、残余抖动;res.worst 是裕度最小的 lane
```

## 配置就是一切(铁律 1)

`configs/*.yaml` 镜像 `d2d_link.config.schema.LinkConfig` 的嵌套结构;未知键报错。扫描用 `dataclasses.replace`
或 `apply_overrides(cfg, {"channel.length_mm": 30.0})`。

| 段 | 关键字段 |
|---|---|
| `package.kind` | `standard` / `advanced`:选 RLGC 预设与规范表的 reach / pitch / 模块宽度行 |
| `channel` | `kind: analytic`(`length_mm`,RLGC 可逐项覆盖)或 `touchstone`(`file`,经 vendored Halo 读法);`xtalk: fext`(行为级幅度,`xtalk_adjacent_db` 留空取封装预设)或 `xtalk: coupled`(从几何估计:`trace_pitch_um` 留空取规范表的 bump 间距,线宽 / 介质厚 / εr 取 `PACKAGE_STACKUP` 预设);段 6:`routing`、`xtalk: touchstone`、`xtalk_next` + `next_db`、`touchstone_mode` + `touchstone_lanes` |
| `lanes` | `count`、`skew_ps` / `skew_sigma_ps`、`deskew_step_ps`、`spare_count`、`failed`、`repair`、`reverse_adjacent` + `reverse_phase_ui`(旁边有反向 lane 的物理 lane,取 NEXT) |
| `clocking` | 发端:`pll_profile`、`correlation`、`data_path_rj_s`、`clock_path_rj_s`、`*_wander_s` + `wander_corner_hz`;收端:`local_pll_profile` + `local_pll_fn_hz`(环路自然频率,锁到前向时钟,必须给;−3 dB 带宽 = 2.48 f_n @ ζ = 1,旧键 `local_pll_bw_hz` 仍可读、给 DeprecationWarning)、`tree_delay_ps`、`tree_bw_hz`、`tree_rj_s`、`track_bw_hz`、`track_delay_ui`(延迟在反馈路径里,过快 + 延迟会被 schema 之后的构造拒绝为不稳定)、`pi_step_ui`、`dcd_ui`(收端)、`tx_dcd_ui`(发端共模,有本地 PLL 时才显现)、`wander_floor_hz`(漫游 RMS 的频带下沿) |
| `tx` / `rx` | `swing_vpp`、`bw_hz`;`noise_rms_v` + `noise_at`(`sampler`:采样点处的 RMS,默认;`input`:前端输入处的白噪声,以奈奎斯特带内 RMS 给出,经前端 × CTLE 整形后到采样器,需要有限的 `bw_hz`)、`bw_hz`(收端前端一阶极点,留空 = 平坦,段 7)、`ctle.*`、`sampling_phase_ui`、`vref_offset_v`、`training_ber`(训练在哪个 BER 上找眼边并居中;留空 = 目标 BER) |
| `sim` | `osr`、`n_symbols`、`seed`、`pattern`、`engine`、`time_mode`(waveform / samples)+ `time_cursor_floor`、统计引擎的 ISI 分布 bin(`stat_isi_bin_v`)/ 相位网格参数 |
| `target` | 留空 = 规范表(带 `source: survey`);写了 = 配置自己的主张 |

`d2d_link.config.form.SECTIONS` 按 Halo 的方式声明了每个字段的表单行(标签、类型、显示比例);GUI 这一轮不做,
测试保证它与 schema 双向一致。

## 两个引擎(铁律 3)

- `run_statistical(cfg)`:主引擎,BER 到 1e-27,眼高 / 眼宽在目标 BER 处,浴盆,残余抖动预算。
- `run_time(cfg, phase_ui=...)`:时域校核,`sim.n_symbols` 个符号(> 2^24 时抖动按块流式合成);`sim.engine: both` 时 `run_link` 两个都跑并给出比。
  `pytest -m slow tests/test_engines_deep.py` 跑 1e9 符号的 3e-8 一致性点(每周 CI);`D2D_DEEP_SYMBOLS` / `D2D_DEEP_BER` 可改。
- `run_link(cfg)`:整个模块 —— lane 映射与修复、逐 lane skew 残余、邻 lane 串扰(按物理邻接,死 lane 与闲置备用 lane 静默)、
  最差 lane 判定;`LinkResult.summary()`。
- `ForwardedClock(cfg).budget()`:残余抖动的闭式分解(发端泄漏、本地 PLL、路径白噪、漫游、树);`residual_vs_local_pll_bw`、`residual_vs_track_bw` 扫曲线。

## 规范数字(铁律 5)

```bash
grep "source: survey" src/d2d_link/data/spec/ucie_survey.yaml     # 所有未核实的规范数字
grep "source: model"  src/d2d_link/data/spec/model_presets.yaml   # 所有模型估计数(走线损耗、叠层、行为级串扰)
python tools/budget_report.py configs/standard_32g_x5_coupled.yaml --sensitivity   # 哪些估计 ±20% 会翻转结论
```

走线的 L、C 不是预设:由 `channel.z0_ohm`(预设 50 Ω)与叠层几何的 Hammerstad ε_eff 推出(`LinkConfig.rlgc()`),显式给
`l_h_m` / `c_f_m` 时覆盖。发端带宽 `tx.bw_hz` 留空 = 2 × Nyquist,`inf` = 理想边沿。

## 工具

| 命令 | 作用 |
|---|---|
| `python tools/run_examples.py --smoke` | 每个示例以 2 万符号跑一遍(CI) |
| `python tools/run_examples.py --save new/` 然后 `python tools/example_drift.py compare new/` | 全尺寸输出与 `examples/expected/` 逐行比,列出文档里仍引用旧值的行 |
| `python tools/fingerprint.py record a.json` / `compare a.json b.json` | 重构前后逐位比对(铁律 6) |
| `python tools/budget_report.py configs/x.yaml [-o x.md] [--json x.json]` | 时序预算报表:逐项抖动(fs / UI)、目标与来源、串扰参数、逐 lane 眼与裕度 |
| `python tools/vendor_check.py --strict --siblings Halo_Serdes=... pll_simulator=...` | vendored 文件与钉住的上游一致 |
