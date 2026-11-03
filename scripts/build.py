"""Build the site from src/template.html and the draw history in data/all.json.

Outputs:
    index.html            full HTML document for GitHub Pages (SEO meta, JSON-LD, static summary)
    og.png                1200x630 social preview with the latest draw
    sitemap.xml           single-URL sitemap, lastmod = latest draw date
    .cache/artifact.html  page fragment for the claude.ai artifact (its host adds the document shell)

Usage:
    python3 scripts/build.py            # build from the local data file
    python3 scripts/build.py --update   # download the latest history first
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
import re
import string
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_URL = "https://smok95.github.io/lotto/results/all.json"
DATA_FILE = ROOT / "data" / "all.json"
TEMPLATE_FILE = ROOT / "src" / "template.html"
CACHE_DIR = ROOT / ".cache"
NUMBERS_PER_DRAW = 6

FONT_FAMILY = "Pretendard"
FONT_WEIGHT_RANGE = "45 920"
FONT_URL = "https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/web/variable/woff2/PretendardVariable.woff2"
FONT_CACHE = CACHE_DIR / "PretendardVariable.woff2"


@dataclass(frozen=True)
class Site:
    url: str = "https://galactic19.github.io/lotto_number/"
    name: str = "로또 연구소"
    title: str = "로또 번호 생성기 · 역대 당첨번호 분석 알고리즘 | 로또 연구소"
    locale: str = "ko_KR"
    lang: str = "ko"
    og_image: str = "og.png"
    og_size: tuple[int, int] = (1200, 630)

    def absolute(self, path: str) -> str:
        return self.url + path


SITE = Site()


class Placeholder:
    DATA = "/*__DATA__*/"
    FONT = "/*__FONT__*/"
    HEAD = "<!--__HEAD__-->"
    SUMMARY = "<!--__SUMMARY__-->"
    UPDATED = "<!--__UPDATED__-->"


# ───────── Data ─────────
@dataclass(frozen=True)
class Draw:
    no: int
    numbers: list[int]
    bonus: int
    date: str

    @classmethod
    def from_raw(cls, raw: dict) -> "Draw":
        numbers = sorted(raw["numbers"])
        if len(numbers) != NUMBERS_PER_DRAW:
            raise ValueError(f"Draw {raw['draw_no']} has {len(numbers)} numbers")
        return cls(raw["draw_no"], numbers, raw["bonus_no"], raw["date"][:10])


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
class Summary:
    """Facts about the history that the static page, meta tags and preview image all share."""
    latest: Draw
    total: int
    hot: list[int]
    strategy_count: int

    @classmethod
    def of(cls, draws: list[Draw], template: str) -> "Summary":
        counts = Counter(n for d in draws for n in d.numbers)
        hot = sorted(n for n, _ in counts.most_common(NUMBERS_PER_DRAW))
        strategy_count = len(re.findall(r"class \w+ extends Strategy\b", template))
        return cls(draws[-1], len(draws), hot, strategy_count)

    @staticmethod
    def join(numbers: list[int]) -> str:
        return ", ".join(map(str, numbers))

    @property
    def latest_text(self) -> str:
        d = self.latest
        return f"{d.no}회 당첨번호: {self.join(d.numbers)} + 보너스 {d.bonus}"

    @property
    def description(self) -> str:
        return (f"역대 {self.total:,}회 로또 6/45 당첨번호를 분석해 핫넘버·콜드넘버·동반출현 등 "
                f"{self.strategy_count}가지 알고리즘으로 번호를 뽑고, 백테스트로 실제 적중률을 비교해요. "
                f"최신 {self.latest_text}.")

    @property
    def sentence(self) -> str:
        y, m, d = self.latest.date.split("-")
        return (f"최신 {self.latest.no}회({y}년 {int(m)}월 {int(d)}일) 당첨번호는 {self.join(self.latest.numbers)}, "
                f"보너스 {self.latest.bonus}번이에요. 1회부터 {self.latest.no}회까지 가장 많이 나온 번호는 "
                f"{self.join(self.hot)}번이에요.")


# ───────── Template tokens (read from the template so colours and bands live in one place) ─────────
class TemplateTokens:
    def __init__(self, template: str):
        self.template = template

    def css(self, name: str) -> str:
        match = re.search(rf"--{re.escape(name)}:\s*(#[0-9a-fA-F]{{3,8}})", self.template)
        if not match:
            raise ValueError(f"CSS token --{name} not found in template")
        return match.group(1)

    def ball_groups(self) -> list[int]:
        match = re.search(r"ballGroups:\s*\[([\d,\s]+)\]", self.template)
        return [int(x) for x in match.group(1).split(",")]

    def ball_color(self, n: int) -> str:
        index = next(i for i, upper in enumerate(self.ball_groups()) if n <= upper) + 1
        return self.css(f"ball-{index}")


# ───────── Font ─────────
class FontEmbedder:
    """Subsets the font to the characters the page uses and returns an inline @font-face rule."""

    def __init__(self, url: str, cache: Path):
        self.url, self.cache = url, cache

    def path(self) -> Path:
        if not self.cache.exists():
            download(self.url, self.cache)
        return self.cache

    def font_face(self, text: str) -> str:
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
        data = base64.b64encode(buffer.getvalue()).decode("ascii")
        return (f'@font-face {{ font-family: "{FONT_FAMILY}"; font-weight: {FONT_WEIGHT_RANGE}; '
                f'font-display: swap; src: url(data:font/woff2;base64,{data}) format("woff2"); }}')


# ───────── SEO head ─────────
class SeoHead:
    def __init__(self, site: Site, summary: Summary):
        self.site, self.summary = site, summary

    def json_ld(self) -> str:
        data = {
            "@context": "https://schema.org",
            "@type": "WebApplication",
            "name": self.site.name,
            "url": self.site.url,
            "description": self.summary.description,
            "inLanguage": self.site.lang,
            "applicationCategory": "UtilitiesApplication",
            "operatingSystem": "Any",
            "isAccessibleForFree": True,
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "KRW"},
            "image": self.site.absolute(self.site.og_image),
            "dateModified": self.summary.latest.date,
        }
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    def render(self) -> str:
        e = lambda v: html.escape(v, quote=True)
        image = self.site.absolute(self.site.og_image)
        width, height = self.site.og_size
        tags = [
            f'<meta name="description" content="{e(self.summary.description)}">',
            f'<link rel="canonical" href="{e(self.site.url)}">',
            '<meta name="robots" content="index, follow, max-image-preview:large">',
            f'<meta property="og:type" content="website">',
            f'<meta property="og:site_name" content="{e(self.site.name)}">',
            f'<meta property="og:locale" content="{self.site.locale}">',
            f'<meta property="og:title" content="{e(self.site.title)}">',
            f'<meta property="og:description" content="{e(self.summary.description)}">',
            f'<meta property="og:url" content="{e(self.site.url)}">',
            f'<meta property="og:image" content="{e(image)}">',
            f'<meta property="og:image:width" content="{width}">',
            f'<meta property="og:image:height" content="{height}">',
            f'<meta property="og:image:alt" content="{e(self.summary.latest_text)}">',
            '<meta name="twitter:card" content="summary_large_image">',
            f'<meta name="twitter:title" content="{e(self.site.title)}">',
            f'<meta name="twitter:description" content="{e(self.summary.description)}">',
            f'<meta name="twitter:image" content="{e(image)}">',
            f'<script type="application/ld+json">{self.json_ld()}</script>',
        ]
        return "\n".join(tags)


# ───────── Preview image ─────────
class OgImage:
    def __init__(self, site: Site, summary: Summary, tokens: TemplateTokens, font_path: Path):
        self.site, self.summary, self.tokens, self.font_path = site, summary, tokens, font_path

    def font(self, size: int, weight: int):
        from PIL import ImageFont

        font = ImageFont.truetype(str(self.font_path), size)
        font.set_variation_by_axes([weight])
        return font

    def render(self, out: Path) -> None:
        from PIL import Image, ImageDraw

        width, height = self.site.og_size
        pad, ball, gap = 80, 104, 20
        img = Image.new("RGB", (width, height), self.tokens.css("bg"))
        draw = ImageDraw.Draw(img)
        ink, muted = self.tokens.css("ink"), self.tokens.css("muted")
        draw.text((pad, pad), "로또 6/45 데이터 실험실", font=self.font(34, 600), fill=muted)
        draw.text((pad, pad + 52), self.site.name, font=self.font(92, 800), fill=ink)
        draw.text((pad, pad + 172), f"최신 {self.summary.latest.no}회 · {self.summary.latest.date}",
                  font=self.font(34, 600), fill=muted)

        balls = [*self.summary.latest.numbers, None, self.summary.latest.bonus]
        x, y = pad, height - pad - ball
        number_font, plus_font = self.font(46, 700), self.font(52, 600)
        for n in balls:
            if n is None:
                draw.text((x + 4, y + ball / 2), "+", font=plus_font, fill=muted, anchor="lm")
                x += 52
                continue
            draw.ellipse((x, y, x + ball, y + ball), fill=self.tokens.ball_color(n))
            draw.text((x + ball / 2, y + ball / 2), str(n), font=number_font, fill=self.tokens.css("ball-text"), anchor="mm")
            x += ball + gap
        img.save(out, optimize=True)


# ───────── Pages ─────────
class Sitemap:
    def __init__(self, site: Site, summary: Summary):
        self.site, self.summary = site, summary

    def render(self) -> str:
        return ('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                f"  <url><loc>{html.escape(self.site.url)}</loc><lastmod>{self.summary.latest.date}</lastmod></url>\n"
                "</urlset>\n")


class PageBuilder:
    def __init__(self, site: Site, fonts: FontEmbedder):
        self.site, self.fonts = site, fonts

    @staticmethod
    def inject(text: str, placeholder: str, value: str) -> str:
        if placeholder not in text:
            raise ValueError(f"{placeholder} not found in template")
        return text.replace(placeholder, value)

    def body(self, template: str, draws: list[Draw], summary: Summary) -> str:
        payload = json.dumps([d.__dict__ for d in draws], ensure_ascii=False, separators=(",", ":"))
        page = self.inject(template, Placeholder.FONT, self.fonts.font_face(template + summary.sentence))
        page = self.inject(page, Placeholder.SUMMARY, html.escape(summary.sentence))
        page = self.inject(page, Placeholder.UPDATED, f"마지막 업데이트: {summary.latest.date} ({summary.latest.no}회)")
        return self.inject(page, Placeholder.DATA, payload)

    def document(self, fragment: str, summary: Summary) -> str:
        head_end = fragment.index("</style>") + len("</style>")
        head = re.sub(r"<title>.*?</title>", f"<title>{html.escape(self.site.title)}</title>", fragment[:head_end], count=1)
        head = self.inject(head, Placeholder.HEAD, SeoHead(self.site, summary).render())
        return (f'<!doctype html>\n<html lang="{self.site.lang}">\n<head>\n<meta charset="utf-8">\n'
                '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                f"{head}\n</head>\n<body>{fragment[head_end:]}\n</body>\n</html>\n")

    def build(self, draws: list[Draw]) -> Summary:
        template = TEMPLATE_FILE.read_text(encoding="utf-8")
        summary = Summary.of(draws, template)
        fragment = self.body(template, draws, summary)

        (ROOT / "index.html").write_text(self.document(fragment, summary), encoding="utf-8")
        CACHE_DIR.mkdir(exist_ok=True)
        (CACHE_DIR / "artifact.html").write_text(self.inject(fragment, Placeholder.HEAD, ""), encoding="utf-8")
        (ROOT / "sitemap.xml").write_text(Sitemap(self.site, summary).render(), encoding="utf-8")
        OgImage(self.site, summary, TemplateTokens(template), self.fonts.path()).render(ROOT / self.site.og_image)
        return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--update", action="store_true", help="download the latest draw history first")
    args = parser.parse_args()

    repo = DrawRepository(DATA_FILE, DATA_URL)
    if args.update:
        repo.update()
    draws = repo.load()
    summary = PageBuilder(SITE, FontEmbedder(FONT_URL, FONT_CACHE)).build(draws)
    print(f"Built index.html, og.png, sitemap.xml: draws 1-{summary.latest.no} ({summary.total} total)")


if __name__ == "__main__":
    main()
