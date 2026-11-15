// The stadium (Discover, desktop): 22,522 players as the seats of one European ground, in WebGL.
//
// The idea: a two-tier bowl, ONE considered geometry. LOWER stand "Projections": the bigger, shallower tier near the
// pitch, everyone we project from our standard. UPPER stand "Deep analysis": the smaller, steeper tier set back above it, the
// players we know best (each seat of the lower stand says what data would make his projection more accurate: the seat card,
// app.js). The Attack end is the tall steep "Kop", the Goalkeepers' end the low quiet end, by design, never by head count.
// Each tier is cut into blocks by birth year (looking from the pitch, oldest left, youngest right; the best outlook in the
// front rows of a block), so a sentence about age lights whole sections. Each seat is painted with the seat ramp (level in
// 25/26), the stand's own plastic when no football was seen.
//
// this module no longer draws any stadium of its own. The stands, roof and dressing (pitch, goals, boards, banners,
// flags, signs, the screen) are THE GROUND, the model made in Blender (ground3d.js, served read-only at /ground). Here live
// only what the desk owns: the seats (one per player, laid on the rows the FILE really has: its stand profiles, the Kop's
// steeper rake, the north end's boxes), the sky and far ground, the day/night light (the model says where its lamp banks stand),
// the picking (snaps to the nearest visible seat, 18 px), the camera and its flights, the markers and the scoreboard figures
// on the model's screen. While the file downloads the page shows "Loading the Ground"; if it cannot load, `onFail` tells the
// desk to open Promesse Light (the flat bowl, app.js), which is also what a phone-class device or a visitor's choice gets.
//
// Camera: ONE continuous flight per move, always looking at the pitch: it circles at cruising height (never over the centre spot,
// where a look-at flips), comes in behind the stand, over the roof rim and down the tier's normal into the seat. Seat to seat in
// one stand: a crane move. Parked, the eye settles as you sit and breathes a little. First visit in a browser session: the walk out of
// the tunnel, then up over the stand to the wide view. The camera never crosses geometry: `audit()` replays the flights to many
// seats against the model's light copies, `auditEnter()` the walk-out. The 21 parts of targets.json can be clicked (outline,
// glow, one flight to the part's pose; Esc or "Back to the ground" flies back).
import * as THREE from "/static/vendor/three.module.min.js";

// the four stands. k scales a stand's envelope: 1 for the long sides, 1.2 for the Kop, 0.75 for the quiet end
const STANDS = [
  { pos: "Midfield", side: "E", name: "Midfield", k: 1.0, style: "two_tier" },
  { pos: "Defender", side: "W", name: "Defence", k: 1.0, style: "two_tier" },
  { pos: "Attack", side: "S", name: "Attack", k: 1.2, style: "kop" },
  { pos: "Goalkeeper", side: "N", name: "Goalkeepers", k: 0.75, style: "palcos" },
];
// The Ground's own differences (the-ground/kit/ground.json), used only when its model is in the page: the Kop's tiers are 6
// degrees steeper, the north end's upper tier is a stack of boxes (3 levels, 2 rows each), and the roofs fall 1 in 20
const KOP_EXTRA = 6, FALL = 0.05, PALCOS = { levels: 3, level_height: 3.3, rows_per_level: 2 };
// the two tiers: id is the value of a player's `stand` field; depth is the tier's run in metres, rake its slope
const TIERS = {
  projection: { id: "projection", name: "Projections", depth: 19, rake: 25 },
  deep: { id: "deep", name: "Deep analysis", depth: 12, rake: 33 },
};
const L = 105, W = 68;                                       // the pitch
const RUN = 6;                                               // run-off from the touchline to the first wall
const FRONT = 2.2, LIP = 2.6, HEAD = 3.4, OVER = 4.5;       // parapet height, upper tier's front lip, headroom under the overhang, how far the upper tier overhangs
const COVER = 0.45;                                          // the roof covers the back 45 % of the upper tier
const SEAT_H = 0.92;                                         // seat height to the top of the backrest; its footprint is fitted per stand
const SIDE = { E: { len: L + 2 * RUN, rot: Math.PI / 2 }, W: { len: L + 2 * RUN, rot: -Math.PI / 2 }, S: { len: W + 2 * RUN, rot: 0 }, N: { len: W + 2 * RUN, rot: Math.PI } };
const IN = { E: [0, 0, 1], W: [0, 0, -1], S: [-1, 0, 0], N: [1, 0, 0] };    // the direction from a stand toward the pitch
const rad = (d) => (d * Math.PI) / 180;
const SNAP = 18;                                             // px: a click this close to a seat takes it
const AISLE = 1.0;                                           // m: the stairs between two blocks
// a seat's block: one per birth year, the oldest and the youngest years pooled (the bounds)
const BLOCK_LO = 1992, BLOCK_HI = 2008;
const blockOf = (born) => Math.min(BLOCK_HI, Math.max(BLOCK_LO, born || BLOCK_LO));
const blockName = (b) => (b === BLOCK_LO ? `${b} and before` : b === BLOCK_HI ? `${b} and after` : `${b}`);

// a player's stand: his own `stand` field when the desk has one ("deep" | "projection"); until the deep-analysis
// cohort is defined, the lake's evidence tier decides: 'solid' (1,800+ minutes with match stats) -> upper stand
export function standOf(p) {
  if (p.stand === "deep" || p.stand === "projection") return p.stand;
  return p.tier === "solid" ? "deep" : "projection";
}

// a CSS colour (the desk's OKLCH tokens included) as a three.js colour, through a 1-pixel canvas
const probe = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
function cssColor(css) {
  probe.clearRect(0, 0, 1, 1); probe.fillStyle = "#000"; probe.fillStyle = css; probe.fillRect(0, 0, 1, 1);
  const d = probe.getImageData(0, 0, 1, 1).data;
  return new THREE.Color().setRGB(d[0] / 255, d[1] / 255, d[2] / 255, THREE.SRGBColorSpace);
}
const hex = (c) => `#${c.getHexString(THREE.SRGBColorSpace)}`;

// stand-local frame: u along the stand (centred), o outward from the stand's front wall, y up; to world by side.
// The front walls stand RUN metres off the touchlines (E: z = -(W/2 + RUN + o), S: x = L/2 + RUN + o, ...)
function toWorld(side, u, o, y, out = new THREE.Vector3()) {
  if (side === "E") return out.set(u, y, -(W / 2 + RUN + o));
  if (side === "W") return out.set(-u, y, W / 2 + RUN + o);
  if (side === "S") return out.set(L / 2 + RUN + o, y, u);
  return out.set(-(L / 2 + RUN + o), y, -u);
}
const xOf = (side, o) => (side === "S" ? 1 : -1) * (L / 2 + RUN + o);      // world x of a point o out from the S or N front wall
const zOf = (side, o) => (side === "W" ? 1 : -1) * (W / 2 + RUN + o);      // world z of a point o out from the E or W front wall

// a canvas texture, sRGB, sharp at grazing angles
function canvasTex(w, h, paint) {
  const cv = document.createElement("canvas"); cv.width = w; cv.height = h;
  const tex = new THREE.CanvasTexture(cv); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 8;
  tex.cv = cv; tex.repaint = () => { paint(cv.getContext("2d"), cv); tex.needsUpdate = true; };
  tex.repaint();
  return tex;
}
// one geometry from several boxes (no BufferGeometryUtils in the vendor folder): positions and normals, non-indexed
function boxes(...specs) {
  const parts = specs.map(([w, h, d, x, y, z]) => new THREE.BoxGeometry(w, h, d).translate(x, y, z).toNonIndexed());
  const g = new THREE.BufferGeometry();
  for (const k of ["position", "normal"]) g.setAttribute(k, new THREE.Float32BufferAttribute(parts.flatMap((p) => Array.from(p.attributes[k].array)), 3));
  return g;
}

