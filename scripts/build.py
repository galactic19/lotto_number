"""Build the static site from src/ and the draw history in data/all.json.

Outputs:
    _site/                 everything GitHub Pages serves (pages, assets, og.png, sitemap.xml)
    .cache/artifact.html   the home page as one self-contained fragment for the claude.ai artifact

Usage:
    python3 scripts/build.py            # build from the local data file
    python3 scripts/build.py --update   # download the latest history first
    python3 -m http.server -d _site     # preview at http://localhost:8000/
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import shutil
import string
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from itertools import groupby
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from analysis import PatternAnalysis

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
TEMPLATES = SRC / "templates"
JS_DIR = SRC / "js"
BASE_CSS = SRC / "base.css"
RULES_FILE = SRC / "rules.json"
DATA_URL = "https://smok95.github.io/lotto/results/all.json"
DATA_FILE = ROOT / "data" / "all.json"
OUT = ROOT / "_site"
CACHE = ROOT / ".cache"
ARTIFACT_FILE = CACHE / "artifact.html"
ASSETS = "assets/"

FONT_FAMILY = "Pretendard"
FONT_WEIGHT_RANGE = "45 920"
FONT_URL = "https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/web/variable/woff2/PretendardVariable.woff2"
FONT_CACHE = CACHE / "PretendardVariable.woff2"
FONT_FILE = "pretendard.woff2"


@dataclass(frozen=True)
class Site:
    domain: str = "lottelab.app"          # custom domain; GitHub Pages serves it at the root over HTTPS
    name: str = "로또 연구소"
    locale: str = "ko_KR"
    lang: str = "ko"
    og_image: str = "og.png"
    og_size: tuple[int, int] = (1200, 630)
    theme_key: str = "lotto-lab-theme"

    @property
    def url(self) -> str:
        return f"https://{self.domain}/"

    def absolute(self, path: str = "") -> str:
        return self.url + path

    def title(self, text: str) -> str:
        return f"{text} | {self.name}"


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    path: str


SITE = Site()
NAV = [
    NavItem("home", "번호 생성", ""),
    NavItem("draws", "회차별 당첨번호", "draws/"),
    NavItem("patterns", "패턴 분석", "patterns/"),
    NavItem("calculator", "실수령액 계산기", "calculator/"),
    NavItem("check", "내 번호 확인", "check/"),
    NavItem("pension", "연금복권720+", "pension/"),
]
NAV_PATH = {item.key: item.path for item in NAV}
YEARS_PATH = f"{NAV_PATH['draws']}years/"
ROWS_PER_AD = 15          # draws-list tables get a banner after every this many rows


# ───────── Shared source values (read from src so CSS/JS stay the single source of truth) ─────────
class SourceTokens:
    def __init__(self):
        self.css = BASE_CSS.read_text(encoding="utf-8")
        self.common_js = (JS_DIR / "common.js").read_text(encoding="utf-8")

    def color(self, name: str) -> str:
        match = re.search(rf"--{re.escape(name)}:\s*(#[0-9a-fA-F]{{3,8}})", self.css)
        if not match:
            raise ValueError(f"CSS token --{name} not found in base.css")
        return match.group(1)

    def js_number(self, key: str) -> int:
        return int(re.search(rf"\b{key}:\s*(\d+)", self.common_js).group(1))

    @property
    def ball_groups(self) -> list[int]:
        match = re.search(r"ballGroups:\s*\[([\d,\s]+)\]", self.common_js)
        return [int(x) for x in match.group(1).split(",")]

    def ball_band(self, n: int) -> int:
        return next(i for i, upper in enumerate(self.ball_groups) if n <= upper) + 1

    def strategy_count(self) -> int:
        return len(re.findall(r"class \w+ extends Strategy\b", (JS_DIR / "home.js").read_text(encoding="utf-8")))


TOKENS = SourceTokens()
MAX_NUMBER = TOKENS.js_number("maxNumber")
PICK_COUNT = TOKENS.js_number("pickCount")
RULES = json.loads(RULES_FILE.read_text(encoding="utf-8"))


# ───────── Tax (mirrors Tax.compute in common.js) ─────────
@dataclass(frozen=True)
class TaxResult:
    prize: int
    tax: int
    net: int


def compute_tax(prize: int, deduct_ticket: bool = True) -> TaxResult:
    rules = RULES["tax"]
    if prize <= rules["taxFreeLimit"]:
        return TaxResult(prize, 0, prize)
    taxable = max(0, prize - (rules["ticketPrice"] if deduct_ticket else 0))
    tax, floor = 0, 0
    for bracket in rules["brackets"]:
        upper = bracket["upTo"] if bracket["upTo"] is not None else taxable
        base = max(0, min(taxable, upper) - floor)
        tax += int(base * bracket["rate"])
        floor = upper
    return TaxResult(prize, tax, prize - tax)


# ───────── Data ─────────
@dataclass(frozen=True)
class Division:
    prize: int
    winners: int


@dataclass(frozen=True)
class Draw:
    no: int
    numbers: list[int]
    bonus: int
    date: str
    divisions: list[Division]
    sales: int
    auto: int | None
    manual: int | None

    @classmethod
    def from_raw(cls, raw: dict) -> "Draw":
        numbers = sorted(raw["numbers"])
        if len(numbers) != PICK_COUNT:
            raise ValueError(f"Draw {raw['draw_no']} has {len(numbers)} numbers")
        divisions = [Division(d.get("prize", 0), d.get("winners", 0)) for d in raw.get("divisions", [])]
        combo = raw.get("winners_combination") or {}
        return cls(raw["draw_no"], numbers, raw["bonus_no"], raw["date"][:10], divisions,
                   raw.get("total_sales_amount") or 0, combo.get("auto"), combo.get("manual"))

    @property
    def first(self) -> Division:
        return self.divisions[0] if self.divisions else Division(0, 0)

    def payload(self) -> dict:
        return {"no": self.no, "numbers": self.numbers, "bonus": self.bonus, "date": self.date,
                "prizes": [d.prize for d in self.divisions]}


def download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as res:
        path.write_bytes(res.read())


class DrawRepository:
    def __init__(self, path: Path, url: str):
        self.path, self.url = path, url

    def update(self) -> None:
        download(self.url, self.path)

    def load(self) -> list[Draw]:
        draws = [Draw.from_raw(r) for r in json.loads(self.path.read_text(encoding="utf-8"))]
        return sorted(draws, key=lambda d: d.no)


@dataclass(frozen=True)
class NumberRow:
    n: int
    count: int
    gap: int | None


@dataclass(frozen=True)
class DrawStats:
    total: int
    odd: int
    even: int
    low: int
    high: int
    run_text: str
    numbers: list[NumberRow]
    half: int = (MAX_NUMBER + 1) // 2
    max: int = MAX_NUMBER


def longest_run(numbers: list[int]) -> int:
    best = run = 1
    for a, b in zip(numbers, numbers[1:]):
        run = run + 1 if b == a + 1 else 1
        best = max(best, run)
    return best


def draw_stats(draws: list[Draw]) -> dict[int, DrawStats]:
    """Per-draw pattern stats plus each number's running count and gap, computed in one pass."""
    counts: Counter[int] = Counter()
    last_seen: dict[int, int] = {}
    half = (MAX_NUMBER + 1) // 2
    result = {}
    for d in draws:
        rows = []
        for n in d.numbers:
            counts[n] += 1
            rows.append(NumberRow(n, counts[n], d.no - last_seen[n] if n in last_seen else None))
            last_seen[n] = d.no
        odd = sum(n % 2 for n in d.numbers)
        low = sum(n <= half for n in d.numbers)
        run = longest_run(d.numbers)
        result[d.no] = DrawStats(sum(d.numbers), odd, PICK_COUNT - odd, low, PICK_COUNT - low,
                                 f"{run}개 이어짐" if run > 1 else "없음", rows)
    return result


