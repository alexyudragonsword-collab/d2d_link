import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

PROFILE = "data/clock_profiles/bench_markulic16_sspll_40m_10p24g.yaml"
