/* Shared by every page: site config, DOM helpers, ball rendering, reel animation, theme toggle, ads. */
const SITE = Object.freeze({
  maxNumber: 45,
  pickCount: 6,
  ballGroups: [10, 20, 30, 40, 45],             // upper bound of each official colour band
  themes: [{ label: "시스템", value: "system" }, { label: "라이트", value: "light" }, { label: "다크", value: "dark" }],
  roll: { baseMs: 900, perBallMs: 150, perTicketMs: 120, baseCells: 14, cellsPerBall: 3,
    easing: "cubic-bezier(.12, .8, .22, 1.04)", blurPx: 1.2, sharpAt: 0.55 },
  /* Fill in the IDs, then rebuild. Open any page with #ad-preview to see the slots. */
  ads: {
    provider: "coupang",                     // "coupang" | "adsense" | "" (off)
    adsenseClient: "",                       // "ca-pub-…"
    coupang: {
      trackingCode: "AF1710075",             // "AF…" from Coupang Partners
      template: "carousel",
      sizes: { mobile: { width: 320, height: 100 }, desktop: { width: 680, height: 140 } },
      widgetUrl: "https://ads-partners.coupang.com/widgets.html",
      disclosure: "이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.",
    },
    previewHash: "#ad-preview",
    sizes: { mobile: { width: 320, height: 100 }, desktop: { width: 728, height: 90 }, breakpoint: 760 },
    slots: { default: { coupangId: "1046130", adsenseSlot: "" } },   // per-slot overrides go here by data-slot name
  },
});

/* ───────── Utilities ───────── */
const NUMBERS = Array.from({ length: SITE.maxNumber }, (_, i) => i + 1);
const $ = (id) => document.getElementById(id);
const el = (tag, attrs = {}, children = []) => {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([k, v]) => k === "text" ? (node.textContent = v) : node.setAttribute(k, v));
  [].concat(children).forEach((c) => node.append(c));
  return node;
};
const fmt = (n, d = 2) => n.toFixed(d);
const won = (n) => `${Math.round(n).toLocaleString("ko-KR")}원`;
const readJson = (id) => JSON.parse($(id).textContent);
const choose = (n, k) => (k < 0 || k > n ? 0 : Array.from({ length: k }, (_, i) => (n - i) / (i + 1)).reduce((a, b) => a * b, 1));
const randomOf = (pool) => pool[Math.floor(Math.random() * pool.length)];

/* ───────── Balls ───────── */
const groupIndex = (n) => SITE.ballGroups.findIndex((max) => n <= max) + 1;
const ball = (n, color = `var(--ball-${groupIndex(n)})`) => el("span", { class: "ball", style: `--c: ${color}`, text: String(n) });

/** Slot-reel animation: digits scroll vertically inside a blank ball and land on the result. */
class BallReel {
  static get reduced() { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; }
  static cell(n) { return el("span", { class: "cell", text: String(n) }); }

  /** Rolls `node` (a .ball) through random values from `pool`, ending on `finalValue`. Resolves when it lands. */
  static spin(node, finalValue, ticketIndex, ballIndex, pool = NUMBERS) {
    if (BallReel.reduced) return Promise.resolve();
    const { baseMs, perBallMs, perTicketMs, baseCells, cellsPerBall, easing, blurPx, sharpAt } = SITE.roll;
    const count = baseCells + ballIndex * cellsPerBall;
    const values = [...Array.from({ length: count }, () => randomOf(pool)), finalValue];
    const strip = el("span", { class: "strip" }, values.map(BallReel.cell));
    node.classList.add("reel");
    node.replaceChildren(strip);
    const travel = `translateY(-${(count / values.length) * 100}%)`;
    const duration = baseMs + ballIndex * perBallMs + ticketIndex * perTicketMs;
    const frames = [
      { transform: "translateY(0)", filter: `blur(${blurPx}px)` },
      { offset: sharpAt, filter: "blur(0)" },
      { transform: travel, filter: "blur(0)" },
    ];
    return strip.animate(frames, { duration, easing, fill: "forwards" }).finished.then(() => {
      node.classList.remove("reel");
      node.replaceChildren(String(finalValue));
      node.classList.add("settled");
    });
  }

  /** Spins every ball in `rows` (arrays of [node, value]); disables `button` until all land. */
  static spinAll(rows, button, pool) {
    const done = rows.flatMap((row, i) => row.map(([node, value], j) => BallReel.spin(node, value, i, j, pool)));
    if (button) {
      button.disabled = true;
      Promise.all(done).then(() => (button.disabled = false));
    }
    return Promise.all(done);
  }
}

/** Renders a segmented control; `onSelect` runs with the chosen option, then the control re-renders. */
function renderSeg(containerId, options, isActive, onSelect) {
  const container = $(containerId);
  if (!container) return;
  const render = () => container.replaceChildren(...options.map((o, i) => {
    const b = el("button", { type: "button", id: `${containerId}-${i}`, "aria-pressed": String(isActive(o)), text: o.label });
    b.addEventListener("click", () => { onSelect(o); render(); });
    return b;
  }));
  render();
}

