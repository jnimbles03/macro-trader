"""End-to-end mock pipeline test — must produce two valid trade ideas.

Combined with PAPER_MODE + MOCK_DATA, output should be deterministic.
"""

import os

os.environ["MOCK_DATA"] = "true"
os.environ["PAPER_MODE"] = "true"
os.environ["DEFAULT_ACCOUNT_SIZE"] = "100000"

from app.config import reload_settings  # noqa: E402

reload_settings()

from app.reports.markdown_renderer import render_brief  # noqa: E402
from app.reports.trade_report import generate_trade_brief  # noqa: E402


def test_mock_pipeline_produces_two_trades():
    brief = generate_trade_brief(lookback_hours=48, fresh=True)
    md = render_brief(brief)
    # both slots should resolve to a real trade in mock mode (fixtures are sufficient)
    spread = brief.selector.spread.trade
    yolo = brief.selector.yolo.trade
    assert spread is not None, f"expected spread trade in mock mode, got NO TRADE: {brief.selector.spread.detail}"
    assert yolo is not None, f"expected yolo trade in mock mode, got NO TRADE: {brief.selector.yolo.detail}"

    # spread RR clears 2.0 floor
    assert spread.rr_ratio >= 2.0

    # YOLO is single long
    assert len(yolo.legs) == 1 and yolo.legs[0].action == "BUY"
    assert yolo.why_probably_dumb is not None and yolo.why_probably_dumb.strip()

    # Disclaimer present in markdown
    assert "not financial advice" in md.lower()


def test_mock_pipeline_is_deterministic():
    a = render_brief(generate_trade_brief(lookback_hours=48, fresh=True))
    b = render_brief(generate_trade_brief(lookback_hours=48, fresh=True))
    # Generated_at lines differ; strip those.
    def normalize(s):
        return "\n".join(l for l in s.splitlines() if not l.lower().startswith("generated:"))
    assert normalize(a) == normalize(b)