@dataclass(frozen=True)
class Summary:
    """Facts about the history that pages, meta tags and the preview image share."""
    latest: Draw
    total: int
    hot: list[int]
    strategy_count: int

    @classmethod
    def of(cls, draws: list[Draw]) -> "Summary":
        counts = Counter(n for d in draws for n in d.numbers)
        hot = sorted(n for n, _ in counts.most_common(PICK_COUNT))
        return cls(draws[-1], len(draws), hot, TOKENS.strategy_count())

    @staticmethod
    def join(numbers: list[int]) -> str:
        return ", ".join(map(str, numbers))

    @property
    def latest_text(self) -> str:
        d = self.latest
        return f"{d.no}회 당첨번호: {self.join(d.numbers)} + 보너스 {d.bonus}"

    @property
    def description(self) -> str:
        return (f"로또 6/45 당첨번호 {self.total:,}회치를 분석해서 자주 나온 번호, 오래 안 나온 번호 등 "
                f"{self.strategy_count}가지 방법으로 번호를 뽑아 드려요. 지난 회차로 직접 시험한 결과도 함께 보여 드려요. "
                f"최신 {self.latest_text}.")

    @property
    def sentence(self) -> str:
        return (f"최신 {self.latest.no}회({date_ko(self.latest.date)}) 당첨번호는 {self.join(self.latest.numbers)}이고 "
                f"보너스 번호는 {self.latest.bonus}번이에요. 1회부터 {self.latest.no}회까지 가장 많이 나온 번호는 "
                f"{self.join(self.hot)}번이에요.")


