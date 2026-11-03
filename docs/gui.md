# 浏览器 GUI(段 8)

页面就是 `tools/budget_report.py` 的时序预算报表,按"什么决定判定"的顺序排版;标题句里带下划线的值是控件。
GUI 不含仿真逻辑(铁律 1):它只编辑 overrides、把 frozen `LinkConfig` 交给 worker 进程里的 `run_link`、渲染拿回来的结果。

## 启动

```bash
pip install -e ".[gui]"                                    # Dash >= 3, Plotly
d2d-link-gui configs/standard_32g_x16_module.yaml          # http://127.0.0.1:8050
d2d-link-gui configs/standard_32g_x5_coupled.yaml --also sensitivity,rate_sweep,sweep:reach
d2d-link-gui configs/standard_32g_x1.yaml --compare configs/standard_32g_x16_repair.yaml
d2d-link-gui configs/standard_32g_x1.yaml --workers 0      # 内联跑(调试)
d2d-link-gui configs/standard_32g_x1.yaml --no-cache       # 不写磁盘缓存
```

| 参数 | 含义 |
|---|---|
| `config` | 打开并运行的链路配置;左栏列出同目录的其它 `*.yaml` 作场景 |
| `--configs DIR` | 场景目录(默认配置所在目录) |
| `--workers N` | worker 进程数(默认 2;0 = 内联) |
| `--port N` / `--host H` | 监听端口与地址(默认 8050、127.0.0.1) |
| `--no-autorun` | 打开配置但不自动运行 |
| `--also a,b` | 启动时就排进队列的任务:`sensitivity`、`rate_sweep`、`sweep:track_bw`、`sweep:local_pll_fn`、`sweep:reach` |
| `--compare PATH` | 启动时就在 "Compare with" 里选中的场景 |
| `--cache DIR` / `--no-cache` | 结果缓存目录(默认 `$XDG_CACHE_HOME/d2d_link/gui` 或 `~/.cache/d2d_link/gui`),按配置哈希存 JSON,重启后秒开;文件带库版本号,别的版本写的(或 0.12.1 之前没有版本号的)会被忽略并重跑 |
| `--open-drawer` | 启动时打开 All fields 抽屉 |

## 页面

- **标题句**:封装、速率、长度、lane 数、串扰模式、布线是控件;改一个 = 一条 override + 入队重跑,旧数字置灰保留到新结果落地。
- **1 Verdict**:三格(眼宽 / 眼高 / BER 各自的约束 lane)、逐 lane 眼宽条对目标、一句"时序判定还是幅度判定"。
- **Compare with**(选了场景才出现):两场景的判定、损耗、时钟残余、最差 lane 眼与裕度并排,逐 lane 眼宽条左右对照。
- **2 What flips the verdict**:按钮入队敏感性(1 + 2 × 旋钮次运行);完成后一句结论、tornado、表。导出的 Markdown 自动带上。
- **3 Clock-path jitter**:各项 fs 与方差占比,功率和;前向时钟一句话。
- **4 Eye & bathtub per lane**:所有 lane 浴盆叠一条轴(log10 BER 截到 −60),选中 lane 在前。
- **5 Lanes and repair**:物理 lane 平面图(按比例眼六边形 + 目标 mask;死 bump 斜纹、闲置 / 备用灰、最差琥珀、不过的红;点选后攻击 lane 虚线圈出)+ 按裕度排序的表。
- **6 Crosstalk / 7 Receiver**:报表原句。
- **A–C Sweeps**:tracker 带宽、本地 PLL 自然频率、reach,各一个按钮入队(每点一次运行),完成后眼宽 + 时钟残余曲线与表。
- **右栏**:This page(来源计数、overrides 数)、Queue(进度 / 剩余时间 / 取消)、Inspector(选中 lane 的眼对目标、浴盆、事实)、Data rate × package、Export(Markdown 与 CLI 逐字同文、JSON、overrides YAML)、Unverified inputs(survey 条目 + cite)。
- **All fields 抽屉**:由 `config/form.py::SECTIONS` 生成,折叠组一行摘要,来源标签 yaml / default / model / survey / override;改动只写 overrides,按 Re-run 才跑。

## 耗时(空闲机器,2 个 worker;运行一行是 0.12.2,其余 0.11 量的,0.12 的 512 UI 窗让每次运行多约 20 %)

| 任务 | x1 25 mm | x5 耦合 25 mm | x16 模块 20 mm |
|---|---|---|---|
| 运行 | 1.3 s | 14 s | 19 s |
| 敏感性(17 次) | ~30 s | 348 s | — |
| 速率扫描(6 档) | ~10 s | 167 s | 222 s |
| tracker 带宽扫描(12 点) | 18 s | — | — |

## 健壮性(段 10,0.12.1)

- 浏览器每秒轮询,但服务端只在**渲染键**变了才重绘:配置 / overrides / 选中 lane / 比较场景 / 任务状态进度(页面与左栏)、再加运行中任务的秒数(右栏队列)、
  抽屉的折叠组。什么都没变的 tick 返回 204,图不换、悬停缩放不丢。标签页切到后台时轮询停(5 s 内恢复)。
- 当前配置的运行**失败**时页面顶部出红色横幅(错误原文),This page 卡的状态也写 failed;有旧结果时旧结果置灰保留。worker 进程死掉(OOM、被杀)时进程池自动重建,
  受影响的任务标 failed 并说明,再按 Run 即可。
- 编辑被拒(非数字、负数、`lanes.count` 4.5 这类非整数)不再静默弹回:抽屉底部与 This page 卡显示"rejected: 字段: 原因",直到下一次成功的编辑。
- 场景栏按**配置哈希**找该文件自己的运行(以前按 label,带 override 的运行会被当成文件的结果)。
- Queue 的 ✕ 只在排队中的任务上出现:进程池无法中断已经开始的任务(悬停提示)。
- 键盘:lane 格、场景行、字段组都能 Tab 到、Enter / 空格激活,焦点有可见轮廊;窄于 1100 px 时三栏变一栏。
- 测试:`App.handle` 是回调主体,测试直接驱动它(tick 不重绘、点选、编辑、丢弃);失败路径、编辑拒绝、场景匹配、导出、缓存版本、
  `workers=1` 的进程池(排队 / 取消 / 进度)、`main()` 参数解析都有测试。

## 不做

- 深色主题;多用户共享服务(缓存与 worker 没有按用户隔离);Android(以后用同一套页面,后端跑服务器);真实 bump map(仓库里没有,平面图是一维物理编号)。
