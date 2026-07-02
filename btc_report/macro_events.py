from __future__ import annotations

import html
import re
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from html.parser import HTMLParser
from zoneinfo import ZoneInfo


ET = ZoneInfo("America/New_York")
CN_TZ = ZoneInfo("Asia/Shanghai")

NYFED_URL = "https://www.newyorkfed.org/research/calendars/nationalecon_cal"
FED_URL = "https://www.federalreserve.gov/newsevents/calendar.htm"
BEA_URL = "https://www.bea.gov/news/schedule"
BLS_EMPSIT_URL = "https://www.bls.gov/schedule/news_release/empsit.htm"

HIGH_IMPACT = {
    "FOMC": ("高", "利率预期会直接影响美元流动性和风险资产估值，BTC 通常会放大波动。"),
    "Federal Open Market": ("高", "利率预期会直接影响美元流动性和风险资产估值，BTC 通常会放大波动。"),
    "Consumer Price Index": ("高", "通胀数据会改变降息/加息预期，若高于预期通常压制 BTC，低于预期通常利好风险资产。"),
    "CPI": ("高", "通胀数据会改变降息/加息预期，若高于预期通常压制 BTC，低于预期通常利好风险资产。"),
    "Producer Price Index": ("中高", "PPI 会影响通胀预期，强于预期偏利空 BTC，弱于预期偏利多。"),
    "PPI": ("中高", "PPI 会影响通胀预期，强于预期偏利空 BTC，弱于预期偏利多。"),
    "Employment Situation": ("高", "非农就业会影响美联储路径，强就业偏利空风险资产，弱就业偏利多但也可能引发衰退交易。"),
    "Initial Claims": ("中", "初请失业金影响就业降温预期，异常上升通常降低利率压力。"),
    "Personal Income": ("高", "PCE/收入消费数据是美联储重点通胀线索，容易影响 BTC 短线波动。"),
    "PCE": ("高", "PCE/收入消费数据是美联储重点通胀线索，容易影响 BTC 短线波动。"),
    "Gross Domestic Product": ("中高", "GDP 改变增长预期，过热偏利空降息交易，明显走弱可能引发避险。"),
    "GDP": ("中高", "GDP 改变增长预期，过热偏利空降息交易，明显走弱可能引发避险。"),
    "ISM": ("中", "ISM 反映增长和价格压力，强数据偏利空降息预期，弱数据偏利多流动性预期。"),
    "Michigan Consumer": ("中", "消费者信心和通胀预期会影响美债收益率与风险偏好。"),
}


@dataclass(frozen=True)
class MacroEvent:
    title: str
    source: str
    url: str
    scheduled_at: datetime
    impact: str
    btc_view: str
    expected: str = ""
    previous: str = ""
    my_forecast: str = ""
    btc_direction: str = ""


@dataclass(frozen=True)
class MacroBrief:
    window_start: datetime
    window_end: datetime
    events: list[MacroEvent]
    summary: str
    forecast: str
    warnings: list[str]


class EventHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[tuple[str, str, str]] = []
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href", "") or ""
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            title = " ".join("".join(self._text).split())
            if title:
                self.events.append((title, self._href, self.get_starttag_text() or ""))
            self._href = ""
            self._text = []


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "btc-report/1.0"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _event_profile(title: str) -> tuple[str, str] | None:
    lowered = title.lower()
    for key, profile in HIGH_IMPACT.items():
        if key.lower() in lowered:
            return profile
    return None


def _absolute_url(url: str) -> str:
    if url.startswith("http"):
        return url
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return f"https://www.newyorkfed.org{url}"
    return url


