# 时钟相噪剖面(与 pll_simulator 的唯一接口)

d2d_link 的发端 PLL 相噪来自 pll_simulator 导出的时钟剖面文件,格式与 Halo_Serdes `docs/clock_profile.md` 定义的一致
(本库是第二个消费端,不改格式):

```yaml
f0_hz: 10240000000.0           # 相噪对应的载波 [Hz];秒数 = 相位 / (2π f0_hz)
f_hz: [100.0, 103.9, ...]      # 频偏网格,递增,> 0
l_dbc_hz: [-92.6, ...]         # 总 L(f),单边带 [dBc/Hz],与 f_hz 等长
spurs: [{f_hz: 40.0e6, dbc: -65.6}]
source: "pllsim preset ..., pllsim 0.9.6, commit ..."
```

三条容易丢的约定(`tests/test_clock_profile.py` 守着):

1. **L(f) 是单边带**:S_φ = 2·10^(L/10)。丢掉这个 2 就是所有抖动数上的 √2。
2. **秒数按文件的 f0 算**,不从数据率推。10.24 GHz 的 PLL 经倍频做 16 GHz DDR 前向时钟,秒数不变。`clocking.pll_f0_hz` 只改比例。
3. **最后一个频点以上**:默认按最后的电平平延到 fs/2(`clocking.profile_above: floor`,0.13.0);`zero` 是 Halo 的约定(f0/2 以上 S_φ = 0)。网格以下按首值保持(Halo 同)。
   0.13.4 用 pll_simulator 的同一模型算到 16 GHz 核过:两个随库 PLL 在 1 GHz 以上都平在 VCO 底噪(Markulic −145.00、Wu −154.00 dBc/Hz,其余各项 < −175),
   所以 `floor` 就是模型,`zero` 只是文件格式在 f0/2 的截断。

本库读它的地方只有 `clock/profile.py`;`clock/forwarded.py` 把它变成数据路径与前向时钟**共享**的定时抖动(铁律 2),
同一格式的第二个文件可以作收端本地 PLL(`clocking.local_pll_profile`,锁到前向时钟)。随库附带两个 Halo 从 pll_simulator ex22
导出的文件:`bench_markulic16_sspll_40m_10p24g.yaml`(Markulic 2016 SSPLL,10.24 GHz,带内 100 Hz..f0/2 约 186 fs、底噪延到 16 GHz 时 226.5 fs;0.13.7 前的默认发端)
与 `bench_wu19_spll_frac_52m_6p253g.yaml`(Wu 2019 分数 SPLL,6.25 GHz,约 88 fs、底噪延到 16 GHz 时 119.9 fs;0.13.7 前示例 04 的本地 PLL)。0.13.7 起 bundled 配置与示例 04 用下面的 `_to16g` 版本,f0/2 版本留给测试与示例 10。

**算到链路 Nyquist 的剖面**(0.13.4):pll_simulator 的导出器按格式只写 100 Hz..f0/2,也拒绝外推。`tools/export_profile_to_nyquist.py --pllsim <checkout> <preset>`
在 100 Hz..`--f-hi`(默认 16 GHz)的对数网格上直接分析模型,按同一格式写出 `<preset>_to16g.yaml`(source 行写明 pllsim 版本、commit 与本工具)。
随库附两个:`bench_markulic16_sspll_40m_10p24g_to16g.yaml` 与 `bench_wu19_spll_frac_52m_6p253g_to16g.yaml`(pllsim 0.9.6 @ 00e48a2f)。
读它们时两种口径给出同一预算:x1 泄漏 223.42 fs(f0/2 文件 + floor 223.43)、总 365.52 fs、眼宽 0.7091 UI;x16 模块总 331.54 对 331.56 fs
(`tests/test_clock_profile.py::test_profile_to_nyquist_matches_the_floor_reading`)。0.13.7 起 bundled 配置都指向 `_to16g` 文件(眼宽变 ≤ 8e-6 UI;`tests/test_clock_profile.py` 守着每个 bundled 剖面覆盖到 fs/2),口径不再影响任何结论;f0/2 文件留给测试与示例 10 的读法对照。
还开着的是底噪本身:−145 dBc/Hz 是 pllsim 预设的 VCO 参数 `pn_floor_dbchz`,不是从 Markulic 2016 原文读的(未核实)。
另一个口径问题这里不解决:10.24 GHz 载波在 16 GHz 偏移处的连续时间相噪,经时钟边沿采样后如何折叠,由消费端的时钟方案决定;本库把它当作边沿率 fs 上的定时噪声。

vendored 的 `synth_from_psd` / `integrate_pn` 来自 pll_simulator@00e48a2f(`src/d2d_link/vendor/pllsim/`),
`tools/vendor_check.py` 守着与上游逐字节一致。

## 杂散(spurs)

`spurs: [{f_hz, dbc}]` 从 0.6.0 起**被两个引擎使用**(此前只读入不用):每条单边带 `dbc` 的杂散是峰值 2·10^(dbc/20) rad 的正弦相位调制,
除以 2π·f0 得到秒。发端 PLL 的杂散对数据与前向时钟共模,经 |E_track·(1 − ρG)| 泄漏(ρ < 1 时另有一项经 |E·√(1−ρ²)·G|,相位独立);
本地 PLL 的杂散经 |E·H_tree·(1 − H_pll)|。闭式里是正弦幅度(`JitterBudget.spur_s` = √(ΣA²/2)),统计引擎把它作反正弦分布的采样偏移核
(远小于高斯 σ 的杂散并入方差),时域合成逐块加正弦并保持相位连续。`ForwardedClock.spur_terms()` 列出采样器处的每条残余幅度。

