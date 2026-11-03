"""Build index.html from src/template.html and the draw history in data/all.json.

Usage:
    python3 scripts/build.py            # build from the local data file
    python3 scripts/build.py --update   # download the latest history first
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_URL = "https://smok95.github.io/lotto/results/all.json"
DATA_FILE = ROOT / "data" / "all.json"
TEMPLATE_FILE = ROOT / "src" / "template.html"
OUTPUT_FILE = ROOT / "index.html"
PLACEHOLDER = "/*__DATA__*/"
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
        with urllib.request.urlopen(self.url, timeout=60) as res:
            self.path.write_bytes(res.read())

    def load(self) -> list[Draw]:
        draws = [Draw.from_raw(r) for r in json.loads(self.path.read_text(encoding="utf-8"))]
        return sorted(draws, key=lambda d: d.no)


class PageBuilder:
    def __init__(self, template: Path, output: Path):
        self.template, self.output = template, output

    def build(self, draws: list[Draw]) -> None:
        html = self.template.read_text(encoding="utf-8")
        if PLACEHOLDER not in html:
            raise ValueError(f"{PLACEHOLDER} not found in {self.template}")
        payload = json.dumps([d.__dict__ for d in draws], ensure_ascii=False, separators=(",", ":"))
        self.output.write_text(html.replace(PLACEHOLDER, payload), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="download the latest draw history first")
    args = parser.parse_args()

    repo = DrawRepository(DATA_FILE, DATA_URL)
    if args.update:
        repo.update()
    draws = repo.load()
    PageBuilder(TEMPLATE_FILE, OUTPUT_FILE).build(draws)
    print(f"Built {OUTPUT_FILE.name}: draws 1-{draws[-1].no} ({len(draws)} total)")


if __name__ == "__main__":
    main()
