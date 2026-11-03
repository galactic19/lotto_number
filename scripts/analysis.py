"""Pattern analysis for the /patterns/ page.

Every candidate rule is scored as the average count of numbers matched per draw (pure chance = pick²/max).
Rules are ranked on an earlier TRAIN span and then scored on the later TEST span they never saw, which is
the only honest way to tell a real pattern from one that only appears in hindsight.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import comb
from typing import Callable

import numpy as np

CONFIG = {
    "history": 200,          # draws a rule needs before it can start predicting
    "test_draws": 200,       # most recent draws held out as the unseen test span
    "sims": 2000,            # random worlds for the frequency test
    "seed": 20021207,
    "alpha": 0.05,
    "z": 1.96,               # 95% band for "better than chance"
    "windows": (5, 10, 20, 30, 50, 100, 200),
    "lags": (1, 2, 3),
}


@dataclass(frozen=True)
class RuleResult:
    name: str
    family: str
    train: float
    test: float


@dataclass(frozen=True)
class Share:
    label: str
    actual: float
    expected: float


@dataclass(frozen=True)
class PatternReport:
    draws: int
    chance: float
    counts: list[tuple[int, int]]          # (number, times drawn), most frequent first
    expected_count: float
    chi_p: float
    repeat_mean: float
    repeat_hist: list[tuple[int, int]]
    odd_shares: list[Share]
    consecutive: Share
    rules: list[RuleResult]                 # sorted by train score, best first
    correlation: float
    fake_best: float
    train_span: tuple[int, int]
    test_span: tuple[int, int]
    noise: float                            # ± range a random rule's test score wanders by luck (95%)

    @property
    def best(self) -> RuleResult:
        return self.rules[0]

    @property
    def frequency_is_random(self) -> bool:
        return self.chi_p > CONFIG["alpha"]

    @property
    def rules_beating_chance(self) -> int:
        """Rules whose test score clears chance by more than luck alone explains."""
        return sum(r.test > self.chance + self.noise for r in self.rules)


class PatternAnalysis:
    def __init__(self, draws: list[list[int]], max_number: int, pick: int):
        self.draws, self.n, self.k = draws, max_number, pick
        self.count = len(draws)
        self.matrix = np.zeros((self.count, max_number + 1), dtype=np.int32)
        for i, d in enumerate(draws):
            self.matrix[i, d] = 1
        self.chance = pick * pick / max_number
        self.rng = np.random.default_rng(CONFIG["seed"])

    # ───────── helpers ─────────
    def random_counts(self) -> np.ndarray:
        """Number counts for one simulated history of the same length."""
        picks = np.argsort(self.rng.random((self.count, self.n)), axis=1)[:, :self.k] + 1
        return np.bincount(picks.ravel(), minlength=self.n + 1)[1:]

    def top(self, scores: np.ndarray) -> np.ndarray:
        """Six numbers with the highest score; ties go to the smaller number so results are stable."""
        order = np.lexsort((np.arange(1, self.n + 1), -scores[1:]))
        return order[:self.k] + 1

    # ───────── individual checks ─────────
    def frequency(self) -> tuple[list[tuple[int, int]], float, float]:
        counts = self.matrix[:, 1:].sum(axis=0)
        expected = self.count * self.k / self.n
        chi = lambda c: float(((c - expected) ** 2 / expected).sum())
        observed = chi(counts)
        worse = sum(chi(self.random_counts()) >= observed for _ in range(CONFIG["sims"]))
        ranked = sorted(((n + 1, int(c)) for n, c in enumerate(counts)), key=lambda x: (-x[1], x[0]))
        return ranked, expected, (worse + 1) / (CONFIG["sims"] + 1)

    def repeats(self) -> tuple[float, list[tuple[int, int]]]:
        r = [len(set(a) & set(b)) for a, b in zip(self.draws, self.draws[1:])]
        return float(np.mean(r)), sorted(Counter(r).items())

    def combinatorics(self) -> tuple[list[Share], Share]:
        total = comb(self.n, self.k)
        odd_total = (self.n + 1) // 2
        hist = Counter(sum(x % 2 for x in d) for d in self.draws)
        odd = [Share(f"홀수 {j}개 : 짝수 {self.k - j}개", hist[j] / self.count,
                     comb(odd_total, j) * comb(self.n - odd_total, self.k - j) / total) for j in range(self.k + 1)]
        has_run = sum(any(b == a + 1 for a, b in zip(d, d[1:])) for d in self.draws) / self.count
        return odd, Share("연속번호 포함", has_run, 1 - comb(self.n - self.k + 1, self.k) / total)

    # ───────── rule mining ─────────
    def rules(self) -> dict[str, tuple[str, Callable[[int, dict], np.ndarray]]]:
        r: dict[str, tuple[str, Callable]] = {}
        for w in CONFIG["windows"]:
            r[f"최근 {w}회 핫넘버"] = ("핫넘버", lambda i, s, w=w: self.top(s["prefix"][i] - s["prefix"][max(0, i - w)]))
            r[f"최근 {w}회 콜드넘버"] = ("콜드넘버", lambda i, s, w=w: self.top(-(s["prefix"][i] - s["prefix"][max(0, i - w)])))
        r["가장 오래 쉰 번호"] = ("출현 간격", lambda i, s: self.top(i - s["last"]))
        r["가장 최근 나온 번호"] = ("출현 간격", lambda i, s: self.top(-(i - s["last"])))
        r["직전 회차 그대로"] = ("흐름", lambda i, s: np.array(self.draws[i - 1]))
        for lag in CONFIG["lags"]:
            r[f"{lag}회 전 번호 뒤따르기"] = ("흐름", lambda i, s, lag=lag: self.top(s["follow"][lag][self.draws[i - lag]].sum(axis=0)))
        return r

    def mine(self) -> tuple[list[RuleResult], float, float, tuple[int, int], tuple[int, int]]:
        split = self.count - CONFIG["test_draws"]
        start = CONFIG["history"]
        rules = self.rules()
        hits = {name: [] for name in rules}
        state = {
            "prefix": np.vstack([np.zeros(self.n + 1, dtype=np.int32), np.cumsum(self.matrix, axis=0)]),
            "last": np.full(self.n + 1, -1),
            "follow": {lag: np.zeros((self.n + 1, self.n + 1), dtype=np.int32) for lag in CONFIG["lags"]},
        }
        for i in range(self.count):
            if i >= start:
                actual = set(self.draws[i])
                for name, (_, rule) in rules.items():
                    hits[name].append(len(actual & set(rule(i, state).tolist())))
            state["last"][self.draws[i]] = i
            for lag, table in state["follow"].items():
                if i >= lag:
                    table[np.ix_(self.draws[i - lag], self.draws[i])] += 1
        cut = split - start
        results = sorted((RuleResult(name, family, float(np.mean(hits[name][:cut])), float(np.mean(hits[name][cut:])))
                          for name, (family, _) in rules.items()), key=lambda r: -r.train)
        correlation = float(np.corrcoef([r.train for r in results], [r.test for r in results])[0, 1])
        fake = max(np.mean([len(set(self.draws[i]) & set(self.top(self.rng.random(self.n + 1)).tolist()))
                            for i in range(start, split)]) for _ in rules)
        return results, correlation, float(fake), (start + 1, split), (split + 1, self.count)

    def run(self) -> PatternReport:
        counts, expected, p = self.frequency()
        repeat_mean, repeat_hist = self.repeats()
        odd, consecutive = self.combinatorics()
        rules, corr, fake, train_span, test_span = self.mine()
        # Matches per draw follow a hypergeometric distribution; its spread over the test span sets the luck band.
        n, k = self.n, self.k
        variance = k * (k / n) * ((n - k) / n) * ((n - k) / (n - 1))
        noise = CONFIG["z"] * (variance / (test_span[1] - test_span[0] + 1)) ** 0.5
        return PatternReport(self.count, self.chance, counts, expected, p, repeat_mean, repeat_hist, odd, consecutive,
                             rules, corr, fake, train_span, test_span, noise)
