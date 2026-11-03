/* My-numbers checker: replays a fixed ticket against every draw using the rank rules in RULES.ranks. */
const CHECK = Object.freeze({ param: "numbers", hitRanks: 4, drawPath: (no) => `../draws/${no}/` });

class TicketChecker {
  constructor(draws) { this.draws = draws; }

  /** Index into RULES.ranks for one draw, or -1 when the ticket wins nothing. */
  static rankOf(ticket, draw) {
    const hits = ticket.filter((n) => draw.numbers.includes(n)).length;
    const bonus = ticket.includes(draw.bonus);
    return RULES.ranks.findIndex((r) => r.match === hits && (!r.bonus || bonus));
  }
  run(ticket) {
    const counts = RULES.ranks.map(() => 0);
    const hits = [];
    let prize = 0;
    this.draws.forEach((d) => {
      const rank = TicketChecker.rankOf(ticket, d);
      if (rank < 0) return;
      counts[rank]++;
      prize += d.prizes[rank] || 0;
      if (rank < CHECK.hitRanks) hits.push({ draw: d, rank });
    });
    const spent = this.draws.length * RULES.tax.ticketPrice;
    return { counts, hits: hits.sort((a, b) => a.rank - b.rank || b.draw.no - a.draw.no), prize, spent };
  }
}

class CheckPage {
  constructor(draws) {
    this.checker = new TicketChecker(draws);
    this.picked = new Set();
    this.buttons = NUMBERS.map((n) => {
      const b = el("button", { type: "button", class: "pick", "aria-pressed": "false", text: String(n), style: `--c: var(--ball-${groupIndex(n)})` });
      b.addEventListener("click", () => this.toggle(n));
      return b;
    });
    $("picker").replaceChildren(...this.buttons);
    $("random").addEventListener("click", () => this.set([...NUMBERS].sort(() => Math.random() - 0.5).slice(0, SITE.pickCount)));
    $("clear").addEventListener("click", () => this.set([]));
    $("check").addEventListener("click", () => this.check());
    $("share").addEventListener("click", () => this.share());
    const fromUrl = (new URLSearchParams(location.search).get(CHECK.param) || "").split(",").map(Number).filter((n) => NUMBERS.includes(n));
    this.set(fromUrl);
    if (this.ready) this.check();
  }
  get ready() { return this.picked.size === SITE.pickCount; }
  get ticket() { return [...this.picked].sort((a, b) => a - b); }
  set(numbers) {
    this.picked = new Set(numbers.slice(0, SITE.pickCount));
    this.sync();
  }
  toggle(n) {
    if (this.picked.has(n)) this.picked.delete(n);
    else if (!this.ready) this.picked.add(n);
    this.sync();
  }
  sync() {
    this.buttons.forEach((b, i) => b.setAttribute("aria-pressed", String(this.picked.has(NUMBERS[i]))));
    $("pick-count").textContent = `${this.picked.size} / ${SITE.pickCount}개 선택`;
    $("check").disabled = !this.ready;
  }
  check() {
    const ticket = this.ticket;
    const r = this.checker.run(ticket);
    history.replaceState(null, "", `?${CHECK.param}=${ticket.join(",")}`);
    $("result").hidden = false;
    $("result-balls").replaceChildren(...ticket.map((n) => ball(n)));
    const wins = r.counts.reduce((a, b) => a + b, 0);
    const profit = r.prize - r.spent;
    $("result-stats").replaceChildren(
      ...[["당첨 횟수", `${wins.toLocaleString()}회`], ["쓴 돈", won(r.spent)], ["받은 당첨금", won(r.prize)], [profit >= 0 ? "수익" : "손실", won(Math.abs(profit))]]
        .map(([label, value], i) => el("div", { class: `stat${i === 2 ? " accent" : ""}` }, [el("span", { text: label }), el("b", { text: value })])),
    );
    const row = (cells, tag = "td") => el("tr", {}, cells.map(([content, cls]) => el(tag, { class: cls || "" }, content)));
    $("rank-table").replaceChildren(
      el("thead", {}, row([["등수"], ["조건"], ["횟수", "num"]], "th")),
      el("tbody", {}, RULES.ranks.map((rank, i) => row([[rank.name], [rank.rule], [`${r.counts[i]}회`, "num"]]))),
    );
    const link = (no) => el("a", { class: "link", href: CHECK.drawPath(no), text: `${no}회` });
    $("hit-table").replaceChildren(
      el("thead", {}, row([["회차"], ["등수"], ["당첨번호"], ["당첨금", "num"]], "th")),
      el("tbody", {}, r.hits.length
        ? r.hits.map(({ draw, rank }) => row([[link(draw.no)], [RULES.ranks[rank].name], [el("div", { class: "balls" }, draw.numbers.map((n) => ball(n)))], [won(draw.prizes[rank] || 0), "num"]]))
        : [row([[`${RULES.ranks[CHECK.hitRanks - 1].name} 이상 당첨은 없었어요.`]])]),
    );
    $("result").scrollIntoView({ behavior: BallReel.reduced ? "auto" : "smooth", block: "start" });
  }
  share() {
    const status = $("share-status");
    navigator.clipboard.writeText(location.href)
      .then(() => (status.textContent = "링크를 복사했어요."))
      .catch(() => (status.textContent = location.href));
  }
}

new CheckPage(readJson("draws-data"));
