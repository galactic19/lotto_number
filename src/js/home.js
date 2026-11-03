/* Home page: data-driven number generator, frequency chart and backtest. Uses helpers from common.js. */
const CONFIG = Object.freeze({
  ...SITE,
  tickets: { min: 1, max: 10, initial: 5 },
  recentWindow: 50,
  chartTicks: 5,
  chartWindows: [{ label: "전체", size: null }, { label: "최근 100회", size: 100 }, { label: "최근 50회", size: 50 }],
  balance: { sumPercentiles: [0.1, 0.9], oddRange: [2, 4], lowRange: [2, 4], maxRun: 2, maxTries: 400 },
  backtest: { draws: 100, ticketsPerDraw: 20, minHit: 3, seed: 20021207 },
  defaultStrategies: ["hot", "balanced"],
});

/* ───────── Utilities ───────── */
const zeros = () => new Array(CONFIG.maxNumber + 1).fill(0);
const quantile = (sorted, q) => sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))];
const inRange = (v, [lo, hi]) => v >= lo && v <= hi;
/** Rounds max/targetTicks up to 1, 2 or 5 × 10^k so axis labels stay readable. */
const niceStep = (max, targetTicks) => {
  const raw = max / targetTicks, mag = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw);
};

/** Picks one index (1..max) with probability proportional to its weight. */
function weightedPick(weights, rng) {
  let r = rng() * weights.reduce((a, b) => a + b, 0);
  const n = weights.findIndex((v) => (r -= v) < 0);
  return n > 0 ? n : NUMBERS.find((x) => weights[x] > 0);
}
/** Probability that a random ticket matches at least `min` of the drawn numbers (hypergeometric). */
const matchProbability = (min) => {
  const { maxNumber: N, pickCount: K } = CONFIG;
  let p = 0;
  for (let m = min; m <= K; m++) p += (choose(K, m) * choose(N - K, K - m)) / choose(N, K);
  return p;
};