def date_ko(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{y}년 {int(m)}월 {int(d)}일"


def date_dot(iso: str) -> str:
    """Compact date for tables and labels: 2026.10.31."""
    return iso.replace("-", ".")


HANGUL_START, HANGUL_COUNT, JONG_COUNT = 0xAC00, 11172, 28


def josa(word: str, pair: str) -> str:
    """Attach the right particle: josa("초과분", "은/는") -> "초과분은". pair is "with-batchim/without"."""
    with_final, without_final = pair.split("/")
    code = ord(word[-1]) - HANGUL_START
    has_final = 0 <= code < HANGUL_COUNT and code % JONG_COUNT != 0
    return word + (with_final if has_final else without_final)


def draw_path(draw: Draw) -> str:
    return f"{NAV_PATH['draws']}{draw.no}/"


def won(n: int) -> str:
    return f"{n:,}원"


EOK = 10 ** 8


def won_eok(n: int) -> str:
    """Large amounts in 억 원 so stat tiles stay on one line."""
    return f"{n / EOK:,.0f}억 원"


# ───────── Pages ─────────
@dataclass
class Page:
    path: str
    template: str
    nav: str
    title: str
    description: str
    scripts: list[str] = field(default_factory=list)
    context: dict = field(default_factory=dict)
    schema_type: str = "WebPage"
    lastmod: str = ""

    @property
    def url(self) -> str:
        return SITE.absolute(self.path)

    @property
    def root(self) -> str:
        return "../" * self.path.count("/")

    def breadcrumbs(self) -> list[tuple[str, str]]:
        trail = [(SITE.name, SITE.url)]
        nav = next((n for n in NAV if n.key == self.nav and n.path), None)
        if nav:
            trail.append((nav.label, SITE.absolute(nav.path)))
        if self.path and (not nav or self.path != nav.path):
            trail.append((self.title.split(" | ")[0], self.url))
        return trail

    @property
    def json_ld(self) -> list[dict]:
        main = {"@context": "https://schema.org", "@type": self.schema_type, "name": self.title.split(" | ")[0],
                "url": self.url, "description": self.description, "inLanguage": SITE.lang}
        if self.schema_type == "WebApplication":
            main |= {"applicationCategory": "UtilitiesApplication", "operatingSystem": "Any", "isAccessibleForFree": True,
                     "offers": {"@type": "Offer", "price": "0", "priceCurrency": "KRW"}}
        if self.lastmod:
            main["dateModified"] = self.lastmod
        blocks = [main]
        crumbs = self.breadcrumbs()
        if len(crumbs) > 1:
            blocks.append({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "name": name, "item": url} for i, (name, url) in enumerate(crumbs)]})
        return blocks


