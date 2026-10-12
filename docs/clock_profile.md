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
3. **f0/2 以上 S_φ = 0**,网格以下按首值保持(Halo 同)。

本库读它的地方只有 `clock/profile.py`;`clock/forwarded.py` 把它变成数据路径与前向时钟**共享**的定时抖动(铁律 2)。
随库附带的 `data/clock_profiles/bench_markulic16_sspll_40m_10p24g.yaml` 是 Halo 从 pll_simulator ex22 导出的七个文件之一
(Markulic 2016 SSPLL,10.24 GHz,带内 100 Hz..f0/2 约 186 fs)。

vendored 的 `synth_from_psd` / `integrate_pn` 来自 pll_simulator@00e48a2f(`src/d2d_link/vendor/pllsim/`),
`tools/vendor_check.py` 守着与上游逐字节一致。
