// Deep Dives (C in the nav): one club read in full, each in its own colours. FC Barcelona is live, in blaugrana
// (vivid: blau, grana and the senyera's gold); Paris Saint-Germain comes next, in its own darker register (night navy,
// the Hechter red band). The Barça dive reuses the club page (club.js) and dresses it: a striped hero instead of the
// plain head, and its tokens repainted under main[data-dive="barca"] (style.css). Crimson stays Promesse's own call.

(() => {   // a scope of its own, like scoreboard.js
const DIVES = [
  { slug: "barcelona", club: "FC Barcelona", theme: "barca", state: "live",
    line: "The system first, then who fits it, then the pathway that feeds it.",
    facts: ["Flick's game model against Xavi's", "La Masia's pathway and its share of minutes", "Who fits the roles he asks for"] },
  { slug: "psg", club: "Paris Saint-Germain", theme: "psg", state: "next",
    line: "How Paris play today, and how France develops its young players.",
    facts: ["A data inventory first", "The game model, season by season", "Île-de-France's academies"] },
];

async function divesIndex() {
  return () => {
    setNav("dives");
    main.innerHTML = `<div class="page-head"><div><h1>Deep Dives</h1>
      <p class="lead">One club read in full: how it plays, who fits, and the pathway that feeds it. Each in its own colours.</p></div></div>
      <div class="dives">${DIVES.map((d) => `<a class="dive-card t-${d.theme}${d.state === "live" ? "" : " soon"}" ${d.state === "live" ? `href="#/dive/${d.slug}"` : 'aria-disabled="true"'}>
        <span class="dive-stripes" aria-hidden="true"></span>
        <span class="dive-state">${d.state === "live" ? "Live" : "In preparation"}</span>
        <h2>${esc(d.club)}</h2><p>${esc(d.line)}</p>
        <ul>${d.facts.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>
        ${d.state === "live" ? `<span class="dive-go">Open the dive${icon("right")}</span>` : ""}</a>`).join("")}</div>`;
    if (motion()) gsap.from(".dive-card", { y: 26, opacity: 0, duration: 0.7, ease: "expo.out", stagger: 0.12 });
  };
}

async function divePage(slug) {
  const d = DIVES.find((x) => x.slug === slug);
  if (!d || d.state !== "live" || !window.clubPage) return divesIndex();
  const paint = await window.clubPage(slug);
  return () => {
    const enter = paint();                                  // the club page's own entrance, run after the swap
    setNav("dive");
    main.dataset.dive = d.theme;
    // the plain head becomes the hero: the club's stripes, its name, the dive's line
    const head = $(".clubhead", main), back = $(".back", main);
    if (back) { back.href = "#/dives"; back.innerHTML = `${icon("left")}Deep Dives`; }
    if (head) head.outerHTML = `<header class="dive-hero t-${d.theme}"><span class="dive-stripes" aria-hidden="true"></span>
      <div class="dive-hero-in"><span class="dive-state">Deep dive</span><h1 class="display">${esc(d.club)}</h1>
      <p class="lead">${$(".lead", head)?.innerHTML || esc(d.line)}</p></div></header>`;
    if (motion()) {
      gsap.from(".dive-hero h1", { y: 30, opacity: 0, duration: 0.9, ease: "expo.out" });
      gsap.from(".dive-hero .lead, .dive-hero .dive-state", { y: 14, opacity: 0, duration: 0.7, ease: "expo.out", delay: 0.15, stagger: 0.08 });
      gsap.from(".dive-hero .dive-stripes", { scaleX: 0.6, opacity: 0, transformOrigin: "right center", duration: 1.2, ease: "expo.out" });
    }
    return enter;
  };
}

window.divesIndex = divesIndex;
window.divePage = divePage;
})();
