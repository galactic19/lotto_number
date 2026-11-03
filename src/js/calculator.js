/* Prize calculator: tax rules come from RULES.tax via the shared Tax helper. ?amount= reopens a shared result. */
const CALC = Object.freeze({ param: "amount" });

class Calculator {
  constructor() {
    this.input = $("amount");
    const shared = Number(new URLSearchParams(location.search).get(CALC.param));
    if (shared > 0) this.input.value = shared.toLocaleString("ko-KR");
    Share.bind($("share-result"), () => {
      const r = Tax.compute(this.amount);
      return { text: `로또 당첨금 ${won(r.prize)}의 실수령액은 ${won(r.net)} (세금 ${won(r.tax)})`, url: Share.pageUrl(`?${CALC.param}=${r.prize}`) };
    });
    this.input.addEventListener("input", () => this.update());
    $("presets").addEventListener("click", (e) => {
      const value = e.target.closest("[data-value]")?.dataset.value;
      if (value) { this.input.value = Number(value).toLocaleString("ko-KR"); this.update(); }
    });
    this.update();
  }
  get amount() { return Number(this.input.value.replace(/[^\d]/g, "")) || 0; }
  update() {
    const r = Tax.compute(this.amount);
    $("out-prize").textContent = won(r.prize);
    $("out-tax").textContent = won(r.tax);
    $("out-net").textContent = won(r.net);
    const row = (cells, tag = "td") => el("tr", {}, cells.map(([text, cls]) => el(tag, { class: cls || "", text })));
    $("breakdown").replaceChildren(
      el("thead", {}, row([["구간"], ["과세 금액", "num"], ["세율", "num"], ["세금", "num"]], "th")),
      el("tbody", {}, r.parts.length
        ? r.parts.map((p) => row([[p.range], [won(p.base), "num"], [`${Math.round(p.rate * 100)}%`, "num"], [won(p.tax), "num"]]))
        : [row([[`${won(Tax.rules.taxFreeLimit)} 이하 비과세`], ["-", "num"], ["0%", "num"], [won(0), "num"]])]),
    );
  }
}
new Calculator();