def _parse_nyfed_calendar(page: str, now: datetime) -> list[MacroEvent]:
    year_match = re.search(r"\b(20\d{2})\b", page)
    month_match = re.search(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\b",
        page,
        re.I,
    )
    year = int(year_match.group(1)) if year_match else now.astimezone(ET).year
    month_name = month_match.group(1) if month_match else now.astimezone(ET).strftime("%B")
    month = datetime.strptime(month_name[:3], "%b").month
    events: list[MacroEvent] = []
    cell_pattern = re.compile(r"<div>\s*(\d{1,2})\s*<br/><br/><span class=\"ts-accordion-content\">(.*?)</span>", re.S)
    item_pattern = re.compile(r'<a href="([^"]+)"[^>]*>(.*?)</a>(?:.*?<br/>\((\d{2}:\d{2})\))?', re.S)
    for day_text, cell_html in cell_pattern.findall(page):
        day = int(day_text)
        for href, raw_title, time_text in item_pattern.findall(cell_html):
            title = html.unescape(re.sub(r"<.*?>", "", raw_title)).strip()
            profile = _event_profile(title)
            if not profile:
                continue
            hour, minute = (8, 30)
            if time_text:
                hour, minute = [int(x) for x in time_text.split(":")]
            scheduled = datetime(year, month, day, hour, minute, tzinfo=ET)
            impact, btc_view = profile
            events.append(MacroEvent(title, "New York Fed Economic Calendar", _absolute_url(href), scheduled, impact, btc_view))
    return events


def _source_health(url: str, source: str, warnings: list[str]) -> None:
    try:
        _fetch(url)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"{source} 获取失败：{exc}")


def _curated_events() -> list[MacroEvent]:
    return [
        MacroEvent(
            title="美国6月非农就业报告：非农、失业率、平均时薪、初请失业金",
            source="BLS / Trading Economics / Kiplinger",
            url=BLS_EMPSIT_URL,
            scheduled_at=datetime(2026, 7, 2, 8, 30, tzinfo=ET),
            impact="高",
            btc_view="重点看“就业强度 + 薪资通胀”组合。强就业/强薪资压制降息预期，弱就业/温和薪资有利流动性预期。",
            expected="市场预期：非农约110K-115K；失业率4.3%；平均时薪MoM 0.3%；平均时薪YoY 3.5%；初请失业金约220K。",
            previous="前值：5月非农172K；失业率4.3%；平均时薪MoM 0.3%、YoY 3.4%；初请215K。",
            my_forecast="我的基准判断：非农100K-120K，中心值约110K；失业率大概率维持4.3%；薪资MoM约0.3%。劳动力市场偏稳但降温，不像明显衰退信号。",
            btc_direction="BTC方向：若非农>130K且薪资>=0.3%，美元和美债收益率易走强，短线偏利空BTC；若非农80K-120K且薪资不超预期，偏震荡略利多；若非农<80K或失业率升至4.4%+，先利多降息交易，但若美股同步转弱，BTC可能先冲高后回落。",
        )
    ]


def build_macro_brief(generated_at: datetime) -> MacroBrief:
    start = generated_at.astimezone(CN_TZ)
    end = start + timedelta(hours=24)
    warnings: list[str] = []
    events: list[MacroEvent] = []
    try:
        nyfed_page = _fetch(NYFED_URL)
        events.extend(_parse_nyfed_calendar(nyfed_page, start))
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"New York Fed 经济日历获取失败：{exc}")

    _source_health(FED_URL, "Federal Reserve 日程", warnings)
    _source_health(BEA_URL, "BEA 新闻日程", warnings)
    _source_health(BLS_EMPSIT_URL, "BLS 就业报告日程", warnings)
    events.extend(_curated_events())

    filtered = [
        event
        for event in events
        if start <= event.scheduled_at.astimezone(CN_TZ) <= end
    ]
    filtered.sort(key=lambda item: item.scheduled_at)
    deduped: list[MacroEvent] = []
    seen: set[tuple[str, str]] = set()
    for event in filtered:
        key = (event.title.lower(), event.scheduled_at.astimezone(CN_TZ).strftime("%Y-%m-%d %H:%M"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(event)

    if deduped:
        high_count = sum(1 for event in deduped if event.impact in {"高", "中高"})
        directional = next((event for event in deduped if event.btc_direction), deduped[0])
        summary = f"未来24小时识别到 {len(deduped)} 个宏观事件，其中 {high_count} 个为高/中高影响。重点关注：{directional.title}。"
        forecast = directional.btc_direction or "事件窗口内 BTC 可能放大波动；高杠杆短线仓位应提前设置止损，避免在数据公布前后追单。"
    else:
        summary = "未来24小时未在已接入官方日历中识别到高影响宏观事件。"
        forecast = "若无临时新闻冲击，BTC 短线更可能由技术位、资金费率、持仓拥挤和美元流动性预期驱动。"

    return MacroBrief(start, end, deduped[:8], summary, forecast, warnings)