class SitePages:
    """Builds every Page from the draw history."""

    def __init__(self, draws: list[Draw], summary: Summary):
        self.draws, self.summary = draws, summary
        self.latest_date = summary.latest.date

    def all(self) -> list[Page]:
        return [self.home(), *self.year_pages(), *self.draw_pages(), self.patterns(), self.calculator(), self.check(), self.pension()]

    def home(self) -> Page:
        return Page("", "home.html", "home", SITE.title("로또 번호 생성기 · 당첨번호 분석으로 고르는 로또 번호 추천"),
                    self.summary.description, ["common.js", "home.js"],
                    {"draws_payload": [d.payload() for d in self.draws]}, "WebApplication", self.latest_date)

    def year_pages(self) -> list[Page]:
        """One list page per year (newest first). The latest year lives at /draws/ so the index stays short."""
        years = [(year, list(group)) for year, group in groupby(reversed(self.draws), key=lambda d: d.date[:4])]
        links = [{"year": year, "path": NAV_PATH["draws"] if i == 0 else f"{YEARS_PATH}{year}/"} for i, (year, _) in enumerate(years)]
        latest = self.summary.latest
        pages = []
        for i, (year, draws) in enumerate(years):
            first, last = draws[-1], draws[0]
            is_index = i == 0
            title = (f"이번 주 로또 당첨번호 {latest.no}회 · 회차별 당첨번호 전체 조회" if is_index
                     else f"{year}년 로또 당첨번호 ({first.no}~{last.no}회)")
            description = (f"이번 주 로또 {latest.no}회({date_ko(latest.date)}) 당첨번호는 {Summary.join(latest.numbers)}이고 "
                           f"보너스 번호는 {latest.bonus}번이에요. 1회부터 모든 회차의 당첨번호와 1등 당첨금을 연도별로 찾아볼 수 있어요."
                           if is_index else
                           f"{year}년 로또 {first.no}회부터 {last.no}회까지의 당첨번호, 1등 당첨금, 당첨자 수를 모았어요. "
                           "회차를 누르면 등수별 당첨금과 번호 분석이 나와요.")
            chunks = [draws[k:k + ROWS_PER_AD] for k in range(0, len(draws), ROWS_PER_AD)]
            pages.append(Page(links[i]["path"], "draws.html", "draws", SITE.title(title), description, ["common.js"],
                              {"year": year, "chunks": chunks, "year_links": links, "heading": title, "index_path": NAV_PATH["draws"],
                               "is_index": is_index, "latest": latest, "latest_tax": compute_tax(latest.first.prize),
                               "newer": links[i - 1] if i else None, "older": links[i + 1] if i + 1 < len(links) else None},
                              "CollectionPage", last.date))
        return pages

    def draw_pages(self) -> list[Page]:
        stats = draw_stats(self.draws)
        pages = []
        for i, d in enumerate(self.draws):
            first = d.first
            first_tax = compute_tax(first.prize)
            ranks = [{**rule, "prize": div.prize, "winners": div.winners}
                     for rule, div in zip(RULES["ranks"], d.divisions)]
            prize_text = (f"1등은 {first.winners}명이고 1인당 {won(first.prize)}(실수령 {won(first_tax.net)})을 받아요"
                          if first.winners else "1등 당첨자가 없어서 당첨금이 다음 회차로 넘어갔어요")
            pages.append(Page(
                draw_path(d), "draw.html", "draws",
                SITE.title(f"로또 {d.no}회 당첨번호 ({date_dot(d.date)})"),
                f"로또 {d.no}회({date_ko(d.date)}) 당첨번호는 {Summary.join(d.numbers)}이고 보너스 번호는 {d.bonus}번이에요. "
                f"{prize_text}. 등수별 당첨금과 번호 분석도 볼 수 있어요.",
                ["common.js"],
                {"d": d, "first": first, "first_tax": first_tax, "ranks": ranks, "stats": stats[d.no],
                 "prev": self.draws[i - 1] if i else None, "next": self.draws[i + 1] if i + 1 < len(self.draws) else None},
                "WebPage", d.date))
        return pages

    def patterns(self) -> Page:
        report = PatternAnalysis([d.numbers for d in self.draws], MAX_NUMBER, PICK_COUNT).run()
        best = report.best
        return Page(NAV_PATH["patterns"], "patterns.html", "patterns",
                    SITE.title("로또 패턴 분석 · 당첨번호에 규칙이 있을까?"),
                    f"자주 나오는 번호, 오래 안 나온 번호, 지난주 번호 등 로또 규칙 {len(report.rules)}가지를 1~{report.draws}회 "
                    f"실제 기록으로 시험했어요. 가장 잘 맞던 규칙도 최근 회차에서는 평균 {best.test:.2f}개를 맞혀, "
                    f"아무렇게나 고른 것({report.chance:.2f}개)과 차이가 없었어요.",
                    ["common.js"], {"r": report}, "WebPage", self.latest_date)

    def calculator(self) -> Page:
        latest = self.summary.latest
        record = max(self.draws, key=lambda d: d.first.prize)
        second = latest.divisions[1].prize if len(latest.divisions) > 1 else 0
        presets = [{"label": f"{latest.no}회 1등", "value": latest.first.prize},
                   {"label": f"{latest.no}회 2등", "value": second},
                   {"label": "역대 최고 1등", "value": record.first.prize},
                   {"label": "10억 원", "value": 10 ** 9}, {"label": "3억 원", "value": 3 * 10 ** 8}]
        return Page(NAV_PATH["calculator"], "calculator.html", "calculator",
                    SITE.title("로또 당첨금 실수령액 계산기 · 세금 자동 계산"),
                    f"로또 당첨금을 넣으면 세금과 실수령액을 바로 계산해요. {latest.no}회 1등 당첨금 {won(latest.first.prize)}을 받으면 "
                    f"실제로 {won(compute_tax(latest.first.prize).net)}이 손에 들어와요. 세금은 3억 원까지 22%, 넘는 부분은 33%예요.",
                    ["common.js", "calculator.js"],
                    {"presets": presets, "record": record, "latest_first": latest.first,
                     "latest_first_tax": compute_tax(latest.first.prize)},
                    "WebApplication", self.latest_date)

    def check(self) -> Page:
        latest = self.summary.latest
        return Page(NAV_PATH["check"], "check.html", "check",
                    SITE.title("내 로또 번호 역대 당첨 확인 · 1회부터 몇 등?"),
                    f"번호 6개를 고르면 1회부터 {latest.no}회까지 매주 그 번호로 샀을 때 몇 등에 몇 번 당첨됐을지 "
                    "알려 드려요. 쓴 돈과 받은 돈도 함께 계산해요.",
                    ["common.js", "check.js"],
                    {"draws_payload": [d.payload() for d in self.draws], "max_number": MAX_NUMBER},
                    "WebApplication", self.latest_date)

    def pension(self) -> Page:
        ranks = []
        for r in RULES["pension"]["ranks"]:
            amount = r.get("monthly") or r["lump"]
            text = f"매월 {won(amount)} × {r['months'] // 12}년" if "monthly" in r else won(amount)
            ranks.append({**r, "amount_text": text, "net": compute_tax(amount, deduct_ticket=False).net})
        first = RULES["pension"]["ranks"][0]
        return Page(NAV_PATH["pension"], "pension.html", "pension",
                    SITE.title("연금복권720+ 번호 생성기 · 등수별 당첨금"),
                    f"연금복권720+ 조와 6자리 번호를 무작위로 뽑아요. 1등은 매월 {won(first['monthly'])}씩 "
                    f"{first['months'] // 12}년 동안 받고, 세금을 떼면 매월 {won(ranks[0]['net'])}이에요. 등수별 당첨금과 구매 방법도 정리했어요.",
                    ["common.js", "pension.js"], {"pension_ranks": ranks}, "WebApplication", self.latest_date)


