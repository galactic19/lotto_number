/* Pension lottery 720+ generator: one group plus RULES.pension.digits random digits, rolled on the shared reel. */
const PENSION = Object.freeze({
  ...RULES.pension,
  tickets: { min: 1, max: 5, initial: 1 },
  digitPool: Array.from({ length: 10 }, (_, i) => i),
  groupColor: "var(--accent)",
  digitColor: (i) => `var(--ball-${(i % SITE.ballGroups.length) + 1})`,
});

class PensionPage {
  constructor() {
    this.count = PENSION.tickets.initial;
    const { min, max } = PENSION.tickets;
    const setCount = (v) => { this.count = Math.max(min, Math.min(max, v)); $("count").textContent = this.count; };
    setCount(this.count);
    $("dec").addEventListener("click", () => setCount(this.count - 1));
    $("inc").addEventListener("click", () => setCount(this.count + 1));
    $("go").addEventListener("click", () => this.generate());
    this.generate();
  }
  static digits() { return Array.from({ length: PENSION.digits }, () => randomOf(PENSION.digitPool)); }
  static groups() { return Array.from({ length: PENSION.groups }, (_, i) => i + 1); }
  /** One ticket per game, or the same digits across every group when "all groups" is on. */
  tickets() {
    return Array.from({ length: this.count }, () => {
      const digits = PensionPage.digits();
      const groups = $("all-groups").checked ? PensionPage.groups() : [randomOf(PensionPage.groups())];
      return groups.map((group) => ({ group, digits }));
    }).flat();
  }
  generate() {
    const rows = this.tickets().map(({ group, digits }) => ({
      group: [ball(group, PENSION.groupColor), group],
      digits: digits.map((d, i) => [ball(d, PENSION.digitColor(i)), d]),
    }));
    $("tickets").replaceChildren(...rows.map((r, i) => el("div", { class: "ticket" }, [
      el("span", { class: "slot", text: String.fromCharCode(65 + i) }),
      el("div", { class: "balls" }, [r.group[0], el("span", { class: "plus", text: "조" }), ...r.digits.map(([node]) => node)]),
    ])));
    BallReel.spinAll(rows.map((r) => r.digits), $("go"), PENSION.digitPool);
  }
}
new PensionPage();
