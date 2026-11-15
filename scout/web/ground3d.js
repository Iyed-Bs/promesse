// The Ground, inside the stadium page: loads the model made in Blender (the-ground/out/the_ground.glb, served read-only at
// /ground by api.py) and answers the questions stadium3d.js has about it. stadium3d.js keeps the seats, the camera, the
// picking and the day/night switch; this module only knows the file.
//
// The contract: metres, Y up, the centre spot at the origin, no seats in the file, parts
// found by NAME (never by position in the file), the clickable ones listed in targets.json with a camera pose each.
//
// What it hands back:
//   root       the scene graph to add to the scene
//   sections   per stand, how many rows each tier has IN THE FILE (read from the stand's own profile), so the desk's seats
//              always sit on the treads that were exported, whatever the crowd's size is today
//   solids     light copies (world space, with a bounding-volume tree) of the structure the camera must not cross, and of
//              every clickable part: raycasts against 1.1 million triangles would be far too slow, against these they are not
//   targets    the clickable parts: label, camera pose, `show`, their meshes and their pick copies
//   lamps      where the four corner lamp banks stand (the desk lights the night from there)
import * as THREE from "/static/vendor/three.module.min.js";
import { GLTFLoader } from "/static/vendor/GLTFLoader.js";
import { MeshoptDecoder } from "/static/vendor/meshopt_decoder.module.js";
import { MeshBVH, acceleratedRaycast } from "/static/vendor/three-mesh-bvh.js";

// the section constants of the ground (ground.json "section" and "tiers"), the same ones the desk's procedural bowl uses
const FRONT = 2.2, W = 68, L = 105, RUN = 6;
const TIER_DEPTH = { projection: 19, deep: 12 }, TIER_RAKE = { projection: 25, deep: 33 }, KOP_EXTRA = 6;
const STAND_NAMES = { E: "Midfield", W: "Defence", S: "Attack", N: "Goalkeepers" };
const K = { E: 1.0, W: 1.0, S: 1.2, N: 0.75 }, KOP = "S", PALCOS = "N";
const OVER = 4.5, HEAD = 3.4, LIP = 2.6;

// what the camera must not cross: the structure, never the trims (nosings, rails, steps), trees, nets or cables
const SOLID = /^(STAND_[NSEW]_[A-Za-z]+|STAND_cores|STAND_backs_louvres|ROOF_(fascia|membrane|trusses|girders_red|pylons_yellow)|PALCOS_N_structure|CORNERS_bastions_towers|CORNER_\d_ramp|DRESS_(screen|screen_frame|tunnel))$/;
const ROOF = /^ROOF_(fascia|membrane)$/;                       // the parts of the roof that fade as the camera rises
const LAMP_MATS = /^M_(Lamp_Bank|Lamp_Face|Rim_Lamp)/;         // lit at 20:45 (if the kit renames its lamp materials)

const proxyMat = new THREE.MeshBasicMaterial({ side: THREE.DoubleSide });
const proxies = new Map();                                     // mesh -> its light copy
function proxyOf(mesh) {
  if (proxies.has(mesh)) return proxies.get(mesh);
  const g = mesh.geometry, pos = g.attributes.position, arr = new Float32Array(pos.count * 3), v = new THREE.Vector3();
  mesh.updateWorldMatrix(true, false);
  for (let i = 0; i < pos.count; i++) { v.fromBufferAttribute(pos, i).applyMatrix4(mesh.matrixWorld); arr[i * 3] = v.x; arr[i * 3 + 1] = v.y; arr[i * 3 + 2] = v.z; }   // fromBufferAttribute undoes the file's quantisation
  const ng = new THREE.BufferGeometry();
  ng.setAttribute("position", new THREE.BufferAttribute(arr, 3));
  if (g.index) ng.setIndex(new THREE.BufferAttribute(g.index.array.slice(), 1));
  ng.boundsTree = new MeshBVH(ng);
  const p = new THREE.Mesh(ng, proxyMat);
  p.raycast = acceleratedRaycast; p.name = mesh.name; p.userData.source = mesh;
  proxies.set(mesh, p);
  return p;
}

const meshesUnder = (root, name) => { const out = []; root.getObjectByName(name)?.traverse((o) => { if (o.isMesh) out.push(o); }); return out; };