export function createStadium(wrap, players, { tok, stepOf, isNight, onHover, onPick, onTarget, onFail, reduced }) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1));
  renderer.toneMapping = THREE.NeutralToneMapping;            // keeps the seat ramp's hues true
  renderer.domElement.className = "stadium";
  renderer.domElement.setAttribute("role", "img");
  renderer.domElement.setAttribute("aria-label", `${players.length.toLocaleString("en")} players as the seats of a two-tier stadium: the upper stand holds the players we have analysed deepest, the lower stand everyone else, projected from them; four stands by position, a block per birth year (oldest on the left, youngest on the right), the best outlook in the front rows`);
  wrap.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 2, 0.3, 4000);
  const yAxis = new THREE.Vector3(0, 1, 0);
  const tmpP = new THREE.Vector3(), q = new THREE.Quaternion(), s3 = new THREE.Vector3(), m4 = new THREE.Matrix4();

  // ── the geometry: per stand, per tier: rows fitted to the crowd inside a fixed envelope ──────────────────────────
  // seats of a stand-tier, youngest first (front rows); then rows R so a seat is about as deep as it is wide.
  // `rowsOf` is null before the model is in (a first guess, never drawn). Once it is, it is the rows the FILE has,
  // { E: { lo, up }, ... } (read from the model's own stand profiles), plus the Kop's steeper rake and the north end's
  // boxes: so the desk's seats always sit on the treads that were exported, whatever the crowd's size is today.
  function makeStands(rowsOf) {
    return STANDS.map((st) => {
      const len = SIDE[st.side].len, usable = len - 3;           // 3 m of aisle and wall
      const mine = players.filter((p) => p.position === st.pos);
      const kop = !!rowsOf && st.style === "kop", palcos = !!rowsOf && st.style === "palcos";
      const tiers = {};
      for (const id of ["projection", "deep"]) {
        const T = { ...TIERS[id], rake: TIERS[id].rake + (kop ? KOP_EXTRA : 0) }, depth = T.depth * st.k;
        const ps = mine.filter((p) => standOf(p) === id);
        const rows = palcos && id === "deep" ? PALCOS.levels * PALCOS.rows_per_level
          : rowsOf ? rowsOf[st.side][id === "projection" ? "lo" : "up"]
          : Math.max(4, Math.min(64, Math.round(Math.sqrt(ps.length * 0.75 * depth / usable))));
        const rd = depth / rows;                                  // row depth
        // the blocks, oldest first: each as many columns as its players need at this many rows, best outlook first
        const blocks = [];
        for (let b = BLOCK_LO; b <= BLOCK_HI; b++) {
          const bp = ps.filter((p) => blockOf(p.born) === b).sort((x, y) => ((y.p_reg3 ?? -1) - (x.p_reg3 ?? -1)) || (y.min_now - x.min_now));
          if (bp.length) blocks.push({ b, ps: bp, cols: Math.ceil(bp.length / rows) });
        }
        const cols = blocks.reduce((a, x) => a + x.cols, 0), pitch = (usable - AISLE * Math.max(0, blocks.length - 1)) / Math.max(1, cols);
        tiers[id] = { ...T, ps, n: ps.length, rows, rd, riser: rd * Math.tan(rad(T.rake)), depthM: depth, blocks, pitch };
      }
      const lo = tiers.projection, up = tiers.deep;
      // heights, bottom up: the lower treads, the soffit of the overhang, the upper tier's front lip, its treads, the back rail
      const topLow = FRONT + (lo.rows - 1) * lo.riser;
      const ys = topLow + lo.riser + HEAD;                        // underside of the overhang
      let geo;
      if (palcos) {                                               // the boxes stand over the back of the lower tier
        const po = lo.depthM - 2.4, oBack = lo.depthM + 1.2, yTop = ys + PALCOS.levels * PALCOS.level_height + 0.6;
        const oOut = oBack + 1.6, oRi = po - 1.5, yIn = yTop + 3.0;
        geo = { len, usable, lo, up, ys, yU0: ys, uo: po, po, oBack, yTop, backTread: yTop - 2.6, oRi, yIn, yOut: yIn - FALL * (oOut - oRi), oOut };
      } else {
        const yU0 = ys + LIP;                                       // the first upper tread
        const uo = lo.depthM - OVER * st.k;                         // where the upper tier starts, out from the front wall
        const oBack = uo + up.depthM;                               // the back of the upper tier
        const backTread = yU0 + (up.rows - 1) * up.riser;
        const yTop = backTread + up.riser + 2.2;                    // the back wall
        // roof: its inner edge sits COVER from the back, 7 m over the seats there; at the outer edge 9.5 m over the back row
        const oRi = oBack - COVER * up.depthM, treadAtRi = yU0 + ((oRi - uo) / up.rd) * up.riser;
        const yIn = rowsOf ? Math.max(treadAtRi + 7.0, yTop + 3.0) : treadAtRi + 7.0;
        geo = { len, usable, lo, up, ys, yU0, uo, oBack, yTop, backTread, oRi, yIn, yOut: rowsOf ? yIn - FALL * (oBack + 1.6 - oRi) : backTread + 9.5, oOut: oBack + 1.6 };
      }
      return { ...st, ...geo, tiers };
    });
  }
  let standInfo = makeStands(null);
  let byPos = Object.fromEntries(standInfo.map((s) => [s.side, s]));
  let groundMode = false;                                    // true once The Ground's model is in
  let H = Math.max(...standInfo.map((s) => s.yOut)) + 22;  // cruising height: over every roof, flag and lamp bank

  // ── the seats: a pan and a backrest (local +x is away from the pitch), hinged at the floor ────────────────────
  const seatGeo = boxes([0.72, 0.46, 0.94, -0.14, 0.23, 0], [0.16, 1.0, 0.94, 0.38, 0.5, 0]);
  const seatMat = new THREE.MeshStandardMaterial({ roughness: 0.5, metalness: 0.0 });
  const seats = new THREE.InstancedMesh(seatGeo, seatMat, players.length);
  seats.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  scene.add(seats);
  const place = [];                                          // per seat: world position, rotation, size, row, tier, stand
  let byInstance = [], seatTop = new Float32Array(0);
  // every seat's place, from the stands above: block by block from the left, youngest in the front rows
  function layoutSeats() {
    place.length = 0;
    for (const st of standInfo) {
      const rowBase = { projection: 0, deep: st.lo.rows };      // a global row index so the stands fill from the front row back
      for (const id of ["projection", "deep"]) {
        const t = st.tiers[id], o0 = id === "deep" ? st.uo : 0, y0 = id === "deep" ? st.yU0 : FRONT;
        // block by block from the left (u < 0 is the left as you face the stand from the pitch); inside a block, row by
        // row from the front, the last row centred
        let u0 = -st.usable / 2;
        if (id === "deep" && st.style === "palcos" && groundMode) {
          // the north end's boxes: the upper stand's players in a stack, rows per level, oldest left to youngest right
          const ps = t.blocks.flatMap((b) => b.ps), perRow = Math.max(1, Math.ceil(ps.length / (PALCOS.levels * PALCOS.rows_per_level)));
          // the file's boxes are 4 m wide, a divider between each: the seats of a row are shared out box by box, so none sits in a wall
          const nbox = Math.max(1, Math.floor(st.len / 4)), boxW = st.len / nbox;
          ps.forEach((p, k) => {
            const slot = Math.floor(k / perRow), i = k % perRow, level = Math.floor(slot / PALCOS.rows_per_level), row = slot % PALCOS.rows_per_level;
            const b = Math.min(nbox - 1, Math.floor((i * nbox) / perRow)), i0 = Math.ceil((b * perRow) / nbox), inBox = Math.ceil(((b + 1) * perRow) / nbox) - i0, pitchB = (boxW - 0.6) / inBox;
            const u = -st.len / 2 + b * boxW + 0.3 + (i - i0 + 0.5) * pitchB, o = st.po + 0.6 + row * 1.0, y = st.ys + level * PALCOS.level_height;      // on the box's floor (the kit lifts these 0.25 m, and the second row 0.35 m more, where the file has no step)
            p._seat = place.length;
            place.push({ p, st, tier: id, block: blockOf(p.born), rot: SIDE[st.side].rot, row: rowBase[id] + slot, u, o, y, pos: toWorld(st.side, u, o, y), sx: 0.8, sz: Math.min(1.0, pitchB * 0.9) });
          });
          continue;
        }
        for (const blk of t.blocks) {
          blk.u0 = u0; blk.u1 = u0 + blk.cols * t.pitch;
          blk.ps.forEach((p, k) => {
            const r = Math.floor(k / blk.cols), inRow = Math.min(blk.cols, blk.ps.length - r * blk.cols), c = k % blk.cols;
            const u = u0 + (c + 0.5 + (blk.cols - inRow) / 2) * t.pitch;
            const o = o0 + (r + 0.5) * t.rd, y = y0 + r * t.riser;
            p._seat = place.length;
            place.push({
              p, st, tier: id, block: blk.b, rot: SIDE[st.side].rot, row: rowBase[id] + r, u, o, y,
              pos: toWorld(st.side, u, o, y),
              // footprint: depth along the stand's outward axis (box x), width along the row (box z); the seat fills its tread
              sx: Math.min(1.0, t.rd * 0.88), sz: Math.min(1.0, t.pitch * 0.92),
            });
          });
          u0 = blk.u1 + AISLE;
        }
      }
    }
    seats.count = place.length;                              // players with no position have no seat (else they pile up as cubes at the centre spot)
    byInstance = place.map((x) => x.p);
    seatTop = new Float32Array(place.length * 3);            // the point a click snaps to: the seat's pan, in world space
    place.forEach((x, i) => { seatTop[i * 3] = x.pos.x; seatTop[i * 3 + 1] = x.pos.y + 0.5; seatTop[i * 3 + 2] = x.pos.z; });
  }
  layoutSeats();

  // ── what is left of the world around the seats: the far ground and the four floodlights; the stands, roof and dressing are the Ground's model ──
  const apron = new THREE.MeshStandardMaterial({ roughness: 1, metalness: 0 });               // the far ground round the model
  const solids = [];                                       // everything the camera must not cross (the audit's targets): the model's structure, once it is in
  // four floodlight sources; the model says where its lamp banks stand (g.lamps) and they move there when it arrives
  const towers = [0, 1, 2, 3].map(() => {
    const spot = new THREE.SpotLight(0xf4f6ff, 0, 340, Math.PI / 5, 0.55, 1.2);
    spot.position.set(0, 60, 0); spot.target.position.set(0, 0, 0);
    scene.add(spot, spot.target);
    return { spot, head: new THREE.Vector3(0, 60, 0) };
  });

  // the sky: a dome with a gradient (afternoon blue to a warm horizon; at 20:45 night blue over a floodlit haze)
  const skyMat = new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false, fog: false,
    uniforms: { top: { value: new THREE.Color() }, horizon: { value: new THREE.Color() }, bottom: { value: new THREE.Color() } },
    vertexShader: "varying vec3 vW; void main() { vec4 w = modelMatrix * vec4(position, 1.0); vW = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }",
    fragmentShader: `uniform vec3 top; uniform vec3 horizon; uniform vec3 bottom; varying vec3 vW;
      void main() { float h = normalize(vW).y; vec3 c = h > 0.0 ? mix(horizon, top, pow(h, 0.55)) : mix(horizon, bottom, min(1.0, -h * 5.0));
        gl_FragColor = vec4(c, 1.0);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
  });
  const skyDome = new THREE.Mesh(new THREE.SphereGeometry(1900, 32, 16), skyMat);
  scene.add(skyDome);

  const concourse = new THREE.Mesh(new THREE.PlaneGeometry(2400, 2400), apron);
  concourse.rotation.x = -Math.PI / 2; concourse.position.y = -0.02;
  scene.add(concourse);


  // the screen in the south-east corner, on the bastion, facing the centre spot: the scoreboard, live from the desk
  let board = null;
  // the Scoreboard page's rule (scoreboard.js): right picks out of 100 pairs, one decimal when whole numbers would hide the gap,
  // and the verdict from the 95 % range of the gap
  const picks = (auc, dp = 1) => (auc == null ? "—" : (auc * 100).toFixed(dp));
  const score2 = (a, b) => (Math.round(a * 100) === Math.round(b * 100) ? [picks(a), picks(b)] : [picks(a, 0), picks(b, 0)]);
  const verdict = (lo, hi, mean) => (lo > 0 ? "ahead" : hi < 0 ? "behind" : mean > 0 ? "edge" : "level");
  const boardFigures = () => {
    const e = board?.rungs?.find((r) => r.kind === "engine"), m = board?.rungs?.find((r) => r.kind === "market");
    if (!e || !m) return null;
    const g = board.gate || {}, [lo, hi] = g.ci95 || [null, null];
    const [us, them] = score2(e.auc, m.auc);
    const v = lo == null || hi == null || g.mean == null ? null : verdict(lo, hi, g.mean);
    const gap = v === "behind" ? `${Math.abs(g.mean * 100).toFixed(1)} right picks in 100 behind market value, from match records alone` : null;
    const line = v && { ahead: "Ahead of market value, from match records alone", edge: "Just ahead of market value, from match records alone",
      level: "Level with market value, from match records alone", behind: gap }[v];
    return { us, them, line: line || "the scoreboard" };
  };
  const paintScreen = (g, cv) => {
    g.fillStyle = "#07090f"; g.fillRect(0, 0, cv.width, cv.height);
    g.fillStyle = "#e9eef7"; g.textBaseline = "alphabetic";
    g.font = `700 54px "Barlow Condensed"`; g.textAlign = "left"; g.fillText("PROMESSE", 60, 104);
    g.textAlign = "right"; g.fillText("MARKET VALUE", cv.width - 60, 104);
    const f = boardFigures();
    g.font = `800 250px "Barlow Condensed"`; g.textAlign = "left"; g.fillStyle = "#ffd75e"; g.fillText(f ? f.us : "—", 50, 370);
    g.textAlign = "right"; g.fillText(f ? f.them : "—", cv.width - 50, 370);
    g.fillStyle = "#e9eef7"; g.font = `600 40px "Barlow"`; g.textAlign = "center";
    g.fillText(f ? f.line : "the scoreboard", cv.width / 2, 470);
    g.fillStyle = "#8fa3c4"; g.font = `500 32px "Barlow"`;
    g.fillText("right picks out of 100 pairs of young players  ·  coin flip 50", cv.width / 2, 530);
  };
  let boardLine = "";                                       // the ribbon's words (the model's LED boards are named by the desk)
  let groundScreenTex = null;                                // the same picture for the model's own screen (set once it is in)

  // ── light: 15:00 sun and sky, or 20:45 under the corner towers' lamp banks and the roof's lamp edge ─────────
  let ground = null;                                         // The Ground's model (ground3d.js), once it has loaded
  let roofParts = [];                                    // the meshes that count as the roof for the camera (it fades as you rise)
  const hemi = new THREE.HemisphereLight(0xffffff, 0x444444, 1.2);
  const sun = new THREE.DirectionalLight(0xfff1dc, 2.2);
  sun.position.set(-150, 110, 90);                          // a low afternoon sun: one side lit, its neighbour in shade
  scene.add(hemi, sun);
  // the lamp banks' glow at 20:45: a soft halo on each, additive, only at night
  const glowTex = canvasTex(128, 128, (g) => {
    const grd = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    grd.addColorStop(0, "rgba(255,250,235,1)"); grd.addColorStop(0.25, "rgba(255,246,220,0.45)"); grd.addColorStop(1, "rgba(255,240,210,0)");
    g.fillStyle = grd; g.fillRect(0, 0, 128, 128);
  });
  const glows = towers.map(({ head }) => {
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, blending: THREE.AdditiveBlending, depthWrite: false, transparent: true }));
    s.position.copy(head); s.scale.set(34, 34, 1); scene.add(s); return s;
  });

  // ── colours, from the desk's tokens; a theme change repaints everything ──────────────────────────────────────
  let ramp = [], livery, dim, crimson;
  function recolor() {
    const night = isNight();
    ramp = [0, 1, 2, 3, 4].map((i) => cssColor(tok(`--s${i}`)));
    livery = cssColor(tok("--seat-livery"));                 // a seat with no football we can see: the stand's own plastic
    dim = cssColor(tok("--seat-dim"));                       // a seat the sentence leaves out: sat back, greyed
    crimson = cssColor(tok("--crimson"));
    apron.color = cssColor(tok("--apron"));
    skyMat.uniforms.top.value = cssColor(tok("--sky"));
    skyMat.uniforms.horizon.value = cssColor(tok("--sky-horizon"));
    skyMat.uniforms.bottom.value = cssColor(tok("--apron"));
    scene.background = cssColor(tok("--sky-horizon"));
    scene.fog = new THREE.Fog(cssColor(tok("--sky-horizon")), night ? 420 : 600, night ? 1500 : 1800);
    hemi.color = cssColor(tok("--sky")).lerp(new THREE.Color(1, 1, 1), 0.6); hemi.groundColor = cssColor(tok("--grass")).lerp(cssColor(tok("--terrace")), 0.5);
    hemi.intensity = night ? 1.0 : 1.7;                      // the bowl's inside gets no direct sun: sky light has to read the seats
    sun.intensity = night ? 0.05 : 2.6;
    towers.forEach(({ spot }) => { spot.intensity = night ? 2800 : 0; });
    glows.forEach((s) => { s.visible = night; });
    ground?.setNight(night);
    renderer.toneMappingExposure = night ? 1.05 : 1.0;
    applySeats(1);
  }

  // ── seats: colour by level; when the sentence filters, the matches stand up and the others sit back ─────────
  const col = new THREE.Color();
  const filtering = () => place.some((x) => x.p.on === false);
  let focus = place.map((x) => (x.p.on === false ? 0 : 1));          // the shown state of every seat, eased toward its target
  let active = filtering();
  function seatColour(x, out) { const st = stepOf(x.p); return out.copy(st < 0 ? livery : ramp[st]); }
  function applySeats(t, rise = 1) {
    for (let i = 0; i < place.length; i++) {
      const x = place[i], target = x.p.on === false ? 0 : 1;
      focus[i] += (target - focus[i]) * t;
      const f = focus[i];
      const grow = x.gone ? 0 : Math.max(0, Math.min(1, rise * 1.6 - x.row / 120));     // the stands fill from the front row back
      const lift = active ? 0.86 + 0.5 * f : 1;                         // a match stands up; the rest sit back
      q.setFromAxisAngle(yAxis, x.rot);
      s3.set(x.sx * grow, Math.max(0.001, SEAT_H * lift * grow), x.sz * grow);
      m4.compose(x.pos, q, s3);
      seats.setMatrixAt(i, m4);
      seatColour(x, col);
      if (active) col.lerp(dim, 0.88 * (1 - f));
      seats.setColorAt(i, col);
    }
    seats.instanceMatrix.needsUpdate = true;
    if (seats.instanceColor) seats.instanceColor.needsUpdate = true;
  }
  // beacons: when the sentence filters, a dot over every match that keeps its size at any distance (seats are half a
  // metre wide; from the wide view that is a pixel)
  const dotTex = canvasTex(64, 64, (g) => {
    g.clearRect(0, 0, 64, 64); g.beginPath(); g.arc(32, 32, 26, 0, Math.PI * 2); g.fillStyle = "#ffffff"; g.fill();
    g.lineWidth = 6; g.strokeStyle = "rgba(10,14,24,0.85)"; g.stroke();
  });
  const beaconMat = new THREE.PointsMaterial({ size: 8 * renderer.getPixelRatio(), sizeAttenuation: false, vertexColors: true, map: dotTex, transparent: true, alphaTest: 0.35, depthWrite: false });
  const beacons = new THREE.Points(new THREE.BufferGeometry(), beaconMat);
  beacons.frustumCulled = false; scene.add(beacons);
  function buildBeacons() {
    const on = active ? place.filter((x) => x.p.on !== false && !x.gone) : [];
    const pos = new Float32Array(on.length * 3), cl = new Float32Array(on.length * 3);
    on.forEach((x, i) => { pos.set([x.pos.x, x.pos.y + 1.35, x.pos.z], i * 3); seatColour(x, col); if (stepOf(x.p) < 0) col.copy(cssColor(tok("--chalk"))); cl.set([col.r, col.g, col.b], i * 3); });
    beacons.geometry.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    beacons.geometry.setAttribute("color", new THREE.BufferAttribute(cl, 3));
    beacons.visible = on.length > 0 && on.length <= 1500;          // past that, the standing seats carry it
  }

  // ── the camera ───────────────────────────────────────────────────────────────────────────────────────────────
  // two states. Orbit: round the centre spot, outside the bowl (drag turns it, the wheel brings it closer, never
  // closer than the bowl's outer wall). Seat: parked at a seat's eye point, where a drag turns the head. Every move
  // between them is ONE flight on a curve (cam.curve, cam.s 0..1), looking at the pitch all the way.
  const view = { az: -0.62, el: 0.4, dist: 205, target: new THREE.Vector3(0, 6, 0) };
  const DIST = [125, 400];
  const SEAT_LOOK = new THREE.Vector3(0, 1.2, 0);           // from a seat: the centre spot
  const cam = { curve: null, s: 0, lookFrom: new THREE.Vector3(), lookTo: new THREE.Vector3(), lookVia: null, yaw: 0, pitch: 0, settle: 0, at: null, busy: false };
  const look = new THREE.Vector3(), tmpV = new THREE.Vector3(), sideV = new THREE.Vector3();
  let idle = 0, auto = !reduced, hold = false, queued = null;   // hold: a seat was flown to; stay on it until someone leaves
  const smooth = (t) => t * t * (3 - 2 * t);
  const clamp01 = (t) => Math.min(1, Math.max(0, t));
  function orbitPos(out) {
    const { az, el, dist, target } = view;
    return out.set(target.x + dist * Math.cos(el) * Math.sin(az), target.y + dist * Math.sin(el), target.z + dist * Math.cos(el) * Math.cos(az));
  }
  function placeCamera(now) {
    if (cam.curve) {
      cam.curve.getPointAt(clamp01(cam.s), camera.position);
      if (cam.lookVia) {                                     // a flight to a part of the ground: eyes on the pitch until halfway, then on the part
        const s = clamp01(cam.s);
        if (s < 0.5) look.lerpVectors(cam.lookFrom, cam.lookVia, smooth(s / 0.5)); else look.lerpVectors(cam.lookVia, cam.lookTo, smooth((s - 0.5) / 0.5));
      } else look.lerpVectors(cam.lookFrom, cam.lookTo, smooth(clamp01(cam.s)));
      // seated: the eye settles as you sit, then breathes a little (a person, not a tripod)
      camera.position.y -= 0.22 * cam.settle;
      const yaw = cam.yaw + cam.settle * 0.006 * Math.sin(now * 0.00071), pitch = cam.pitch + cam.settle * 0.004 * Math.sin(now * 0.00049 + 1);
      if (Math.abs(yaw) + Math.abs(pitch) > 1e-5) {
        tmpV.copy(look).sub(camera.position); const d = tmpV.length();
        tmpV.normalize().applyAxisAngle(yAxis, yaw);
        tmpV.applyAxisAngle(sideV.crossVectors(tmpV, yAxis).normalize(), pitch);
        look.copy(camera.position).addScaledVector(tmpV, d);
      }
      camera.lookAt(look);
      return;
    }
    orbitPos(camera.position);
    camera.lookAt(view.target);
  }
  // the roof opens as the camera rises over the ground, so the upper tier's data is never hidden; shut in a seat
  let roofOpacity = 1;                                        // how shut the roof is (1) or opened (0.15)
  function roofFade() {
    const f = cam.curve ? 0 : THREE.MathUtils.smoothstep(view.el, 0.5, 0.95);
    roofOpacity = 1 - 0.85 * f;
    if (ground) for (const m of ground.roofMats) { m.opacity = roofOpacity; m.depthWrite = f < 0.02; }     // the model's roof opens the same way
  }

  // a seat's way in, from the seat out: the eye; a slide out from under the overhang or the roof; up the tier's own
  // normal; over the roof's rim; behind the stand at cruising height. Reversed, that is the fan's way to his seat.
  function approach(x) {
    if (x.target) {                                          // a part of the ground: straight up from its pose to cruising height
      const pts = [x.pos.clone()];
      if (x.pos.y < 8) {                                     // low poses sit by the stands, the tunnel, the boards: come away from them before rising: toward the pitch from inside the bowl, outward from outside it (the gate)
        const inside = Math.abs(x.pos.x) < L / 2 + RUN + 2 && Math.abs(x.pos.z) < W / 2 + RUN + 2;
        const toward = new THREE.Vector3(inside ? -x.pos.x : x.pos.x, 0, inside ? -x.pos.z : x.pos.z).normalize(), d = inside ? Math.min(12, Math.hypot(x.pos.x, x.pos.z)) : 12;
        pts.push(new THREE.Vector3(x.pos.x, Math.max(x.pos.y + 3, 5), x.pos.z).addScaledVector(toward, d));
      }
      const last = pts[pts.length - 1], high = new THREE.Vector3(last.x, H, last.z);
      pts.push(high);
      return { pts, back: high, upTo: 1 };
    }
    const st = x.st, rake = rad(st.tiers[x.tier].rake), din = new THREE.Vector3(...IN[st.side]);
    const E = x.pos.clone().addScaledVector(din, 1.2); E.y += 1.7;                  // eye: a little above and in front of the seat
    const n = din.clone().multiplyScalar(Math.sin(rake)).addScaledVector(yAxis, Math.cos(rake));
    const clearO = x.tier === "deep" ? st.oRi - 1.5 : st.uo - 1.5;
    const fx = Math.max(0, x.o - 1.2 - clearO);
    const A1 = E.clone().addScaledVector(din, fx), A2 = A1.clone().addScaledVector(n, 11);
    const rim = toWorld(st.side, x.u, st.oOut - 1, st.yOut + 7);
    const back = toWorld(st.side, x.u, st.oOut + 28, H);
    const pts = [E]; if (fx > 0.01) pts.push(A1); pts.push(A2);
    const upTo = pts.length;
    if (ground) {
      // The Ground's roof carries girders and its pylons stand outside: rise from the open bowl to above the roof's structure,
      // cross to just inside its outer edge, then go straight up to cruising height (above the pylons) and out
      const top = ground.roofTop[st.side] + 5, over = A2.clone(); over.y = Math.max(A2.y, top);
      const edge = toWorld(st.side, x.u, st.oOut - 1, top), edgeUp = edge.clone(); edgeUp.y = H;
      pts.push(over, edge, edgeUp, back);
    } else pts.push(rim, back);
    return { pts, back, upTo };
  }
  // round the bowl at cruising height, the short way, never over the centre spot
  function arc(P, Q) {
    const a0 = Math.atan2(P.x, P.z), a1 = Math.atan2(Q.x, Q.z);
    const da = Math.atan2(Math.sin(a1 - a0), Math.cos(a1 - a0));
    const r0 = Math.max(160, Math.hypot(P.x, P.z)), r1 = Math.max(160, Math.hypot(Q.x, Q.z));
    const n = Math.max(1, Math.ceil(Math.abs(da) / 0.38)), out = [];
    for (let i = 0; i <= n; i++) { const t = i / n, a = a0 + da * t, r = r0 + (r1 - r0) * t; out.push(new THREE.Vector3(r * Math.sin(a), H + 6 * Math.sin(Math.PI * t), r * Math.cos(a))); }
    return out;
  }
  const routeIn = (x, from) => { const a = approach(x); return [from, ...arc(from, a.back), ...a.pts.slice().reverse()]; };
  const routeOut = (x, to) => { const a = approach(x); return [...a.pts, ...arc(a.back, to), to]; };
  function routeAcross(x, y) {
    const a = approach(x), b = approach(y);
    if (!x.target && !y.target && x.st === y.st) return [...a.pts.slice(0, a.upTo), ...b.pts.slice(0, b.upTo).reverse()];    // along the stand, a crane move
    return [...a.pts, ...arc(a.back, b.back), ...b.pts.slice().reverse()];
  }
  function curveOf(pts) {
    const clean = [pts[0]];
    for (const p of pts.slice(1)) if (p.distanceTo(clean[clean.length - 1]) > 0.75) clean.push(p);
    return new THREE.CatmullRomCurve3(clean, false, "centripetal", 0.5);
  }
  // one flight: s 0 -> 1 on the curve, the look easing from where it was to where it lands; a turned head and the
  // seated settle ease out over the first quarter, so leaving a seat never jumps
  const gsap = () => window.gsap;
  function fly(pts, lookTo, ease, done, via = null, delay = 0) {
    const curve = curveOf(pts);
    const lookFrom = cam.curve ? cam.lookTo.clone() : view.target.clone();
    const yaw0 = cam.yaw, pitch0 = cam.pitch, settle0 = cam.settle;
    Object.assign(cam, { curve, s: 0, busy: true, lookVia: via }); cam.lookFrom.copy(lookFrom); cam.lookTo.copy(lookTo);
    const dur = Math.min(10, Math.max(4.6, curve.getLength() / 30));       // slow enough to follow (it was 2.6 to 6.8 s, which read as rushed)
    gsap().to(cam, { s: 1, duration: dur, ease, overwrite: true, delay,
      onUpdate: () => { const k = 1 - smooth(clamp01(cam.s / 0.25)); cam.yaw = yaw0 * k; cam.pitch = pitch0 * k; cam.settle = settle0 * k; },
      onComplete: () => { cam.busy = false; done && done(); } });
  }
  const leave = document.createElement("button");
  leave.type = "button"; leave.className = "stadium-leave"; leave.textContent = "Back to the ground"; leave.hidden = true;
  wrap.appendChild(leave);
  function setSeatUI(on) { leave.hidden = !on; el.classList.toggle("in-seat", on); }

  function leaveSeat(then) {
    if (!cam.curve) return then && then();
    if (cam.busy) return;                                    // let the flight land first
    hold = false; setSeatUI(false); beam.visible = false; hideCard(); clearOutline();
    if (reduced || !gsap()) { Object.assign(cam, { curve: null, at: null, settle: 0, yaw: 0, pitch: 0 }); return then && then(); }
    fly(routeOut(cam.at, orbitPos(new THREE.Vector3())), view.target, "power2.inOut", () => {
      Object.assign(cam, { curve: null, at: null, yaw: 0, pitch: 0, settle: 0, lookVia: null }); idle = performance.now(); then && then();
    }, cam.at.target ? view.target.clone() : null);
  }
  function flyTo(p, then) {
    const x = place[p._seat]; if (!x) return then && then();
    const markFresh = lastMarked !== p && !reduced;           // the marker's rise plays once per seat
    markSeat(p);
    if (reduced || !gsap()) return then && then();
    if (cam.busy) { queued = [p, then]; return; }            // one flight at a time; the next starts where this one lands
    if (cam.at === x) return then && then();
    auto = false; hold = true; setSeatUI(true);
    const pts = cam.at ? routeAcross(cam.at, x) : routeIn(x, orbitPos(new THREE.Vector3()));
    const lead = markFresh ? 1.6 : 0;                         // a seat just marked: let the marker rise and glow before the camera moves
    fly(pts, SEAT_LOOK, "sine.inOut", () => {
      cam.at = x;
      gsap().to(cam, { settle: 1, duration: 1.1, ease: "power2.out" });
      gsap().to(beam.material, { opacity: 0, duration: 1.2, onComplete: () => { beam.visible = false; } });
      then && then();
      if (queued) { const [qp, qt] = queued; queued = null; flyTo(qp, qt); }
    }, null, lead);
  }
  function select(p) { onHover(null); flyTo(p, () => onPick(p)); }

  // ── the parts of The Ground (banners, screen, door...): click one, it outlines and glows, the camera flies to its pose ──
  const labelEl = document.createElement("div");
  labelEl.className = "ground-label"; labelEl.hidden = true; wrap.appendChild(labelEl);
  function showLabel(t, e) {
    if (!t || !e || cam.busy) { labelEl.hidden = true; return; }
    const r = wrap.getBoundingClientRect();
    labelEl.textContent = t.label; labelEl.hidden = false;
    labelEl.style.transform = `translate(${Math.round(e.clientX - r.left + 14)}px, ${Math.round(e.clientY - r.top + 16)}px)`;
  }
  const cardEl = document.createElement("div");
  cardEl.className = "ground-card"; cardEl.hidden = true; cardEl.setAttribute("role", "status");
  cardEl.innerHTML = '<b class="gc-title"></b><p class="gc-body"></p><button type="button" class="gc-go" hidden></button>';
  wrap.appendChild(cardEl);
  const hideCard = () => { cardEl.hidden = true; };
  const PLURAL = { Goalkeeper: "goalkeepers", Defender: "defenders", Midfield: "midfielders", Attack: "attackers" };
  // what each kind of part says about itself, in plain words (the stand and screen cards carry the desk's own figures)
  function describe(t) {
    const kind = t.show?.kind, st = kind === "stand" ? standInfo.find((s) => s.side === t.show.side) : null;
    if (st) return { body: `${st.lo.n.toLocaleString("en")} players in the lower stand (Projections), ${st.up.n.toLocaleString("en")} in the upper stand (Deep analysis). The front rows are the youngest.`, go: `Show these ${PLURAL[st.pos] || "players"}` };
    if (kind === "scoreboard") {
      const f = boardFigures();
      return { body: f ? `Promesse picks right in ${f.us} pairs out of 100, market value in ${f.them}: a pair is one young player who became a regular and one who did not, on a season the engine never saw. 100 would be perfect, 50 a coin flip; higher is better.` : "The scoreboard: how well Promesse ranks who becomes a regular, against the market's own value.", go: "Open the Scoreboard" };
    }
    if (kind === "ribbon") return { body: boardLine.split(" ● ").filter(Boolean).join(" · ") };
    if (kind === "tunnel") return { body: "Where the teams walk out. Your first visit in a browser session starts here." };
    if (kind === "gate") return { body: "The main gate, on the west side." };
    if (kind === "banner") return { body: "Fans' banners hang over the parapets, in the supporters' own languages: what they call their own youngsters." };
    if (kind === "essay") return { body: "A board on the stand's upper tier." };
    return { body: "" };
  }
  function showCard(t) {
    const d = describe(t), go = cardEl.querySelector(".gc-go");
    cardEl.querySelector(".gc-title").textContent = t.label;
    cardEl.querySelector(".gc-body").textContent = d.body;
    go.hidden = !d.go; go.textContent = d.go || ""; go.onclick = () => onTarget && onTarget(t);
    cardEl.hidden = false;
  }
  let outline = null;
  function clearOutline() { if (outline) { scene.remove(outline); outline.children.forEach((l) => l.geometry.dispose()); outline = null; } }
  const targetStop = new Map();                              // per part: where the camera stands (an "at", like a seat's)
  function stopOf(t) {
    if (!targetStop.has(t.name)) targetStop.set(t.name, { target: t, pos: new THREE.Vector3(...t.camera.position), look: new THREE.Vector3(...t.camera.look), row: -1 });
    return targetStop.get(t.name);
  }
  // click on a part: outline and a short glow at once, then ONE flight to its pose, eyes on the pitch until halfway
  function selectTarget(t, { instant = false } = {}) {
    if (!ground || !t.found) return;
    onHover(null); labelEl.hidden = true;
    const x = stopOf(t);
    clearOutline(); outline = groundLib.outlineOf(t, crimson); scene.add(outline);
    groundLib.glow(t, crimson, instant ? null : gsap(), 1.2);
    if (!instant && gsap()) gsap().to(outline.userData.mat, { opacity: 0, duration: 1.4, delay: 1.6, ease: "power1.in" });
    if (instant || reduced || !gsap()) {                      // no flight: stand at the pose
      Object.assign(cam, { curve: new THREE.LineCurve3(x.pos.clone().addScaledVector(tmpV.copy(x.look).sub(x.pos).normalize(), -1), x.pos.clone()), s: 1, at: x, yaw: 0, pitch: 0, settle: 0, busy: false, lookVia: null });
      cam.lookFrom.copy(x.look); cam.lookTo.copy(x.look); hold = true; auto = false; setSeatUI(true); beam.visible = false; showCard(t);
      placeCamera(performance.now());                        // the camera is there NOW, not at the next frame
      return;
    }
    if (cam.busy) { queued = [{ _target: t }, null]; return; }
    if (cam.at === x) return showCard(t);
    auto = false; hold = true; setSeatUI(true); beam.visible = false; hideCard();
    const pts = cam.at ? routeAcross(cam.at, x) : routeIn(x, orbitPos(new THREE.Vector3()));
    fly(pts, x.look, "power2.inOut", () => {
      cam.at = x; showCard(t);
      if (queued) { const [qp, qt] = queued; queued = null; if (qp._target) selectTarget(qp._target); else flyTo(qp, qt); }
    }, view.target.clone());
  }

  // the walk out of the tunnel (first visit in a browser session): from inside the tunnel, onto the grass, up over the west
  // stand to the wide view, while the stands fill from the front row back
  const FAR_STAND = new THREE.Vector3(0, 10, -(W / 2 + RUN + 14));
  function walkPoints() {
    const end = orbitPos(new THREE.Vector3());
    return [new THREE.Vector3(0, 1.5, groundMode ? W / 2 + RUN + 9.5 : W / 2 + RUN - 2.6), new THREE.Vector3(0, 1.7, W / 2 + 0.5), new THREE.Vector3(0, 2.0, W / 2 - 7),
      new THREE.Vector3(-5, 7, 9), new THREE.Vector3(-26, 28, 24), new THREE.Vector3(-64, 60, 80), end];
  }
  function walkOut(done) {
    const start = walkPoints();
    Object.assign(cam, { curve: curveOf(start), s: 0, busy: true, lookVia: null }); cam.lookFrom.copy(FAR_STAND); cam.lookTo.copy(view.target);
    gsap().to(cam, { s: 1, duration: 6.4, ease: "power1.inOut", overwrite: true, onComplete: () => { Object.assign(cam, { curve: null, busy: false }); idle = performance.now(); done && done(); } });
  }

  let drag = null, moved = 0;
  const el = renderer.domElement;
  el.addEventListener("pointerdown", (e) => {
    if (cam.busy) return;
    drag = { x: e.clientX, y: e.clientY, az: view.az, el: view.el, yaw: cam.yaw, pitch: cam.pitch }; moved = 0;
    el.setPointerCapture(e.pointerId); auto = false;
  });
  el.addEventListener("pointerup", (e) => {
    if (el.hasPointerCapture(e.pointerId)) el.releasePointerCapture(e.pointerId);
    if (drag && moved < 5) { const hit = pickAny(e); if (hit?.p) select(hit.p); else if (hit?.t) selectTarget(hit.t); }
    drag = null; idle = performance.now();
  });
  el.addEventListener("pointermove", (e) => {
    if (drag) {
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y; moved = Math.max(moved, Math.abs(dx) + Math.abs(dy));
      if (cam.curve) {                                       // in a seat: turn the head, within what a neck does
        cam.yaw = Math.max(-1.3, Math.min(1.3, drag.yaw - dx * 0.004));
        cam.pitch = Math.max(-0.55, Math.min(0.5, drag.pitch - dy * 0.003));
      } else {
        view.az = drag.az - dx * 0.006; view.el = Math.min(1.25, Math.max(0.2, drag.el + dy * 0.004));
      }
      onHover(null); ring.visible = false; return;
    }
    pending = e;
  });
  el.addEventListener("pointerleave", () => { pending = null; onHover(null); el.classList.remove("hit"); ring.visible = false; });
  el.addEventListener("wheel", (e) => {
    if (cam.curve) return;                                   // in a seat the wheel scrolls the page
    e.preventDefault(); view.dist = Math.min(DIST[1], Math.max(DIST[0], view.dist * (1 + Math.sign(e.deltaY) * 0.08))); auto = false; idle = performance.now();
  }, { passive: false });
  addEventListener("keydown", (e) => { if (e.key === "Escape" && cam.curve && document.body.contains(el)) leaveSeat(); });
  leave.addEventListener("click", () => leaveSeat());

  // picking a seat: the ray against the seats first; if it misses, the nearest seat in focus within SNAP px on screen
  // that no concrete hides. Seats are half a metre wide: from the wide view a click would otherwise land on the tread.
  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2(), vp = new THREE.Matrix4(), occl = new THREE.Raycaster();
  let pending = null;
  // is a point behind concrete (or the roof, while the roof is shut) from where the camera stands?
  function hidden(pt, dist) {
    occl.set(camera.position, tmpV.copy(pt).sub(camera.position).normalize()); occl.far = Math.max(0, dist - 1.2);
    const by = roofOpacity < 0.5 ? solids.filter((m) => !roofParts.includes(m)) : solids;
    return occl.intersectObjects(by, false).length > 0;
  }
  // what is under the pointer: a seat ({ p }) or, when The Ground is in the page, a part of it ({ t }); null when neither
  function pickAny(e) {
    const r = el.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
    ndc.set((mx / r.width) * 2 - 1, -(my / r.height) * 2 + 1);
    camera.updateMatrixWorld();
    ray.setFromCamera(ndc, camera); ray.firstHitOnly = true;
    const hits = ray.intersectObject(seats, false);
    for (const h of hits) { const p = byInstance[h.instanceId]; if (p && p.on !== false && !hidden(h.point, h.distance)) return { p }; }
    // a part of the ground (banner, screen, door...) wins over a seat that is only NEAR; a stand only where no seat is near
    const gt = ground?.pick(ray, { skipStands: true, roofOpen: roofOpacity < 0.5 });
    if (gt) return { t: gt.target };
    vp.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
    const m = vp.elements, near = [], R2 = SNAP * SNAP;
    for (let i = 0; i < place.length; i++) {
      if ((active && byInstance[i].on === false) || place[i].gone) continue;
      const x = seatTop[i * 3], y = seatTop[i * 3 + 1], z = seatTop[i * 3 + 2];
      const w = m[3] * x + m[7] * y + m[11] * z + m[15]; if (w <= 0.1) continue;
      const px = ((m[0] * x + m[4] * y + m[8] * z + m[12]) / w + 1) * 0.5 * r.width, py = (1 - (m[1] * x + m[5] * y + m[9] * z + m[13]) / w) * 0.5 * r.height;
      const d2 = (px - mx) ** 2 + (py - my) ** 2; if (d2 < R2) near.push([d2, i]);
    }
    near.sort((a, b) => a[0] - b[0]);
    for (const [, i] of near.slice(0, 8)) {
      tmpP.set(seatTop[i * 3], seatTop[i * 3 + 1] + 0.3, seatTop[i * 3 + 2]);
      if (!hidden(tmpP, tmpP.distanceTo(camera.position))) return { p: byInstance[i] };
    }
    const gs = ground?.pick(ray, { roofOpen: roofOpacity < 0.5 });
    return gs ? { t: gs.target } : null;
  }
  const pick = (e) => pickAny(e)?.p ?? null;
  // the seat under the pointer: a ring that keeps its size, so you see the seat before you click it
  const ringTex = canvasTex(128, 128, (g) => {
    g.clearRect(0, 0, 128, 128); g.lineWidth = 14; g.strokeStyle = "rgba(10,14,24,0.9)"; g.beginPath(); g.arc(64, 64, 48, 0, Math.PI * 2); g.stroke();
    g.lineWidth = 8; g.strokeStyle = "#ffffff"; g.stroke();
  });
  const ring = new THREE.Sprite(new THREE.SpriteMaterial({ map: ringTex, sizeAttenuation: false, depthTest: false, transparent: true }));
  ring.scale.set(0.045, 0.045, 1); ring.visible = false; ring.renderOrder = 10; scene.add(ring);
  // the picked seat: a crimson block over it and a crimson beam above, so you can follow it while you fly (the One
  // Call Rule: crimson is Promesse's call and the picked seat)
  const marker = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshBasicMaterial({ color: 0xffffff }));
  marker.visible = false; scene.add(marker);
  const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.22, 1, 10, 1, true).translate(0, 0.5, 0), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.55, depthWrite: false }));
  beam.visible = false; scene.add(beam);
  const halo = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending }));
  halo.visible = false; scene.add(halo);
  let lastMarked = null;                                     // the seat found last (kept, so the model arriving late can mark it again)
  function markSeat(p) {
    const x = place[p._seat]; if (!x) return;
    const fresh = lastMarked !== p; lastMarked = p;
    marker.material.color.copy(crimson); beam.material.color.copy(crimson);
    marker.scale.set(x.sx * 1.35, 1.1, x.sz * 1.35);
    marker.position.copy(x.pos).add(tmpP.set(0, 0.55, 0)); marker.rotation.y = x.rot; marker.visible = true;
    beam.position.copy(x.pos).add(tmpP.set(0, 1.2, 0)); beam.scale.set(1, Math.max(8, H - x.pos.y - 6), 1);
    beam.material.opacity = 0.55; beam.visible = true;
    halo.material.color.copy(crimson); halo.position.copy(marker.position); halo.rotation.y = x.rot; halo.visible = false;
    if (!fresh || reduced || !gsap()) return;
    // the arrival: the block rises out of the seat, the beam climbs, a glow swells round it and fades
    const g = gsap(), m0 = marker.scale.clone(), bh = beam.scale.y, y0 = marker.position.y;
    g.killTweensOf([marker.scale, marker.position, beam.scale, beam.material, halo.scale, halo.material]);
    marker.scale.set(m0.x * 0.2, 0.05, m0.z * 0.2); marker.position.y = y0 - 0.5;
    g.to(marker.scale, { x: m0.x, y: m0.y, z: m0.z, duration: 0.9, ease: "back.out(2.2)" });
    g.to(marker.position, { y: y0, duration: 0.9, ease: "power3.out" });
    beam.scale.y = 0.01; beam.material.opacity = 0.9;
    g.to(beam.scale, { y: bh, duration: 1.3, ease: "power2.out", delay: 0.15 });
    g.to(beam.material, { opacity: 0.55, duration: 1.3, delay: 0.15 });
    halo.visible = true; halo.material.opacity = 0.75; halo.scale.set(m0.x * 1.1, m0.y * 1.1, m0.z * 1.1);
    g.to(halo.scale, { x: m0.x * 3.4, y: m0.y * 2.6, z: m0.z * 3.4, duration: 1.5, ease: "power2.out" });
    g.to(halo.material, { opacity: 0, duration: 1.5, ease: "power1.in", onComplete: () => { halo.visible = false; } });
  }

  // ── the audits: replay a flight against the meshes (the camera must never cross concrete, roof, screen, tunnel) ──
  // Samples the path and raycasts every step; probes a 0.45 m sphere of rays round every sample for clearance.
  const probes = [];
  for (const a of [-1, 0, 1]) for (const b of [-1, 0, 1]) for (const c of [-1, 0, 1]) if (a || b || c) probes.push(new THREE.Vector3(a, b, c).normalize());
  function auditCurve(curve, steps = 260, skipStart = 0) {
    const rc = new THREE.Raycaster(), a = new THREE.Vector3(), b = new THREE.Vector3(), d = new THREE.Vector3();
    rc.firstHitOnly = true;
    let crossings = 0, minClear = Infinity, minY = Infinity;
    const names = new Set();                                 // what was hit (so a failing flight says what it hit)
    curve.getPointAt(0, a);
    for (let i = 1; i <= steps; i++) {
      curve.getPointAt(i / steps, b); d.copy(b).sub(a);
      const seg = d.length(); if (seg > 1e-6) {
        rc.set(a, d.normalize()); rc.far = seg;
        const hit = rc.intersectObjects(solids, false); crossings += hit.length; hit.forEach((h) => names.add(h.object.name || "(procedural)"));
      }
      if (i / steps >= skipStart) for (const pr of probes) { rc.set(b, pr); rc.far = 0.45; const h = rc.intersectObjects(solids, false)[0]; if (h) { minClear = Math.min(minClear, h.distance); if (h.distance < 0.3) names.add(h.object.name || "(procedural)"); } }
      minY = Math.min(minY, b.y);
      a.copy(b);
    }
    return { crossings, minClear: minClear === Infinity ? 0.45 : minClear, minY, hit: [...names] };
  }
  const auditSeat = (x) => auditCurve(curveOf(routeIn(x, orbitPos(new THREE.Vector3()))));
  // a spread of seats: every stand, both tiers, the front row, the middle and the back, left, centre and right; plus
  // seat-to-seat flights between stands and along one stand
  function audit() {
    // control: a straight line from outside the east stand to the centre spot MUST cross concrete, or the audit is blind
    const rc = new THREE.Raycaster(new THREE.Vector3(0, 12, -200), new THREE.Vector3(0, 0, 1), 0, 200);
    const out = { control: rc.intersectObjects(solids, false).length, seats: 0, across: 0, crossings: 0, tooClose: 0, minClear: Infinity, minY: Infinity, bad: [] };
    const picked = [];
    for (const st of standInfo) for (const id of ["projection", "deep"]) {
      const mine = place.filter((x) => x.st === st && x.tier === id && !x.gone); if (!mine.length) continue;
      const rows = [...new Set(mine.map((x) => x.row))].sort((a, b) => a - b);
      for (const r of [rows[0], rows[Math.floor(rows.length / 2)], rows[rows.length - 1]]) {
        const rs = mine.filter((x) => x.row === r);
        for (const x of [rs[0], rs[Math.floor(rs.length / 2)], rs[rs.length - 1]]) {
          picked.push(x);
          const res = auditSeat(x); out.seats++; out.crossings += res.crossings;
          out.minClear = Math.min(out.minClear, res.minClear); out.minY = Math.min(out.minY, res.minY);
          if (res.minClear < 0.3) out.tooClose++;
          if (res.crossings || res.minClear < 0.3) out.bad.push({ stand: st.name, tier: id, row: r, ...res });
        }
      }
    }
    for (let i = 0; i + 7 < picked.length; i += 5) {
      const res = auditCurve(curveOf(routeAcross(picked[i], picked[i + 7]))); out.across++; out.crossings += res.crossings;
      out.minClear = Math.min(out.minClear, res.minClear);
      if (res.crossings || res.minClear < 0.3) out.bad.push({ across: [picked[i].st.name, picked[i + 7].st.name], ...res });
    }
    return out;
  }
  // the walk-out starts inside the tunnel, so its first stretch is within reach of the tunnel walls by design
  const auditEnter = () => auditCurve(curveOf(walkPoints()), 260, 0.08);

  // ── the loop: draws while on screen, turns slowly when nobody touches it ─────────────────────────────────────
  let raf = 0, last = performance.now(), alive = true, visible = true;
  const io = new IntersectionObserver((es) => { visible = es.some((x) => x.isIntersecting); if (visible) loop(); }, { threshold: 0.01 });
  io.observe(wrap);
  function resize() {
    const r = wrap.getBoundingClientRect();
    renderer.setSize(r.width, r.height, false);
    camera.aspect = r.width / Math.max(1, r.height); camera.updateProjectionMatrix();
  }
  const ro = new ResizeObserver(resize); ro.observe(wrap);
  function loop() {
    cancelAnimationFrame(raf);
    if (!alive || !visible || document.hidden) return;
    if (!document.body.contains(el)) return dispose();
    raf = requestAnimationFrame((now) => {
      const dt = Math.min(0.05, (now - last) / 1000); last = now;
      if (!auto && !drag && !hold && !cam.curve && performance.now() - idle > 6000 && !reduced) auto = true;
      if (auto && !cam.curve) view.az += dt * 0.035;
      if (!reduced) {
        const t = now / 1000;
      }
      if (pending && !cam.busy) {
        const hit = pickAny(pending), p = hit?.p ?? null;
        if (p) { onHover(p, pending.clientX, pending.clientY); ring.position.copy(place[p._seat].pos).add(tmpP.set(0, 0.6, 0)); ring.visible = true; }
        else { onHover(null); ring.visible = false; }
        showLabel(hit?.t ?? null, pending);                     // a part of the ground names itself in plain words
        el.classList.toggle("hit", !!hit); pending = null;
      }
      placeCamera(now); roofFade();
      renderer.render(scene, camera);
      loop();
    });
  }
  document.addEventListener("visibilitychange", loop);
  const onTheme = () => { recolor(); buildBeacons(); groundScreenTex?.repaint(); };
  addEventListener("themechange", onTheme);
  function dispose() {
    alive = false; cancelAnimationFrame(raf); io.disconnect(); ro.disconnect();
    removeEventListener("themechange", onTheme); document.removeEventListener("visibilitychange", loop);
    leave.remove(); parts.remove(); renderer.dispose();
  }

  // the model's screen and ribbon read the live scoreboard (the same figures as the Scoreboard page)
  const deepN = standInfo.reduce((s, x) => s + x.up.n, 0), projN = standInfo.reduce((s, x) => s + x.lo.n, 0);
  boardLine = `Promesse ● ${place.length.toLocaleString("en")} players in the ground ● upper stand: deep analysis, ${deepN.toLocaleString("en")} ● lower stand: projections, ${projN.toLocaleString("en")} ● front rows: the youngest ● one of our own ● `;
  fetch("/api/scoreboard").then((r) => (r.ok ? r.json() : null)).then((d) => {
    if (!d || !alive) return;
    board = d; groundScreenTex?.repaint();
    const f = boardFigures();
    if (f) { boardLine += `right picks out of 100 pairs: Promesse ${f.us} · market value ${f.them} ● `; }
  }).catch(() => {});

  // ── The Ground: the model made in Blender (ground3d.js) is the stands, roof and dressing ──
  // Until the file is in, the page shows "Loading the Ground" and the seats wait; the desk keeps what it owns: the seats (one per
  // player), the picking, the camera flights, the day/night switch and the scoreboard figures.
  let groundLib = null;
  let ready = false, wantEnter = false, pendingMark = null;   // ready: the model is in; the walk-out and a "find his seat" wait for it
  seats.visible = false;                                     // no seats in mid-air while the file downloads
  let loadingEl = wrap.querySelector(".ground-loading");     // what the visitor sees meanwhile (the page puts it up before this module loads)
  if (!loadingEl) {
    loadingEl = document.createElement("div"); loadingEl.className = "ground-loading"; loadingEl.setAttribute("role", "status");
    loadingEl.innerHTML = '<b>Loading the Ground</b><span>the stadium model, about 14 MB</span><i></i>';
    wrap.appendChild(loadingEl);
  }
  const parts = document.createElement("details");          // a keyboard-friendly list of the parts, beside the ones you can click in the picture
  parts.className = "ground-parts"; parts.hidden = true;
  parts.innerHTML = '<summary>Parts of the ground</summary><ul></ul>';
  wrap.appendChild(parts);
  function switchToGround(g) {
    const wasFlying = cam.curve && !cam.at?.target ? lastMarked : null;        // a seat flight under way when the model arrived: it starts again on the new seats
    if (cam.curve || cam.busy) { gsap()?.killTweensOf(cam); Object.assign(cam, { curve: null, at: null, busy: false, lookVia: null, settle: 0 }); setSeatUI(false); hold = false; }
    ground = g; groundMode = true;
    standInfo = makeStands(g.sections);                      // the rows the file really has, the Kop's rake, the north end's boxes
    byPos = Object.fromEntries(standInfo.map((s) => [s.side, s]));
    H = Math.max(40, g.box.max.y) + 8;                       // cruising height: over the roof, the pylons and the lamp banks
    layoutSeats();
    // a seat needs a floor: the few front-row seats in front of the players' tunnel have none (the file cuts the tread away for the
    // doorway), so those stay unseated rather than float over the opening
    {
      const rc = new THREE.Raycaster(), down = new THREE.Vector3(0, -1, 0), o = new THREE.Vector3(), floors = g.solids.filter((m) => /^(STAND_[NSEW]_[A-Za-z]+|PALCOS_N_structure)$/.test(m.name));
      rc.firstHitOnly = true; rc.far = 3;
      for (const x of place) { o.copy(x.pos); o.y += 1; rc.set(o, down); x.gone = rc.intersectObjects(floors, false).length === 0; }
    }
    scene.add(g.root);
    solids.length = 0; solids.push(...g.solids); roofParts = g.roofParts;
    g.roofMats.forEach((m) => { m.transparent = true; m.needsUpdate = true; });
    camera.near = 1; camera.updateProjectionMatrix();       // the contract: 0.1 m flickers on the paving 1 cm under the turf
    concourse.position.y = -0.6;                             // the far ground sits below the model's own paving
    g.lamps.forEach((v, i) => { if (towers[i]) { towers[i].spot.position.copy(v); glows[i].position.copy(v); } });
    // the model's screen shows the desk's own figures (the file carries only a neutral welcome)
    groundScreenTex = canvasTex(1280, 600, paintScreen); groundScreenTex.flipY = false; groundScreenTex.needsUpdate = true;
    g.screen.forEach((m) => {
      m.material = m.material.clone(); m.material.map = groundScreenTex;
      if (m.material.emissiveMap) m.material.emissiveMap = groundScreenTex;
      m.material.needsUpdate = true;
    });
    // the list of parts
    parts.querySelector("ul").innerHTML = "";
    for (const t of g.targets.filter((t) => t.found)) {
      const li = document.createElement("li"), b = document.createElement("button");
      b.type = "button"; b.textContent = t.label; b.dataset.part = t.name; b.onclick = () => { parts.open = false; selectTarget(t); };
      li.appendChild(b); parts.querySelector("ul").appendChild(li);
    }
    parts.hidden = false;
    focus = place.map((x) => (x.p.on === false ? 0 : 1)); active = filtering();
    recolor(); buildBeacons();
    if (lastMarked) markSeat(lastMarked);
    wrap.dataset.ground = "model";
    if (wasFlying) flyTo(wasFlying);
    seats.visible = true; ready = true; loadingEl.remove();
    if (pendingMark) { const p = pendingMark; pendingMark = null; markSeat(p); flyTo(p); }
    if (wantEnter) { wantEnter = false; api.enter(); }
  }
  async function adoptGround() {
    const base = window.__GROUND_BASE || "/ground";          // (the headless checks point this at a wrong path to test the fallback)
    let g;
    try { groundLib = await import("/static/ground3d.js"); g = await groundLib.loadGround(base); }
    catch (e) { console.info("stadium: the model did not load", e?.message || e); wrap.dataset.ground = "light"; loadingEl.remove(); onFail?.(e); return; }
    if (!alive) return;
    // The model's shaders are compiled on the graphics driver's own threads while the page keeps running ("Loading the Ground"
    // stays up); done in the first frame that draws the model instead, the page froze for ~1 s waiting for the driver ( trace).
    // Mirror the roof's material change first, so the program compiled is the one that will be drawn.
    g.roofMats.forEach((m) => { m.transparent = true; m.needsUpdate = true; });
    try { await renderer.compileAsync(g.root, camera, scene); } catch (e) { console.info("stadium: shader precompile skipped", e?.message || e); }
    if (!alive) return;
    switchToGround(g);
  }
  if (!window.__GROUND_OFF) adoptGround();

  resize(); recolor(); buildBeacons(); placeCamera(performance.now()); loop();
  const api = {
    // the sentence changed: matches stand up, the others sit back, beacons over the matches
    draw(animate) {
      active = filtering(); buildBeacons();
      if (!animate || reduced || !gsap()) return applySeats(1);
      const o = { t: 0 };
      gsap().to(o, { t: 1, duration: 0.5, ease: "expo.out", onUpdate: () => applySeats(0.25), onComplete: () => applySeats(1) });
    },
    mark(p) { if (!ready) { pendingMark = p; lastMarked = p; return; } flyTo(p); },       // flyTo marks the seat (with its rise) and then flies
    enter() {
      if (!ready) { wantEnter = true; return; }       // the walk-out waits for the model
      if (reduced || !gsap()) return applySeats(1, 1);
      const o = { r: 0 };
      applySeats(1, 0);
      let first = true;
      try { first = !sessionStorage.getItem("promesse.walkout"); sessionStorage.setItem("promesse.walkout", "1"); } catch { /* private mode: walk out every time */ }
      if (first) {
        walkOut();
        gsap().to(o, { r: 1, duration: 3.6, delay: 0.6, ease: "power2.out", onUpdate: () => applySeats(1, o.r) });
        return;
      }
      // later visits: the camera comes down over the ground while the stands fill from the front row back
      const from = { az: view.az - 0.5, el: 0.95, dist: 340 };
      const to = { az: view.az, el: view.el, dist: view.dist };
      Object.assign(view, from);
      gsap().to(view, { ...to, duration: 2.0, ease: "expo.out" });
      gsap().to(o, { r: 1, duration: 1.6, ease: "power2.out", onUpdate: () => applySeats(1, o.r) });
    },
    // test hooks (the headless checks): the collision audits, a seat's stand, the camera and a snap to a seat
    audit, auditEnter, scene, renderer, camera,
    stands: () => standInfo.map((s) => ({ stand: s.name, k: s.k, rows: [s.lo.rows, s.up.rows], n: [s.lo.n, s.up.n], blocks: [s.lo.blocks.length, s.up.blocks.length], seatWidth: [+s.lo.pitch.toFixed(2), +s.up.pitch.toFixed(2)], rowDepth: [+s.lo.rd.toFixed(2), +s.up.rd.toFixed(2)] })),
    seatFor: (pred) => place.find(pred),
    park(p) {                                                 // jump to a seat's eye point without the flight
      const x = place[p._seat];
      markSeat(p); beam.visible = false;
      Object.assign(cam, { curve: curveOf(routeIn(x, orbitPos(new THREE.Vector3()))), s: 1, at: x, yaw: 0, pitch: 0, settle: 1, busy: false, lookVia: null });
      cam.lookFrom.copy(SEAT_LOOK); cam.lookTo.copy(SEAT_LOOK); hold = true; auto = false; setSeatUI(true);
    },
    pickAt(clientX, clientY) { return pick({ clientX, clientY }); },
    // The Ground's parts (the headless checks): the model, a part by name, a screen point where a click selects it, the part the camera is at
    ground: () => ground,
    mode: () => (ground ? "model" : "loading"),
    selectPart(name, opts) { const t = ground?.targetByName(name); if (t) selectTarget(t, opts); return !!t; },
    currentPart: () => cam.at?.target?.name ?? null,
    busy: () => cam.busy,
    partPoint(name) {
      const t = ground?.targetByName(name); if (!t) return null;
      const r = el.getBoundingClientRect(); camera.updateMatrixWorld(); camera.matrixWorldInverse.copy(camera.matrixWorld).invert();
      const cands = [], v = new THREE.Vector3();
      for (const p of t.picks.slice(0, 8)) {
        const pos = p.geometry.attributes.position, idx = p.geometry.index, tris = idx ? idx.count / 3 : pos.count / 3, step = Math.max(1, Math.floor(tris / 300));
        for (let k = 0; k < tris; k += step) {                // points inside a triangle (a small grid of weights), projected
          const a = idx ? idx.getX(k * 3) : k * 3, b = idx ? idx.getX(k * 3 + 1) : k * 3 + 1, c = idx ? idx.getX(k * 3 + 2) : k * 3 + 2;
          for (let i = 1; i <= 5; i++) for (let j = 1; i + j <= 5; j++) {
            const wa = i / 6, wb = j / 6, wc = 1 - wa - wb;
            v.set(pos.getX(a) * wa + pos.getX(b) * wb + pos.getX(c) * wc, pos.getY(a) * wa + pos.getY(b) * wb + pos.getY(c) * wc, pos.getZ(a) * wa + pos.getZ(b) * wb + pos.getZ(c) * wc).project(camera);
            if (v.z < 1 && Math.abs(v.x) < 0.96 && Math.abs(v.y) < 0.96) cands.push([v.x, v.y]);
          }
        }
      }
      cands.sort((p, q) => p[0] * p[0] + p[1] * p[1] - (q[0] * q[0] + q[1] * q[1]));
      for (const [nx, ny] of cands.slice(0, 1500)) {
        const x = r.left + ((nx + 1) / 2) * r.width, y = r.top + ((1 - ny) / 2) * r.height;
        if (pickAny({ clientX: x, clientY: y })?.t === t) return { x, y };
      }
      return null;
    },
    rayNames(clientX, clientY) {                              // debugging aid for the checks: what a click there would meet, nearest first
      const r = el.getBoundingClientRect(); ndc.set(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1);
      camera.updateMatrixWorld(); ray.setFromCamera(ndc, camera); ray.firstHitOnly = true;
      const hits = ground ? ray.intersectObjects(ground.pickables, false).slice(0, 4).map((h) => `${h.object.name}@${h.distance.toFixed(1)}`) : [];
      const sh = ray.intersectObject(seats, false)[0];
      return { hits, seat: sh ? +sh.distance.toFixed(1) : null };
    },
    auditPart(name) { const t = ground?.targetByName(name); return t ? auditCurve(curveOf(routeIn(stopOf(t), orbitPos(new THREE.Vector3())))) : null; },
    seatsOnTreads() {                                         // every seat stands on the model's concrete: a ray down from just above it must land within 6 cm
      if (!ground) return null;
      const rc = new THREE.Raycaster(), down = new THREE.Vector3(0, -1, 0), origin = new THREE.Vector3(), gaps = [];
      rc.firstHitOnly = true;
      const stands = ground.solids.filter((m) => /^STAND_[NSEW]_[A-Za-z]+$/.test(m.name) || /^PALCOS_N_structure$/.test(m.name));
      let bad = 0, worst = 0;
      const groups = {};
      for (const x of place) {
        if (x.gone) continue;
        origin.copy(x.pos); origin.y += 1.0; rc.set(origin, down); rc.far = 3;
        const h = rc.intersectObjects(stands, false)[0], gap = h ? h.distance - 1.0 : Infinity;
        const gk = `${x.st.side}-${x.tier}`, G = (groups[gk] ||= { n: 0, off: 0, rows: {} });
        G.n++; if (!h || Math.abs(gap) > 0.06) G.off++; if (x.row - (x.tier === "deep" ? x.st.lo.rows : 0) < 3 && G.rows[x.row] === undefined) G.rows[x.row] = h ? +gap.toFixed(3) : null;
        if (!h || Math.abs(gap) > 0.06) { bad++; if (gaps.length < 5) gaps.push({ stand: x.st.name, tier: x.tier, row: x.row, gap: h ? +gap.toFixed(3) : null }); }
        else worst = Math.max(worst, Math.abs(gap));
      }
      return { seats: place.length, unseated: place.filter((x) => x.gone).length, off: bad, worst: +worst.toFixed(3), examples: gaps, groups };
    },
    setView(v) { Object.assign(view, v); auto = false; },
    leave: leaveSeat,
    dispose,
  };
  wrap.__stadium = api;
  return api;
}
