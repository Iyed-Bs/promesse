// Interaction patterns: the small set of components every page uses where a block of words sat
// before. Each one owns its spacing (tokens --sp-1 to --sp-8 in style.css), so a sentence cannot land on another one.
//   UI.flip({...})     a card with two faces, a button (aria-pressed); front = the question / name / status, back = the proof
//   UI.stepper({...})  one idea per slide: previous/next, dots, arrow keys, swipe (scroll-snap on phones)
//   UI.more(short,long) the one-line answer, the detail on demand (a native <details>)
//   UI.fit(svg)        SVG labels measured and placed: wrapped, flipped to the other side, and the viewBox grown so none is cut
//   reveals            sections and cards arrive with a short stagger (nothing waits to be revealed with reduced motion)
// All event handling is delegated from document, so a page only has to print the markup; the MutationObserver at the bottom
// runs fit() and arms the reveals every time a page paints into <main>.
// Uses app.js's esc() and the CSS in style.css, section "Interaction patterns".
(() => {
  const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const PHONE = matchMedia("(max-width: 760px)");   // slides scroll-snap here; stacked, with arrows, on wider screens
  const e = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ── flip card ───────────────────────────────────────────────────────────────────────────────────────────────────
  // front / back are HTML (phrasing content: spans, b, i, no links). Both faces stay in the page for a screen reader; the
  // visible one is chosen by CSS from aria-pressed. hint = the small line at the foot of each face. state = a class for colour.
  function flip({ front, back, frontHint = "Turn over", backHint = "Turn back", state = "", cls = "", label = "" }) {
    return `<div class="flip ${state} ${cls}" data-reveal><button type="button" class="flip-btn" aria-pressed="false"${label ? ` aria-label="${e(label)}"` : ""}>
      <span class="flip-in"><span class="flip-face flip-front">${front}<span class="flip-hint" aria-hidden="true">${e(frontHint)}</span></span>
      <span class="flip-face flip-back">${back}<span class="flip-hint" aria-hidden="true">${e(backHint)}</span></span></span></button></div>`;
  }

  // ── stepper ─────────────────────────────────────────────────────────────────────────────────────────────────────
  // slides: [{ title, html, small }]; title feeds the dots' names. Fires a bubbling "step" event ({ detail: { i, n } }) so a page
  // can light up what the slide is about (the chart's point, the board's column).
  let stepN = 0;
  function stepper({ label, slides, start = 0, cls = "" }) {
    const id = `step-${++stepN}`;
    return `<section class="stepper ${cls}" id="${id}" data-i="${start}" data-n="${slides.length}" role="group" aria-roledescription="carousel" aria-label="${e(label)}">
      <div class="step-bar">
        <p class="step-count" aria-live="polite"><b>${start + 1}</b> of ${slides.length}<span class="step-title"> · ${e(slides[start].title)}</span></p>
        <div class="step-dots" role="group" aria-label="Go to a step">${slides.map((s, i) => `<button type="button" class="step-dot" data-go="${i}" aria-label="${e(`${i + 1} of ${slides.length}: ${s.title}`)}"${i === start ? ' aria-current="step"' : ""}><i></i></button>`).join("")}</div>
        <div class="step-nav"><button type="button" class="step-btn step-prev" aria-label="Previous: ${e(label)}"><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-left"/></svg></button>
          <button type="button" class="step-btn step-next" aria-label="Next: ${e(label)}"><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-right"/></svg></button></div>
      </div>
      <div class="step-track">${slides.map((s, i) => `<article class="step-slide${s.small ? " small" : ""}" data-s="${i}" role="group" aria-roledescription="slide" aria-label="${i + 1} of ${slides.length}"${i === start ? ' data-on=""' : ""}>${s.html}</article>`).join("")}</div>
    </section>`;
  }
  const slidesOf = (st) => [...st.querySelectorAll(":scope > .step-track > .step-slide")];
  function go(st, i, { fromScroll = false, focus = false } = {}) {
    const n = +st.dataset.n; i = Math.max(0, Math.min(n - 1, i));
    const slides = slidesOf(st), was = +st.dataset.i;
    st.dataset.i = i;
    slides.forEach((s, k) => { if (k === i) s.setAttribute("data-on", ""); else s.removeAttribute("data-on"); });
    st.querySelectorAll(".step-dot").forEach((d, k) => { if (k === i) d.setAttribute("aria-current", "step"); else d.removeAttribute("aria-current"); });
    st.querySelector(".step-count").innerHTML = `<b>${i + 1}</b> of ${n}<span class="step-title"> · ${e(st.querySelector(`.step-dot:nth-child(${i + 1})`).getAttribute("aria-label").replace(/^\d+ of \d+: /, ""))}</span>`;
    // aria-disabled, not disabled: a disabled button would drop the keyboard focus that is steering the slides
    st.querySelector(".step-prev").setAttribute("aria-disabled", String(i === 0)); st.querySelector(".step-next").setAttribute("aria-disabled", String(i === n - 1));
    if (PHONE.matches && !fromScroll) { const tr = st.querySelector(".step-track"); tr.scrollTo({ left: slides[i].offsetLeft, behavior: REDUCED ? "auto" : "smooth" }); }
    if (!PHONE.matches && !REDUCED && window.gsap && i !== was) gsap.fromTo(slides[i], { x: i > was ? 24 : -24 }, { x: 0, duration: 0.45, ease: "expo.out", clearProps: "transform" });
    if (focus) st.querySelector(".step-dot[aria-current]")?.focus();
    st.dispatchEvent(new CustomEvent("step", { bubbles: true, detail: { i, n } }));
  }
  function initSteppers(scope) {
    scope.querySelectorAll(".stepper:not([data-ready])").forEach((st) => {
      st.dataset.ready = "1";
      go(st, +st.dataset.i, { fromScroll: true });
      const tr = st.querySelector(".step-track");
      // phone: the track scrolls and snaps; the slide nearest the left edge is the current one
      let t; tr.addEventListener("scroll", () => { if (!PHONE.matches) return; clearTimeout(t);
        t = setTimeout(() => { const w = tr.clientWidth || 1, i = Math.round(tr.scrollLeft / w); if (i !== +st.dataset.i) go(st, i, { fromScroll: true }); }, 90); }, { passive: true });
      // wider screens: a horizontal swipe or drag also steps
      let x0 = null, y0 = 0; tr.addEventListener("pointerdown", (ev) => { if (PHONE.matches || ev.pointerType === "mouse") return; x0 = ev.clientX; y0 = ev.clientY; });
      tr.addEventListener("pointerup", (ev) => { if (x0 == null) return; const dx = ev.clientX - x0, dy = ev.clientY - y0; x0 = null;
        if (Math.abs(dx) > 48 && Math.abs(dx) > 1.5 * Math.abs(dy)) go(st, +st.dataset.i + (dx < 0 ? 1 : -1)); });
    });
  }

  // ── delegated events ────────────────────────────────────────────────────────────────────────────────────────────
  document.addEventListener("click", (ev) => {
    const fb = ev.target.closest(".flip-btn");
    if (fb) { const on = fb.getAttribute("aria-pressed") !== "true"; fb.setAttribute("aria-pressed", String(on)); return; }
    const st = ev.target.closest(".stepper"); if (!st) return;
    const dot = ev.target.closest(".step-dot"), prev = ev.target.closest(".step-prev"), next = ev.target.closest(".step-next");
    if ((prev || next)?.getAttribute("aria-disabled") === "true") return;
    if (dot) go(st, +dot.dataset.go); else if (prev) go(st, +st.dataset.i - 1); else if (next) go(st, +st.dataset.i + 1);
  });
  document.addEventListener("keydown", (ev) => {
    const st = ev.target.closest?.(".stepper"); if (!st || ev.altKey || ev.ctrlKey || ev.metaKey) return;
    const i = +st.dataset.i, n = +st.dataset.n;
    const to = { ArrowRight: i + 1, ArrowDown: null, ArrowLeft: i - 1, Home: 0, End: n - 1 }[ev.key];
    if (to == null) return;
    ev.preventDefault(); go(st, to, { focus: ev.target.matches(".step-dot") });
  });

  // ── short first ─────────────────────────────────────────────────────────────────────────────────────────────────
  const more = (short, long, label = "More") => `<div class="more"><p class="more-short">${short}</p><details class="more-d"><summary>${e(label)}</summary><div class="more-body">${long}</div></details></div>`;

  // ── SVG labels: measured and placed ─────────────────────────────────────────────────────────────────────────────
  // data-wrap="W" on a <text>: re-set as lines of at most W user units (tspans, 1.15 line height).
  // data-flip on a <text> with an x anchor: when it runs past the viewBox on the right it moves to the left of its anchor.
  // After both, the viewBox grows to hold every label (never shrinks), so no label is cut by the chart's own edge.
  function wrapText(t, maxW) {
    const x = t.getAttribute("x"), words = t.textContent.trim().split(/\s+/), size = parseFloat(getComputedStyle(t).fontSize) || 14;
    t.textContent = ""; let line = null, lines = [];
    const fresh = () => { const s = document.createElementNS("http://www.w3.org/2000/svg", "tspan"); s.setAttribute("x", x); t.appendChild(s); return s; };
    words.forEach((w) => { if (!line) { line = fresh(); line.textContent = w; lines.push(line); return; }
      const keep = line.textContent; line.textContent = keep + " " + w;
      if (line.getComputedTextLength() > maxW) { line.textContent = keep; line = fresh(); line.textContent = w; lines.push(line); } });
    // centre the block on the original baseline's row
    lines.forEach((s, k) => s.setAttribute("dy", k === 0 ? `${(-(lines.length - 1) * 0.575).toFixed(3)}em` : "1.15em"));
    return size;
  }
  function fit(svg) {
    if (svg.dataset.fitted) return; svg.dataset.fitted = "1";
    svg.querySelectorAll("text[data-wrap]").forEach((t) => wrapText(t, +t.dataset.wrap));
    const vb = svg.viewBox.baseVal; if (!vb || !vb.width) return;
    svg.querySelectorAll("text[data-flip]").forEach((t) => { const b = t.getBBox();
      if (b.x + b.width > vb.x + vb.width - 4) { t.setAttribute("text-anchor", "end"); t.setAttribute("x", +t.getAttribute("x") - 10); } });
    let x0 = vb.x, y0 = vb.y, x1 = vb.x + vb.width, y1 = vb.y + vb.height;
    svg.querySelectorAll("text").forEach((t) => { if (t.closest("[data-nofit]")) return; const b = t.getBBox(); if (!b.width) return;
      x0 = Math.min(x0, b.x - 4); y0 = Math.min(y0, b.y - 4); x1 = Math.max(x1, b.x + b.width + 4); y1 = Math.max(y1, b.y + b.height + 4); });
    if (x0 < vb.x || y0 < vb.y || x1 > vb.x + vb.width || y1 > vb.y + vb.height) svg.setAttribute("viewBox", `${x0} ${y0} ${x1 - x0} ${y1 - y0}`);
  }

  // ── reveals ─────────────────────────────────────────────────────────────────────────────────────────────────────
  let io = null;
  function arm(scope) {
    if (REDUCED || !("IntersectionObserver" in window)) return;
    io = io || new IntersectionObserver((es) => es.forEach((en) => { if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); } }), { rootMargin: "0px 0px -6% 0px", threshold: 0.04 });
    // sections and heads arrive one after another; cards inside a grid arrive with a short stagger (--i counts within the parent)
    scope.querySelectorAll(":scope > .block, :scope > .page-head, :scope > .sb > .block, :scope > .sb > .page-head, :scope > .sb > .sb-now, [data-reveal]").forEach((el) => {
      if (el.dataset.rv) return; el.dataset.rv = "1";
      const sib = el.parentElement ? [...el.parentElement.children].filter((c) => c.matches("[data-reveal], .block, .page-head, .sb-now")).indexOf(el) : 0;
      el.style.setProperty("--i", Math.min(sib, 8)); el.classList.add("rv"); io.observe(el);
    });
    // anything still waiting after a few seconds is shown (a tab opened in the background never intersects)
    setTimeout(() => scope.querySelectorAll(".rv:not(.in)").forEach((el) => { const r = el.getBoundingClientRect(); if (r.top < innerHeight * 1.2) el.classList.add("in"); }), 2500);
  }

  function enhance(scope) {
    scope.querySelectorAll("svg[data-fit]").forEach(fit);
    initSteppers(scope); arm(scope);
  }
  const m = document.getElementById("main");
  if (m) new MutationObserver(() => { requestAnimationFrame(() => enhance(m)); }).observe(m, { childList: true });

  window.UI = { flip, stepper, more, fit, go, enhance };
})();