/* ───────── Theme (system / light / dark), remembered per browser ───────── */
class ThemeStore {
  static key = document.querySelector('meta[name="theme-storage-key"]').content;
  static get current() { return document.documentElement.dataset.theme || SITE.themes[0].value; }
  static read() { try { return localStorage.getItem(ThemeStore.key); } catch { return null; } }
  static apply(value) {
    const root = document.documentElement;
    value === SITE.themes[0].value ? delete root.dataset.theme : (root.dataset.theme = value);
    try { localStorage.setItem(ThemeStore.key, value); } catch { /* storage blocked: theme still applies for this visit */ }
  }
  static restore() {
    const saved = ThemeStore.read();
    if (SITE.themes.some((t) => t.value === saved)) ThemeStore.apply(saved);
  }
  static mountToggle(containerId) {
    renderSeg(containerId, SITE.themes, (t) => t.value === ThemeStore.current, (t) => ThemeStore.apply(t.value));
  }
}

/* ───────── Ads: one renderer per network, chosen by SITE.ads.provider ───────── */
class AdNetwork {
  static scripts = new Set();
  static loadScript(src, attrs = {}) {
    if (AdNetwork.scripts.has(src)) return;
    AdNetwork.scripts.add(src);
    document.head.append(el("script", { src, async: "", ...attrs }));
  }
  constructor(size) { this.size = size; }
  render(_container, _slot) { return false; }
}
class Coupang extends AdNetwork {
  render(container, slot) {
    const { trackingCode, template, widgetUrl, disclosure } = SITE.ads.coupang;
    if (!trackingCode || !slot.coupangId) return false;
    const { width, height } = this.size;
    const params = new URLSearchParams({ id: slot.coupangId, template, trackingCode, subId: "", width, height, tsource: "" });
    container.append(
      el("iframe", { src: `${widgetUrl}?${params}`, width: String(width), height: String(height), class: "ad-frame",
        title: "쿠팡 추천 상품", loading: "lazy", frameborder: "0", scrolling: "no", referrerpolicy: "unsafe-url" }),
      el("p", { class: "ad-disclosure", text: disclosure }),
    );
    return true;
  }
}
class AdSense extends AdNetwork {
  render(container, slot) {
    const client = SITE.ads.adsenseClient;
    if (!client || !slot.adsenseSlot) return false;
    AdNetwork.loadScript(`https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${client}`, { crossorigin: "anonymous" });
    container.append(el("ins", { class: "adsbygoogle", style: "display:block", "data-ad-client": client,
      "data-ad-slot": slot.adsenseSlot, "data-ad-format": "auto", "data-full-width-responsive": "true" }));
    (window.adsbygoogle = window.adsbygoogle || []).push({});
    return true;
  }
}
class AdPreview extends AdNetwork {
  render(container) {
    const { width, height } = this.size;
    container.append(el("div", { class: "ad-preview", style: `--ad-w:${width}px; --ad-h:${height}px`, text: `광고 자리 ${width}×${height}` }));
    return true;
  }
}
class AdManager {
  static NETWORKS = { coupang: Coupang, adsense: AdSense };
  /** A network may override the default slot sizes (e.g. SITE.ads.coupang.sizes). */
  static size(provider) {
    const { breakpoint } = SITE.ads.sizes;
    const { mobile, desktop } = SITE.ads[provider]?.sizes ?? SITE.ads.sizes;
    const isMobile = window.innerWidth < breakpoint;
    return { ...(isMobile ? mobile : desktop), isMobile };
  }
  static mount() {
    const preview = location.hash === SITE.ads.previewHash;
    const Network = preview ? AdPreview : AdManager.NETWORKS[SITE.ads.provider];
    if (!Network) return;
    const network = new Network(AdManager.size(SITE.ads.provider));
    document.querySelectorAll(".ad-slot").forEach((container) => {
      const slot = SITE.ads.slots[container.dataset.slot] ?? SITE.ads.slots.default;
      container.hidden = !network.render(container, slot);
    });
  }
}

ThemeStore.restore();
ThemeStore.mountToggle("theme-seg");
AdManager.mount();

/* ───────── Prize tax (rules in src/rules.json, mirrored by scripts/build.py for static pages) ───────── */
const RULES = readJson("rules");
class Tax {
  static rules = RULES.tax;
  /** Splits a prize into taxable brackets. Prizes at or under the tax-free limit pay nothing. */
  static compute(prize, { deductTicket = true } = {}) {
    const { ticketPrice, taxFreeLimit, brackets } = Tax.rules;
    if (prize <= taxFreeLimit) return { prize, taxable: 0, tax: 0, net: prize, parts: [] };
    const taxable = Math.max(0, prize - (deductTicket ? ticketPrice : 0));
    let floor = 0;
    const parts = brackets.map(({ upTo, rate, range }) => {
      const base = Math.max(0, Math.min(taxable, upTo ?? Infinity) - floor);
      floor = upTo ?? floor;
      return { range, rate, base, tax: Math.floor(base * rate) };
    }).filter((p) => p.base > 0);
    const tax = parts.reduce((s, p) => s + p.tax, 0);
    return { prize, taxable, tax, net: prize - tax, parts };
  }
}
