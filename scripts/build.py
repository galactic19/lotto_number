"""Build index.html from src/template.html and the draw history in data/all.json.

Usage:
    python3 scripts/build.py            # build from the local data file
    python3 scripts/build.py --update   # download the latest history first
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import string
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_URL = "https://smok95.github.io/lotto/results/all.json"
DATA_FILE = ROOT / "data" / "all.json"
TEMPLATE_FILE = ROOT / "src" / "template.html"
OUTPUT_FILE = ROOT / "index.html"
PLACEHOLDER = "/*__DATA__*/"
FONT_PLACEHOLDER = "/*__FONT__*/"
FONT_FAMILY = "Pretendard"
FONT_WEIGHT_RANGE = "45 920"
FONT_URL = "https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/web/variable/woff2/PretendardVariable.woff2"
FONT_CACHE = ROOT / ".cache" / "PretendardVariable.woff2"
NUMBERS_PER_DRAW = 6


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


class DrawRepository:
    def __init__(self, path: Path, url: str):
        self.path, self.url = path, url

    def update(self) -> None:
        download(self.url, self.path)

    def load(self) -> list[Draw]:
        draws = [Draw.from_raw(r) for r in json.loads(self.path.read_text(encoding="utf-8"))]
        return sorted(draws, key=lambda d: d.no)


def download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as res:
        path.write_bytes(res.read())


class FontEmbedder:
    """Subsets the font to the characters the page uses and returns an inline @font-face rule."""

    def __init__(self, url: str, cache: Path):
        self.url, self.cache = url, cache

    def font_face(self, text: str) -> str:
        from fontTools import subset  # requires: pip install -r requirements.txt

        if not self.cache.exists():
            download(self.url, self.cache)
        chars = set(text) | set(string.printable)
        options = subset.Options()
        options.flavor = "woff2"
        options.layout_features = ["*"]
        font = subset.load_font(str(self.cache), options)
        subsetter = subset.Subsetter(options)
        subsetter.populate(text="".join(chars))
        subsetter.subset(font)
        buffer = io.BytesIO()
        subset.save_font(font, buffer, options)
        data = base64.b64encode(buffer.getvalue()).decode("ascii")
        return (f'@font-face {{ font-family: "{FONT_FAMILY}"; font-weight: {FONT_WEIGHT_RANGE}; '
                f'font-display: swap; src: url(data:font/woff2;base64,{data}) format("woff2"); }}')


class PageBuilder:
    def __init__(self, template: Path, output: Path, fonts: FontEmbedder):
        self.template, self.output, self.fonts = template, output, fonts

    @staticmethod
    def inject(html: str, placeholder: str, value: str) -> str:
        if placeholder not in html:
            raise ValueError(f"{placeholder} not found in template")
        return html.replace(placeholder, value)

    def build(self, draws: list[Draw]) -> None:
        html = self.template.read_text(encoding="utf-8")
        payload = json.dumps([d.__dict__ for d in draws], ensure_ascii=False, separators=(",", ":"))
        html = self.inject(html, FONT_PLACEHOLDER, self.fonts.font_face(html))
        self.output.write_text(self.inject(html, PLACEHOLDER, payload), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="download the latest draw history first")
    args = parser.parse_args()

    repo = DrawRepository(DATA_FILE, DATA_URL)
    if args.update:
        repo.update()
    draws = repo.load()
    PageBuilder(TEMPLATE_FILE, OUTPUT_FILE, FontEmbedder(FONT_URL, FONT_CACHE)).build(draws)
    print(f"Built {OUTPUT_FILE.name}: draws 1-{draws[-1].no} ({len(draws)} total)")


if __name__ == "__main__":
    main()