# ───────── Font ─────────
class FontSubset:
    def __init__(self, url: str, cache: Path):
        self.url, self.cache = url, cache

    def path(self) -> Path:
        if not self.cache.exists():
            download(self.url, self.cache)
        return self.cache

    def build(self, text: str) -> bytes:
        from fontTools import subset  # requires: pip install -r requirements.txt

        options = subset.Options()
        options.flavor = "woff2"
        options.layout_features = ["*"]
        font = subset.load_font(str(self.path()), options)
        subsetter = subset.Subsetter(options)
        subsetter.populate(text="".join(set(text) | set(string.printable)))
        subsetter.subset(font)
        buffer = io.BytesIO()
        subset.save_font(font, buffer, options)
        return buffer.getvalue()

    @staticmethod
    def face(src: str) -> str:
        return (f'@font-face {{ font-family: "{FONT_FAMILY}"; font-weight: {FONT_WEIGHT_RANGE}; '
                f'font-display: swap; src: url({src}) format("woff2"); }}\n')


# ───────── Preview image ─────────
class OgImage:
    def __init__(self, summary: Summary, font_path: Path):
        self.summary, self.font_path = summary, font_path

    def font(self, size: int, weight: int):
        from PIL import ImageFont

        font = ImageFont.truetype(str(self.font_path), size)
        font.set_variation_by_axes([weight])
        return font

    def render(self, out: Path) -> None:
        from PIL import Image, ImageDraw

        width, height = SITE.og_size
        pad, ball, gap = 80, 104, 20
        img = Image.new("RGB", (width, height), TOKENS.color("bg"))
        draw = ImageDraw.Draw(img)
        ink, muted = TOKENS.color("ink"), TOKENS.color("muted")
        draw.text((pad, pad), "로또 6/45 데이터 실험실", font=self.font(34, 600), fill=muted)
        draw.text((pad, pad + 52), SITE.name, font=self.font(92, 800), fill=ink)
        draw.text((pad, pad + 172), f"최신 {self.summary.latest.no}회 · {self.summary.latest.date}",
                  font=self.font(34, 600), fill=muted)
        x, y = pad, height - pad - ball
        number_font, plus_font = self.font(46, 700), self.font(52, 600)
        for n in [*self.summary.latest.numbers, None, self.summary.latest.bonus]:
            if n is None:
                draw.text((x + 4, y + ball / 2), "+", font=plus_font, fill=muted, anchor="lm")
                x += 52
                continue
            draw.ellipse((x, y, x + ball, y + ball), fill=TOKENS.color(f"ball-{TOKENS.ball_band(n)}"))
            draw.text((x + ball / 2, y + ball / 2), str(n), font=number_font, fill=TOKENS.color("ball-text"), anchor="mm")
            x += ball + gap
        img.save(out, optimize=True)