// The rows of a tier: the row count whose treads ALL exist in the profile. A tier starts at out-distance o0, height z0 and is
// `depth` deep at `rakeDeg`; with R rows the r-th tread starts at (o0 + r * depth / R, z0 + r * riser). Only the true R fits every tread.
function fitRows(cap, o0, z0, depth, rakeDeg) {
  const tan = Math.tan((rakeDeg * Math.PI) / 180), has = (o, z) => cap.some(([co, cz]) => Math.abs(co - o) < 0.06 && Math.abs(cz - z) < 0.06);   // the file keeps positions in 16 bits: a few mm of noise
  for (let R = 64; R >= 4; R--) {
    const rd = depth / R, riser = rd * tan;
    let ok = true;
    for (let r = 0; r < R && ok; r++) ok = has(o0 + r * rd, z0 + r * riser);
    if (ok) return R;
  }
  return 0;
}

// a stand's rows, read from its own cross-section: the end cap of the extruded profile, in the stand's frame (o out from
// the front wall, z up). (The Kop is 6 degrees steeper than its tier's rake; the quiet north end has boxes, not an upper tier.)
function sectionOf(root, side) {
  const mesh = root.getObjectByName(`STAND_${side}_${STAND_NAMES[side]}`);
  if (!mesh?.isMesh) return null;
  mesh.updateWorldMatrix(true, false);
  const pos = mesh.geometry.attributes.position, v = new THREE.Vector3(), pts = [];
  const frame = { E: (p) => [p.x, -p.z - (W / 2 + RUN)], W: (p) => [-p.x, p.z - (W / 2 + RUN)], S: (p) => [p.z, p.x - (L / 2 + RUN)], N: (p) => [-p.z, -p.x - (L / 2 + RUN)] }[side];
  let u0 = Infinity;
  for (let i = 0; i < pos.count; i++) { v.fromBufferAttribute(pos, i).applyMatrix4(mesh.matrixWorld); const [u, o] = frame(v); pts.push([u, o, v.y]); u0 = Math.min(u0, u); }
  const cap = pts.filter((p) => Math.abs(p[0] - u0) < 0.05).map((p) => [p[1], p[2]]);
  const k = K[side], extra = side === KOP ? KOP_EXTRA : 0, tan = (d) => Math.tan(((d + extra) * Math.PI) / 180);
  const depthLo = TIER_DEPTH.projection * k, depthUp = TIER_DEPTH.deep * k;
  const lo = fitRows(cap, 0, FRONT, depthLo, TIER_RAKE.projection + extra);
  if (!lo) return null;
  if (side === PALCOS) return { lo, up: 0 };
  const riserLo = (depthLo / lo) * tan(TIER_RAKE.projection), ys = FRONT + lo * riserLo + HEAD;   // FRONT + (lo - 1) * riser + riser + HEAD
  const up = fitRows(cap, depthLo - OVER * k, ys + LIP, depthUp, TIER_RAKE.deep + extra);
  return up ? { lo, up } : null;
}