function mulberry32(seed) {
  return () => {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/* ───────── Data model ───────── */
class LottoHistory {
  constructor(draws) {
    this.draws = draws;
    this._cache = new Map();
  }
  memo(key, fn) {
    if (!this._cache.has(key)) this._cache.set(key, fn());
    return this._cache.get(key);
  }
  get last() { return this.draws[this.draws.length - 1]; }
  slice(end) { return new LottoHistory(this.draws.slice(0, end)); }
  recent(size) { return size ? this.draws.slice(-size) : this.draws; }

  frequency(size = null) {
    return this.memo(`freq:${size}`, () => {
      const f = zeros();
      this.recent(size).forEach((d) => d.numbers.forEach((n) => f[n]++));
      return f;
    });
  }
  gaps() {
    return this.memo("gaps", () => {
      const g = zeros().map(() => this.draws.length);
      this.draws.forEach((d, i) => d.numbers.forEach((n) => (g[n] = this.draws.length - 1 - i)));
      return g;
    });
  }
  pairs() {
    return this.memo("pairs", () => {
      const m = Array.from({ length: CONFIG.maxNumber + 1 }, zeros);
      this.draws.forEach(({ numbers }) => numbers.forEach((a) => numbers.forEach((b) => a !== b && m[a][b]++)));
      return m;
    });
  }
  transitions() {
    return this.memo("trans", () => {
      const m = Array.from({ length: CONFIG.maxNumber + 1 }, zeros);
      for (let i = 1; i < this.draws.length; i++)
        this.draws[i - 1].numbers.forEach((a) => this.draws[i].numbers.forEach((b) => m[a][b]++));
      return m;
    });
  }
  sumRange() {
    return this.memo("sum", () => {
      const sums = this.draws.map((d) => d.numbers.reduce((a, b) => a + b, 0)).sort((a, b) => a - b);
      return CONFIG.balance.sumPercentiles.map((q) => quantile(sums, q));
    });
  }
}

/* ───────── Balance filter (composable with any strategy) ───────── */
class BalanceFilter {
  constructor(history) { this.sumRange = history.sumRange(); }
  static longestRun(sorted) {
    let best = 1, run = 1;
    for (let i = 1; i < sorted.length; i++) { run = sorted[i] === sorted[i - 1] + 1 ? run + 1 : 1; best = Math.max(best, run); }
    return best;
  }
  accepts(ticket) {
    const { oddRange, lowRange, maxRun } = CONFIG.balance;
    const half = Math.ceil(CONFIG.maxNumber / 2);
    return inRange(ticket.reduce((a, b) => a + b, 0), this.sumRange)
      && inRange(ticket.filter((n) => n % 2).length, oddRange)
      && inRange(ticket.filter((n) => n <= half).length, lowRange)
      && BalanceFilter.longestRun(ticket) <= maxRun;
  }
}

/* ───────── Strategies: each only defines how it scores numbers ───────── */
class Strategy {
  constructor(id, name, desc) { Object.assign(this, { id, name, desc }); }
  weights(_history) { return zeros().map((_, n) => (n ? 1 : 0)); }
  explain(_history, _ticket) { return ""; }

  sample(history, rng) {
    const w = this.weights(history).slice();
    const picked = [];
    while (picked.length < CONFIG.pickCount) {
      const choice = weightedPick(w, rng);
      picked.push(choice);
      w[choice] = 0;
    }
    return picked.sort((a, b) => a - b);
  }
  generate(history, rng, filter = null) {
    let ticket = this.sample(history, rng);
    for (let i = 0; filter && !filter.accepts(ticket) && i < CONFIG.balance.maxTries; i++) ticket = this.sample(history, rng);
    return ticket;
  }
}

const topOf = (scores, ticket) => ticket.slice().sort((a, b) => scores[b] - scores[a])[0];

class HotStrategy extends Strategy {
  constructor() { super("hot", "핫넘버", `최근 ${CONFIG.recentWindow}회에 자주 나온 번호일수록 가중치를 높여요.`); }
  weights(h) { return h.frequency(CONFIG.recentWindow).map((f, n) => (n ? f + 1 : 0)); }
  explain(h, t) { const f = h.frequency(CONFIG.recentWindow), n = topOf(f, t); return `${n}번: 최근 ${CONFIG.recentWindow}회 중 ${f[n]}번 출현`; }
}
class ColdStrategy extends Strategy {
  constructor() { super("cold", "콜드넘버", "오래 안 나온 번호일수록 '나올 때가 됐다'고 보고 가중치를 줘요."); }
  weights(h) { return h.gaps().map((g, n) => (n ? g + 1 : 0)); }
  explain(h, t) { const g = h.gaps(), n = topOf(g, t); return `${n}번: ${g[n]}회째 미출현`; }
}
class PairStrategy extends Strategy {
  constructor() { super("pair", "동반출현", "역대로 함께 자주 나온 번호 쌍을 따라가며 조합을 만들어요."); }
  sample(h, rng) {
    const m = h.pairs();
    const picked = [weightedPick(h.frequency(), rng)];
    while (picked.length < CONFIG.pickCount) {
      const w = zeros().map((_, n) => (n && !picked.includes(n) ? picked.reduce((s, p) => s + m[p][n], 0) + 1 : 0));
      picked.push(weightedPick(w, rng));
    }
    return picked.sort((a, b) => a - b);
  }
  explain(h, t) {
    const m = h.pairs();
    const [a, b] = t.flatMap((x) => t.filter((y) => y > x).map((y) => [x, y])).sort((p, q) => m[q[0]][q[1]] - m[p[0]][p[1]])[0];
    return `${a}·${b}번: 역대 ${m[a][b]}회 함께 출현`;
  }
}
class TransitionStrategy extends Strategy {
  constructor() { super("trans", "흐름 추적", "지난 회차 번호 다음 회차에 자주 이어서 나온 번호를 골라요 (마르코프 전이)."); }
  weights(h) {
    const m = h.transitions();
    return zeros().map((_, n) => (n ? h.last.numbers.reduce((s, p) => s + m[p][n], 0) + 1 : 0));
  }
  explain(h, t) { const w = this.weights(h), n = topOf(w, t); return `${n}번: 지난 회차(${h.last.no}회) 번호 뒤에 ${w[n] - 1}회 이어서 출현`; }
}
class BalancedStrategy extends Strategy {
  constructor() { super("balanced", "균형 랜덤", "완전 랜덤에 균형 필터를 항상 적용해 '당첨번호다운' 모양만 남겨요."); }
  generate(h, rng) { return super.generate(h, rng, new BalanceFilter(h)); }
  explain(_h, t) { return `합계 ${t.reduce((a, b) => a + b, 0)} · 홀짝 ${t.filter((n) => n % 2).length}:${t.filter((n) => !(n % 2)).length}`; }
}
class RandomStrategy extends Strategy {
  constructor() { super("random", "순수 랜덤", "아무 데이터도 안 쓰는 대조군이에요. 다른 알고리즘과 비교하는 기준점이에요."); }
  explain() { return "45개 번호 균등 추첨"; }
}

const STRATEGIES = [HotStrategy, ColdStrategy, PairStrategy, TransitionStrategy, BalancedStrategy, RandomStrategy].map((S) => new S());
const byId = Object.fromEntries(STRATEGIES.map((s) => [s.id, s]));

/* ───────── Backtest ───────── */
class Backtester {
  constructor(history) { this.history = history; }
  run(strategy) {
    const { draws, ticketsPerDraw, seed } = CONFIG.backtest;
    const rng = mulberry32(seed);
    const all = this.history.draws, start = all.length - draws;
    let hits = 0, three = 0, best = 0, n = 0;
    for (let i = start; i < all.length; i++) {
      const past = this.history.slice(i), target = new Set(all[i].numbers);
      for (let k = 0; k < ticketsPerDraw; k++) {
        const m = strategy.generate(past, rng).filter((x) => target.has(x)).length;
        hits += m; three += m >= CONFIG.backtest.minHit; best = Math.max(best, m); n++;
      }
    }
    return { avg: hits / n, threeRate: three / n, best, n };
  }
  static expectedAvg() { return (CONFIG.pickCount * CONFIG.pickCount) / CONFIG.maxNumber; }
}

/* ───────── View ───────── */
class App {
  constructor(history) {
    this.history = history;
    this.selected = new Set(CONFIG.defaultStrategies);
    this.count = CONFIG.tickets.initial;
    this.chartWindow = CONFIG.chartWindows[0].size;
    this.rng = Math.random;
  }
  mount() {
    this.renderHeader();
    this.renderStrategies();
    this.bindControls();
    this.renderWindowSeg();
    this.renderChart();
    this.generate();
    requestAnimationFrame(() => this.renderBacktest());
  }
  renderHeader() {
    $("strat-count").textContent = STRATEGIES.length;
    $("odds").textContent = choose(CONFIG.maxNumber, CONFIG.pickCount).toLocaleString();
  }
  renderStrategies() {
    $("strategies").replaceChildren(...STRATEGIES.map((s) => {
      const btn = el("button", { type: "button", class: "strat", id: `strat-${s.id}`, "aria-pressed": String(this.selected.has(s.id)) },
        [el("span", { class: "mark", "aria-hidden": "true" }), el("b", { text: s.name }), el("small", { text: s.desc })]);
      btn.addEventListener("click", () => this.toggle(s.id, btn));
      return btn;
    }));
  }
  toggle(id, btn) {
    if (this.selected.has(id) && this.selected.size === 1) return;
    this.selected.has(id) ? this.selected.delete(id) : this.selected.add(id);
    btn.setAttribute("aria-pressed", String(this.selected.has(id)));
  }
  bindControls() {
    const { min, max } = CONFIG.tickets;
    const setCount = (v) => { this.count = Math.max(min, Math.min(max, v)); $("count").textContent = this.count; };
    setCount(this.count);
    $("dec").addEventListener("click", () => setCount(this.count - 1));
    $("inc").addEventListener("click", () => setCount(this.count + 1));
    $("go").addEventListener("click", () => this.generate());
    Share.bind($("share-result"), () => ({ text: `${document.title.split(" | ").pop()}에서 뽑은 로또 번호\n${ticketLines(this.last)}`, url: Share.pageUrl("") }));
  }
  generate() {
    const ids = [...this.selected];
    const filter = $("balance").checked ? new BalanceFilter(this.history) : null;
    const tickets = Array.from({ length: this.count }, (_, i) => {
      const s = byId[ids[i % ids.length]];
      const t = s.generate(this.history, this.rng, filter);
      return { values: t, note: s.name, nodes: t.map((n) => [ball(n), n]), why: el("p", { class: "why pending", text: `${s.name} · ${s.explain(this.history, t)}` }) };
    });
    this.last = tickets;
    $("tickets").replaceChildren(...tickets.map(({ nodes, why }, i) => el("div", { class: "ticket" }, [
      el("span", { class: "slot", text: String.fromCharCode(65 + i) }),
      el("div", { class: "balls" }, nodes.map(([node]) => node)),
      why,
    ])));
    BallReel.spinAll(tickets.map((x) => x.nodes), $("go")).then(() => tickets.forEach((x) => x.why.classList.remove("pending")));
  }
  renderWindowSeg() {
    renderSeg("window-seg", CONFIG.chartWindows, (w) => w.size === this.chartWindow,
      (w) => { this.chartWindow = w.size; this.renderChart(); });
  }
  renderChart() {
    const f = this.history.frequency(this.chartWindow);
    const W = 900, H = 260, pad = { l: 36, r: 8, t: 12, b: 26 };
    const max = Math.max(...NUMBERS.map((n) => f[n]));
    const hot = new Set([...NUMBERS].sort((a, b) => f[b] - f[a]).slice(0, CONFIG.pickCount));
    $("legend-text").textContent = `가장 많이 나온 ${CONFIG.pickCount}개: ${[...hot].sort((a, b) => a - b).join(", ")}`;
    const step = niceStep(max, CONFIG.chartTicks);
    const top = Math.ceil(max / step) * step;
    const ticks = Array.from({ length: top / step + 1 }, (_, i) => i * step);
    const y = (v) => pad.t + (H - pad.t - pad.b) * (1 - v / top);
    const bw = (W - pad.l - pad.r) / CONFIG.maxNumber;
    const ns = "http://www.w3.org/2000/svg";
    const s = (tag, a, text) => { const n = document.createElementNS(ns, tag); Object.entries(a).forEach(([k, v]) => n.setAttribute(k, v)); if (text != null) n.textContent = text; return n; };
    const svg = $("freq-chart");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.replaceChildren(
      ...ticks.flatMap((t) => [s("line", { class: "grid", x1: pad.l, x2: W - pad.r, y1: y(t), y2: y(t) }), s("text", { x: pad.l - 6, y: y(t) + 3, "text-anchor": "end" }, t)]),
      ...NUMBERS.flatMap((n) => {
        const x = pad.l + (n - 1) * bw;
        const bar = s("rect", { x: x + bw * 0.15, width: bw * 0.7, y: y(f[n]), height: y(0) - y(f[n]), rx: 3, class: hot.has(n) ? "bar-fill top" : "bar-fill" });
        bar.append(s("title", {}, `${n}번: ${f[n]}회`));
        return [bar, s("text", { x: x + bw / 2, y: H - 8, "text-anchor": "middle" }, n)];
      }),
    );
  }
  renderBacktest() {
    const { draws, ticketsPerDraw } = CONFIG.backtest;
    const last = this.history.last.no;
    $("bt-label").textContent = `${last - draws + 1}회 ~ ${last}회`;
    $("bt-desc").textContent = `최근 ${draws}회차마다, 그 회차 이전 데이터만 가지고 알고리즘별로 ${ticketsPerDraw}게임씩 뽑아 실제 당첨번호와 비교했어요. 무작위로 찍었을 때 기대 적중 개수는 게임당 ${fmt(Backtester.expectedAvg())}개예요.`;
    const tester = new Backtester(this.history);
    const results = STRATEGIES.map((s) => ({ s, ...tester.run(s) })).sort((a, b) => b.avg - a.avg);
    const maxAvg = Math.max(...results.map((r) => r.avg), Backtester.expectedAvg());
    const row = (cells) => el("tr", {}, cells);
    const bar = (v, cls = "") => el("div", { class: `bar ${cls}`.trim(), style: `width:${(v / maxAvg) * 100}%` });
    $("bt-table").replaceChildren(
      el("thead", {}, row([el("th", { text: "알고리즘" }), el("th", { class: "num", text: "평균 적중" }), el("th", { text: "" }), el("th", { class: "num", text: `${CONFIG.backtest.minHit}개+ 적중률` }), el("th", { class: "num", text: "최고 적중" })])),
      el("tbody", {}, [
        ...results.map((r) => row([el("td", { text: r.s.name }), el("td", { class: "num", text: fmt(r.avg) }), el("td", { style: "width:35%" }, bar(r.avg)), el("td", { class: "num", text: `${fmt(r.threeRate * 100, 1)}%` }), el("td", { class: "num", text: `${r.best}개` })])),
        row([el("td", { text: "이론 기대값" }), el("td", { class: "num", text: fmt(Backtester.expectedAvg()) }), el("td", {}, bar(Backtester.expectedAvg(), "base")), el("td", { class: "num", text: `${fmt(matchProbability(CONFIG.backtest.minHit) * 100, 1)}%` }), el("td", { text: "" })]),
      ]),
    );
  }
}

new App(new LottoHistory(readJson("draws-data"))).mount();