def robots() -> str:
    """Allow everything and point crawlers at the sitemap (only honoured at a domain root)."""
    return f"User-agent: *\nAllow: /\n\nSitemap: {SITE.absolute('sitemap.xml')}\n"


def sitemap(pages: list[Page]) -> str:
    urls = "\n".join(f"  <url><loc>{p.url}</loc><lastmod>{p.lastmod}</lastmod></url>" for p in pages)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{urls}\n</urlset>\n")


# ───────── Builder ─────────
class SiteBuilder:
    def __init__(self, draws: list[Draw]):
        self.draws = draws
        self.summary = Summary.of(draws)
        self.env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True, undefined=StrictUndefined,
                               trim_blocks=True, lstrip_blocks=True)
        self.env.globals.update(site=SITE, nav=NAV, rules=RULES, summary=self.summary,
                                ball_band=TOKENS.ball_band, draw_path=draw_path, date_ko=date_ko, date_dot=date_dot, won_eok=won_eok)
        self.env.filters["josa"] = josa
        self.fonts = FontSubset(FONT_URL, FONT_CACHE)
        self.version = self.source_hash()

    def source_hash(self) -> str:
        digest = hashlib.sha256(str(self.summary.latest.no).encode())
        for path in sorted([*SRC.rglob("*"), Path(__file__)]):
            if path.is_file():
                digest.update(path.read_bytes())
        return digest.hexdigest()[:10]

    @staticmethod
    def js(name: str) -> str:
        return (JS_DIR / name).read_text(encoding="utf-8")

    def render(self, page: Page, inline: bool = False, css_inline: str = "") -> str:
        assets = ({"css_inline": css_inline, "js": [self.js(s) for s in page.scripts]} if inline else
                  {"css": f"{ASSETS}site.css?v={self.version}", "js": [f"{ASSETS}{s}?v={self.version}" for s in page.scripts]})
        return self.env.get_template(page.template).render(page=page, root=page.root, inline=inline, assets=assets, **page.context)

    def build(self) -> list[Page]:
        if OUT.exists():
            shutil.rmtree(OUT)
        pages = SitePages(self.draws, self.summary).all()
        html_by_path = {page.path: self.render(page) for page in pages}

        scripts = sorted({s for page in pages for s in page.scripts})
        glyph_text = "".join(html_by_path.values()) + "".join(self.js(s) for s in scripts) + BASE_CSS.read_text(encoding="utf-8")
        font = self.fonts.build(glyph_text)
        css = BASE_CSS.read_text(encoding="utf-8")

        self.write(f"{ASSETS}{FONT_FILE}", font)
        self.write(f"{ASSETS}site.css", FontSubset.face(f"{FONT_FILE}?v={self.version}") + css)
        for script in scripts:
            self.write(f"{ASSETS}{script}", self.js(script))
        for path, html in html_by_path.items():
            self.write(f"{path}index.html", html)
        self.write("sitemap.xml", sitemap(pages))
        self.write("robots.txt", robots())
        self.write("CNAME", f"{SITE.domain}\n")
        OgImage(self.summary, self.fonts.path()).render(OUT / SITE.og_image)

        inline_css = FontSubset.face(f"data:font/woff2;base64,{base64.b64encode(font).decode()}") + css
        CACHE.mkdir(exist_ok=True)
        ARTIFACT_FILE.write_text(self.render(pages[0], inline=True, css_inline=inline_css), encoding="utf-8")
        return pages

    @staticmethod
    def write(relative: str, content: str | bytes) -> None:
        target = OUT / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--update", action="store_true", help="download the latest draw history first")
    args = parser.parse_args()

    repo = DrawRepository(DATA_FILE, DATA_URL)
    if args.update:
        repo.update()
    draws = repo.load()
    pages = SiteBuilder(draws).build()
    print(f"Built {len(pages)} pages into {OUT.name}/: draws 1-{draws[-1].no}")


if __name__ == "__main__":
    main()