export async function loadGround(base = "/ground", onProgress) {
  const loader = new GLTFLoader().setMeshoptDecoder(MeshoptDecoder);
  const [doc, gltf] = await Promise.all([
    fetch(`${base}/targets.json`).then((r) => { if (!r.ok) throw new Error(`targets.json ${r.status}`); return r.json(); }),
    loader.loadAsync(`${base}/the_ground.glb`, onProgress),
  ]);
  const root = gltf.scene;
  root.updateMatrixWorld(true);

  const sections = {};
  for (const side of Object.keys(STAND_NAMES)) {
    const s = sectionOf(root, side);
    if (!s) throw new Error(`stand ${side} not found in the file`);
    sections[side] = s;
  }

  // the camera's obstacles, and the parts that fade with the roof
  const solids = [], roofParts = [], roofMats = new Set();
  root.traverse((o) => {
    if (!o.isMesh || !SOLID.test(o.name)) return;
    const p = proxyOf(o); solids.push(p);
    if (ROOF.test(o.name)) { roofParts.push(p); (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => roofMats.add(m)); }
  });

  // the clickable parts, found by name
  const targets = doc.targets.map((t, i) => {
    const meshes = [t.name, ...(t.also || [])].flatMap((n) => meshesUnder(root, n));
    return { ...t, i, meshes, picks: meshes.map(proxyOf), found: meshes.length > 0 };
  });
  const owner = new Map();
  targets.forEach((t) => t.picks.forEach((p) => owner.set(p, t)));
  const pickables = [...new Set([...solids, ...targets.flatMap((t) => t.picks)])];

  // lamps lit at night (materials) and the four lamp banks' places (for the floodlight beams)
  const lampMats = new Set();
  root.traverse((o) => { if (o.isMesh) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => { if (LAMP_MATS.test(m.name)) lampMats.add(m); }); });
  const lamps = [];
  for (const sx of [1, -1]) for (const sz of [-1, 1]) {
    const box = new THREE.Box3(), v = new THREE.Vector3();
    for (const o of meshesUnder(root, "CORNERS_lamp_faces")) {
      o.updateWorldMatrix(true, false);
      const pos = o.geometry.attributes.position;
      for (let i = 0; i < pos.count; i++) { v.fromBufferAttribute(pos, i).applyMatrix4(o.matrixWorld); if (Math.sign(v.x) === sx && Math.sign(v.z) === sz) box.expandByPoint(v); }
    }
    if (!box.isEmpty()) lamps.push(box.getCenter(new THREE.Vector3()));
  }
  // how high the roof's structure (membrane, trusses, the red girders) reaches over each stand: the camera's way out goes above it
  const roofTop = { E: 0, W: 0, S: 0, N: 0 };
  for (const p of solids.filter((m) => /^ROOF_(fascia|membrane|trusses|girders_red)$/.test(m.name))) {
    const pos = p.geometry.attributes.position;
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i), z = pos.getZ(i), side = Math.abs(z) / (W / 2 + RUN) > Math.abs(x) / (L / 2 + RUN) ? (z < 0 ? "E" : "W") : (x > 0 ? "S" : "N");
      roofTop[side] = Math.max(roofTop[side], pos.getY(i));
    }
  }
  const screen = meshesUnder(root, "DRESS_screen");
  const box = new THREE.Box3().setFromObject(root);

  return {
    root, doc, sections, roofTop, solids, roofParts, roofMats: [...roofMats], targets, owner, pickables, lampMats: [...lampMats], lamps, screen, box,
    // the first clickable part along a ray (a part hidden behind structure is not clickable); null when none
    //   skipStands: a stand only counts where no seat is near (the desk takes the seat first); roofOpen: the roof is faded out
    pick(raycaster, { skipStands = false, roofOpen = false } = {}) {
      for (const h of raycaster.intersectObjects(pickables, false)) {
        if (roofOpen && roofParts.includes(h.object)) continue;
        const t = owner.get(h.object);
        if (t) { if (skipStands && t.show?.kind === "stand") return null; return { target: t, hit: h }; }
        return null;                                            // structure in front: nothing clickable behind it
      }
      return null;
    },
    targetByName: (n) => targets.find((t) => t.name === n),
    // night: the lamp materials light up
    setNight(night) { lampMats.forEach((m) => { m.emissive?.set(0xffffff); m.emissiveIntensity = night ? 1.5 : 0; }); },
  };
}

// the outline of a part: its hard edges, drawn on top in the given colour; returns a group to add to the scene
export function outlineOf(target, color) {
  const g = new THREE.Group();
  const mat = new THREE.LineBasicMaterial({ color, depthTest: false, transparent: true });
  for (const p of target.picks) {
    const l = new THREE.LineSegments(new THREE.EdgesGeometry(p.geometry, 28), mat);
    l.renderOrder = 20; l.frustumCulled = false; g.add(l);
  }
  g.userData.mat = mat;
  return g;
}

// a short glow: the part's own materials, copied, lit with an emissive colour that rises and falls; restored after
export function glow(target, color, gsap, seconds = 1.2) {
  const saved = target.meshes.map((m) => m.material);
  const mats = [];
  target.meshes.forEach((m, i) => {
    const copy = Array.isArray(saved[i]) ? saved[i].map((x) => x.clone()) : saved[i].clone();
    (Array.isArray(copy) ? copy : [copy]).forEach((x) => { if (x.emissive) { x.emissive.copy(color); x.emissiveIntensity = 0; mats.push(x); } });
    m.material = copy;
  });
  const done = () => { target.meshes.forEach((m, i) => { m.material = saved[i]; }); };
  if (!gsap) { setTimeout(done, 300); return done; }
  const o = { k: 0 };
  gsap.to(o, { k: 1, duration: seconds * 0.35, ease: "power2.out", onUpdate: () => mats.forEach((x) => { x.emissiveIntensity = o.k * 0.9; }),
    onComplete: () => gsap.to(o, { k: 0, duration: seconds * 0.65, ease: "power2.inOut", onUpdate: () => mats.forEach((x) => { x.emissiveIntensity = o.k * 0.9; }), onComplete: done }) });
  return done;
}
