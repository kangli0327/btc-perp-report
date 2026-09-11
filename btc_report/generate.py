from __future__ import annotations

import json
import shutil
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .advice import build_advice
from .binance import fetch_market_data
from .config import load_position, load_preference
from .daily_report import build_daily_report, load_recent_daily_reports, render_daily_card, render_daily_page
from .indicators import compute_indicators
from .macro_events import build_macro_brief
from .okx_private import fetch_okx_position
from .render import render_report


CN_TZ = ZoneInfo("Asia/Shanghai")
ROOT = Path(__file__).resolve().parents[1]
SITE_DIR = ROOT / "site"
REPORTS_DIR = SITE_DIR / "reports"
DAILY_DIR = SITE_DIR / "daily"


def main() -> None:
    generated_at = datetime.now(tz=CN_TZ)
    archive_name = f"{generated_at:%Y-%m-%d-%H%M}.html"
    try:
        position = fetch_okx_position()
    except Exception as exc:  # noqa: BLE001
        fallback_position = load_position()
        position = replace(fallback_position, source_warning=f"OKX私有仓位同步失败，已使用手动仓位配置：{exc}")
    preference = load_preference()
    market = fetch_market_data("BTCUSDT")
    indicators = compute_indicators(market)
    advice = build_advice(position, preference, indicators)
    macro_brief = build_macro_brief(generated_at)
    daily_report = build_daily_report(generated_at, indicators, position, advice, macro_brief, DAILY_DIR)
    recent_daily_reports = load_recent_daily_reports(DAILY_DIR)
    daily_card_html = render_daily_card(daily_report, recent_daily_reports)
    html = render_report(generated_at, market, indicators, position, preference, advice, macro_brief, archive_name, daily_card_html)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = REPORTS_DIR / archive_name
    index_path = SITE_DIR / "index.html"
    archive_path.write_text(html, encoding="utf-8")
    shutil.copyfile(archive_path, index_path)
    (DAILY_DIR / daily_report.archive_name).write_text(render_daily_page(daily_report, recent_daily_reports), encoding="utf-8")
    (DAILY_DIR / "index.json").write_text(
        json.dumps([asdict(item) for item in recent_daily_reports], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (SITE_DIR / ".nojekyll").write_text("", encoding="utf-8")


if __name__ == "__main__":
    main()
