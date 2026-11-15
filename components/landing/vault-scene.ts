import * as THREE from 'three';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import type { BrandLogo } from '@/components/landing/brand-logos';

/**
 * WebGL scene for the hero: Memty's three-layer vault as glassy extruded slabs,
 * a spiral galaxy of memory particles around it, and the assistants on an orbit.
 * Each cycle a violet comet carries a fact into the vault (the slabs spring apart,
 * the lock opens and snaps shut, a shockwave rolls out), then a green capsule
 * comet flies out to another assistant.
 */

export type VaultSceneOptions = {
  canvas: HTMLCanvasElement;
  labels: HTMLElement[]; // one per assistant, positioned every frame
  packetIn: HTMLElement; // text riding the inbound comet
  packetOut: HTMLElement; // text riding the outbound comet
  count: number; // number of assistants
  logos: (BrandLogo | undefined)[]; // brand mark per assistant, drawn inside its glass orb
  onCycle: (src: number, dst: number) => void;
  onDeliver: (dst: number) => void;
};

const CYCLE = 4.6;
const IN_START = 0.15;
const IN_END = 1.35;
const OUT_START = 1.75;
const OUT_END = 2.95;
const RING_R = 4.05;
const GAP = 0.52;
const SLAB_H = 0.34;
const TRAIL = 120;

const VIOLET = new THREE.Color('#6d5cff');
const LAV = new THREE.Color('#b9b3ff');
const DEEP = new THREE.Color('#3b1ff0');
const GREEN = new THREE.Color('#3ddc97');
const CYAN = new THREE.Color('#67e8f9');
const CELL_REST = new THREE.Color('#5b4ee0');
const WHITE = new THREE.Color('#ffffff');

function glowTexture() {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d')!;
  const grd = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  grd.addColorStop(0, 'rgba(255,255,255,1)');
  grd.addColorStop(0.25, 'rgba(255,255,255,.55)');
  grd.addColorStop(0.6, 'rgba(255,255,255,.12)');
  grd.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grd;
  g.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

/** Draws a brand mark centred on a round disc. The texture sits on a sprite, so it always faces the camera undistorted. */
function logoTexture(logo: BrandLogo) {
  const S = 256;
  const c = document.createElement('canvas');
  c.width = c.height = S;
  const g = c.getContext('2d')!;
  g.beginPath();
  g.arc(S / 2, S / 2, S / 2 - 2, 0, Math.PI * 2);
  g.fillStyle = logo.disc;
  g.fill();
  g.lineWidth = 4;
  g.strokeStyle = 'rgba(255,255,255,.35)';
  g.stroke();
  const box = S * 0.58; // logo size inside the disc
  g.save();
  g.translate((S - box) / 2, (S - box) / 2);
  g.scale(box / 24, box / 24);
  if (logo.ink === 'gemini') {
    const grd = g.createLinearGradient(0, 24, 24, 0);
    grd.addColorStop(0, '#1c7dff');
    grd.addColorStop(0.55, '#9b72cb');
    grd.addColorStop(1, '#d96570');
    g.fillStyle = grd;
  } else {
    g.fillStyle = logo.ink;
  }
  g.fill(new Path2D(logo.path));
  g.restore();
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  return t;
}

function roundedSlab(size: number, r: number) {
  const s = size / 2;
  const shape = new THREE.Shape();
  shape.moveTo(-s + r, -s);
  shape.lineTo(s - r, -s);
  shape.quadraticCurveTo(s, -s, s, -s + r);
  shape.lineTo(s, s - r);
  shape.quadraticCurveTo(s, s, s - r, s);
  shape.lineTo(-s + r, s);
  shape.quadraticCurveTo(-s, s, -s, s - r);
  shape.lineTo(-s, -s + r);
  shape.quadraticCurveTo(-s, -s, -s + r, -s);
  const geo = new THREE.ExtrudeGeometry(shape, {
    depth: 0.22, bevelEnabled: true, bevelThickness: 0.06, bevelSize: 0.06, bevelSegments: 4, curveSegments: 10,
  });
  geo.rotateX(-Math.PI / 2);
  geo.center();
  return geo;
}

const POINT_VERT = /* glsl */ `
  uniform float uTime; uniform float uBoost; uniform float uPixel;
  attribute float aRadius; attribute float aAngle; attribute float aSpeed; attribute float aY; attribute float aSize; attribute vec3 aColor;
  varying vec3 vColor; varying float vAlpha;
  void main() {
    float a = aAngle + uTime * aSpeed + uBoost * aSpeed * 1.8;
    float r = aRadius * (1.0 + uBoost * 0.06);
    vec3 p = vec3(cos(a) * r, aY + sin(uTime * 0.7 + aAngle * 3.0) * 0.06, sin(a) * r);
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = aSize * uPixel * (1.0 + uBoost * 0.8) * (13.0 / -mv.z);
    vColor = aColor;
    vAlpha = 0.75 + 0.5 * uBoost;
  }`;
const POINT_FRAG = /* glsl */ `
  varying vec3 vColor; varying float vAlpha;
  void main() {
    float d = length(gl_PointCoord - 0.5);
    float a = smoothstep(0.5, 0.0, d);
    gl_FragColor = vec4(vColor, a * vAlpha);
  }`;

const TRAIL_VERT = /* glsl */ `
  uniform float uHead; uniform float uPixel;
  attribute float aT;
  varying float vA;
  void main() {
    float k = aT <= uHead ? smoothstep(uHead - 0.45, uHead, aT) : 0.0;
    vA = k;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = (1.5 + 9.0 * k * k) * uPixel * (9.0 / -mv.z);
  }`;
const TRAIL_FRAG = /* glsl */ `
  uniform vec3 uColor; varying float vA;
  void main() {
    if (vA <= 0.001) discard;
    float d = length(gl_PointCoord - 0.5);
    float a = smoothstep(0.5, 0.0, d);
    gl_FragColor = vec4(mix(uColor, vec3(1.0), vA * vA * 0.6), a * vA);
  }`;

export function createVaultScene(opts: VaultSceneOptions) {
  const { canvas, labels, packetIn, packetOut, count, logos, onCycle, onDeliver } = opts;
  const disposables: { dispose(): void }[] = [];
  const keep = <T extends { dispose(): void }>(x: T) => { disposables.push(x); return x; };

  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: 'high-performance' });
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  renderer.setPixelRatio(dpr);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.95;

  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  const envTex = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environment = envTex;
  keep(envTex);
  keep(pmrem);

  const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100);
  const camBase = new THREE.Vector3(0, 3.9, 11.4);
  const look = new THREE.Vector3(0, 0.75, 0);
  camera.position.copy(camBase);

  scene.add(new THREE.AmbientLight(0x8a7dff, 0.55));
  const key = new THREE.DirectionalLight(0xffffff, 1.7);
  key.position.set(3, 7, 5);
  scene.add(key);
  const rim = new THREE.DirectionalLight(0x67e8f9, 0.9);
  rim.position.set(-5, 2, -6);
  scene.add(rim);
  const core = new THREE.PointLight(0x7b6bff, 14, 9, 1.4);
  core.position.set(0, 0.6, 0);
  scene.add(core);

  const glow = keep(glowTexture());
  const sprite = (color: THREE.Color, scale: number, opacity = 1) => {
    const m = keep(new THREE.SpriteMaterial({ map: glow, color, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false }));
    const s = new THREE.Sprite(m);
    s.scale.setScalar(scale);
    return s;
  };

  // ── the vault ─────────────────────────────────────────────
  const vault = new THREE.Group();
  scene.add(vault);
  const slabGeo = keep(roundedSlab(2.5, 0.42));
  const edgeGeo = keep(new THREE.EdgesGeometry(slabGeo, 30));
  const slabs = [DEEP, VIOLET, new THREE.Color('#9a90ff')].map((c, i) => {
    const mat = keep(new THREE.MeshPhysicalMaterial({
      color: c, emissive: c, emissiveIntensity: i === 2 ? 0.16 : 0.42, metalness: 0.15, roughness: 0.18,
      clearcoat: 1, clearcoatRoughness: 0.12, transparent: true, opacity: 0.93, envMapIntensity: 0.9,
    }));
    const mesh = new THREE.Mesh(slabGeo, mat);
    const edges = new THREE.LineSegments(edgeGeo, keep(new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.32 })));
    mesh.add(edges);
    vault.add(mesh);
    return mesh;
  });

  // 3×3 memory cells on the top slab; one lights for each fact that arrives
  const cellGeo = keep(new THREE.BoxGeometry(0.5, 0.05, 0.5));
  const cellMat = keep(new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.9 }));
  const cells = new THREE.InstancedMesh(cellGeo, cellMat, 9);
  const cellLit = new Array(9).fill(-99);
  const tmp = new THREE.Object3D();
  for (let i = 0; i < 9; i++) {
    tmp.position.set(((i % 3) - 1) * 0.66, SLAB_H / 2 + 0.02, (Math.floor(i / 3) - 1) * 0.66);
    tmp.updateMatrix();
    cells.setMatrixAt(i, tmp.matrix);
    cells.setColorAt(i, CELL_REST);
  }
  slabs[2].add(cells);

  // the lock, floating above the top slab
  const lock = new THREE.Group();
  const lockMat = keep(new THREE.MeshPhysicalMaterial({ color: 0x0b0b14, metalness: 0.7, roughness: 0.25, clearcoat: 1, envMapIntensity: 1.2 }));
  const bodyGeo = keep(new THREE.BoxGeometry(0.5, 0.4, 0.2));
  lock.add(new THREE.Mesh(bodyGeo, lockMat));
  const shackleGeo = keep(new THREE.TorusGeometry(0.16, 0.045, 12, 32, Math.PI));
  const shackle = new THREE.Mesh(shackleGeo, lockMat);
  lock.add(shackle);
  const holeGeo = keep(new THREE.SphereGeometry(0.05, 16, 16));
  const holeMat = keep(new THREE.MeshBasicMaterial({ color: LAV }));
  const hole = new THREE.Mesh(holeGeo, holeMat);
  hole.position.set(0, -0.02, 0.105);
  lock.add(hole);
  const lockGlow = sprite(LAV, 1.8, 0.35);
  lock.add(lockGlow);
  lock.scale.setScalar(1.25);
  vault.add(lock);

  const baseGlow = sprite(VIOLET, 9, 0.55);
  baseGlow.position.y = 0.3;
  scene.add(baseGlow);
  const flash = sprite(new THREE.Color('#ffffff'), 4, 0);
  scene.add(flash);

  // shockwave ring
  const waveGeo = keep(new THREE.RingGeometry(0.96, 1.0, 96));
  const waveMat = keep(new THREE.MeshBasicMaterial({ color: LAV, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, side: THREE.DoubleSide, depthWrite: false }));
  const wave = new THREE.Mesh(waveGeo, waveMat);
  wave.rotation.x = -Math.PI / 2;
  scene.add(wave);

  // orbit guides
  const guideMat = keep(new THREE.LineBasicMaterial({ color: LAV, transparent: true, opacity: 0.16 }));
  const circle = (r: number, y: number) => {
    const pts = Array.from({ length: 161 }, (_, i) => {
      const a = (i / 160) * Math.PI * 2;
      return new THREE.Vector3(Math.cos(a) * r, y, Math.sin(a) * r);
    });
    const g = keep(new THREE.BufferGeometry().setFromPoints(pts));
    scene.add(new THREE.Line(g, guideMat));
  };
  circle(RING_R, 0.4);
  circle(2.35, -0.1);

  // ── galaxy of memory particles ───────────────────────────
  const N = 3400;
  const gGeo = keep(new THREE.BufferGeometry());
  const aRadius = new Float32Array(N);
  const aAngle = new Float32Array(N);
  const aSpeed = new Float32Array(N);
  const aY = new Float32Array(N);
  const aSize = new Float32Array(N);
  const aColor = new Float32Array(N * 3);
  const gauss = () => (Math.random() + Math.random() + Math.random() - 1.5) / 1.5;
  const col = new THREE.Color();
  for (let i = 0; i < N; i++) {
    const r = 1.9 + Math.pow(Math.random(), 1.5) * 5.4;
    const arm = i % 3;
    aRadius[i] = r;
    aAngle[i] = arm * ((Math.PI * 2) / 3) + r * 0.85 + gauss() * 0.45;
    aSpeed[i] = 0.55 / Math.pow(r, 1.15);
    aY[i] = gauss() * 0.16 * (r / 3) - 0.1;
    aSize[i] = 0.9 + Math.random() * 2.6;
    const k = (r - 1.9) / 5.4;
    if (Math.random() < 0.08) col.copy(CYAN);
    else col.copy(LAV).lerp(DEEP, k);
    aColor.set([col.r, col.g, col.b], i * 3);
  }
  gGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(N * 3), 3));
  gGeo.setAttribute('aRadius', new THREE.BufferAttribute(aRadius, 1));
  gGeo.setAttribute('aAngle', new THREE.BufferAttribute(aAngle, 1));
  gGeo.setAttribute('aSpeed', new THREE.BufferAttribute(aSpeed, 1));
  gGeo.setAttribute('aY', new THREE.BufferAttribute(aY, 1));
  gGeo.setAttribute('aSize', new THREE.BufferAttribute(aSize, 1));
  gGeo.setAttribute('aColor', new THREE.BufferAttribute(aColor, 3));
  const gUniforms = { uTime: { value: 0 }, uBoost: { value: 0 }, uPixel: { value: dpr } };
  const gMat = keep(new THREE.ShaderMaterial({
    uniforms: gUniforms, vertexShader: POINT_VERT, fragmentShader: POINT_FRAG,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  }));
  const galaxy = new THREE.Points(gGeo, gMat);
  galaxy.frustumCulled = false;
  scene.add(galaxy);

  // ── assistants on the orbit ──────────────────────────────
  // each assistant is a glass orb with its real brand mark floating inside
  const ORB_R = 0.5;
  const nodeGeo = keep(new THREE.SphereGeometry(ORB_R, 48, 32));
  const nodes = Array.from({ length: count }, (_, i) => {
    const mat = keep(new THREE.MeshPhysicalMaterial({
      color: 0xffffff, emissive: VIOLET, emissiveIntensity: 0.15, metalness: 0, roughness: 0.04,
      clearcoat: 1, clearcoatRoughness: 0.03, transparent: true, opacity: 0.22, envMapIntensity: 1.6, depthWrite: false,
    }));
    const mesh = new THREE.Mesh(nodeGeo, mat);
    mesh.renderOrder = 3;
    const logo = logos[i];
    if (logo) {
      const tex = keep(logoTexture(logo));
      const badge = new THREE.Sprite(keep(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false })));
      badge.scale.setScalar(ORB_R * 1.62);
      badge.renderOrder = 2;
      mesh.add(badge);
    }
    const halo = sprite(VIOLET, 1.6, 0.5);
    halo.renderOrder = 1;
    mesh.add(halo);
    scene.add(mesh);
    return { mesh, mat, halo, pulse: 0, glow: 0.5 };
  });

  // ── comets ───────────────────────────────────────────────
  const makeTrail = (color: THREE.Color) => {
    const geo = keep(new THREE.BufferGeometry());
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(TRAIL * 3), 3));
    geo.setAttribute('aT', new THREE.BufferAttribute(Float32Array.from({ length: TRAIL }, (_, i) => i / (TRAIL - 1)), 1));
    const uniforms = { uHead: { value: 0 }, uColor: { value: color }, uPixel: { value: dpr } };
    const mat = keep(new THREE.ShaderMaterial({
      uniforms, vertexShader: TRAIL_VERT, fragmentShader: TRAIL_FRAG,
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    }));
    const pts = new THREE.Points(geo, mat);
    pts.frustumCulled = false;
    const head = sprite(color, 1.3, 0);
    scene.add(pts, head);
    return { geo, uniforms, head, curve: new THREE.QuadraticBezierCurve3() };
  };
  const inbound = makeTrail(VIOLET.clone().lerp(LAV, 0.35));
  const outbound = makeTrail(GREEN);
  const v = new THREE.Vector3();

  const setCurve = (trail: ReturnType<typeof makeTrail>, from: THREE.Vector3, to: THREE.Vector3, lift: number) => {
    const mid = from.clone().add(to).multiplyScalar(0.5);
    mid.y += lift;
    trail.curve.v0.copy(from);
    trail.curve.v1.copy(mid);
    trail.curve.v2.copy(to);
    const arr = trail.geo.attributes.position.array as Float32Array;
    for (let i = 0; i < TRAIL; i++) {
      trail.curve.getPoint(i / (TRAIL - 1), v);
      arr[i * 3] = v.x; arr[i * 3 + 1] = v.y; arr[i * 3 + 2] = v.z;
    }
    trail.geo.attributes.position.needsUpdate = true;
  };

  // ── interaction & sizing ─────────────────────────────────
  const pointer = { x: 0, y: 0, tx: 0, ty: 0 };
  const onMove = (e: PointerEvent) => {
    pointer.tx = (e.clientX / window.innerWidth) * 2 - 1;
    pointer.ty = (e.clientY / window.innerHeight) * 2 - 1;
  };
  window.addEventListener('pointermove', onMove, { passive: true });

  let w = 1;
  let h = 1;
  const resize = () => {
    w = canvas.clientWidth || 1;
    h = canvas.clientHeight || 1;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  const ro = new ResizeObserver(resize);
  ro.observe(canvas);
  resize();

  let visible = true;
  const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; if (visible) loop(); }, { rootMargin: '120px' });
  io.observe(canvas);

  // ── animation state ──────────────────────────────────────
  const clock = new THREE.Clock();
  let t = 0;
  let cycle = -1;
  let src = 0;
  let dst = 3;
  let arrived = false;
  let delivered = false;
  let sep = 0;
  let sepV = 0;
  let boost = 0;
  let lockOpen = 0;
  let arriveAt = -99;
  let cellIdx = 0;
  let raf = 0;
  const vaultTop = new THREE.Vector3();
  const nodePos = (i: number, out: THREE.Vector3) => {
    const a = (i / count) * Math.PI * 2 - Math.PI / 2 + t * 0.07;
    return out.set(Math.cos(a) * RING_R, 0.4 + Math.sin(t * 0.9 + i) * 0.12, Math.sin(a) * RING_R);
  };
  const from = new THREE.Vector3();
  const proj = new THREE.Vector3();
  const ease = (x: number) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);

  const place = (el: HTMLElement, p: THREE.Vector3, dy = 0) => {
    proj.copy(p).project(camera);
    el.style.left = `${(proj.x * 0.5 + 0.5) * w}px`;
    el.style.top = `${(-proj.y * 0.5 + 0.5) * h + dy}px`;
  };

  function loop() {
    cancelAnimationFrame(raf);
    if (!visible || document.hidden) return;
    raf = requestAnimationFrame(loop);
    const dt = Math.min(clock.getDelta(), 0.05);
    t += dt;

    const c = Math.floor(t / CYCLE);
    const ct = t - c * CYCLE;
    if (c !== cycle) {
      cycle = c;
      src = c % count;
      dst = (c + 3) % count;
      arrived = false;
      delivered = false;
      onCycle(src, dst);
    }

    // camera parallax
    pointer.x += (pointer.tx - pointer.x) * 0.04;
    pointer.y += (pointer.ty - pointer.y) * 0.04;
    camera.position.set(camBase.x + pointer.x * 1.6, camBase.y - pointer.y * 1.1, camBase.z);
    camera.lookAt(look);

    // vault: slow spin, springy separation
    vault.rotation.y = t * 0.22 + pointer.x * 0.25;
    vault.position.y = Math.sin(t * 0.8) * 0.08;
    const target = t - arriveAt < 0.35 ? 1 : 0;
    sepV += (target - sep) * 60 * dt;
    sepV *= Math.pow(0.0025, dt);
    sep += sepV * dt;
    slabs.forEach((s, i) => {
      s.position.y = i * (GAP + sep * 0.42 + Math.sin(t * 1.3 + i) * 0.025);
      s.rotation.y = sep * (i - 1) * 0.12;
    });
    const topY = 2 * (GAP + sep * 0.42);
    lockOpen = Math.max(0, lockOpen - dt * 1.8);
    lock.position.y = topY + 0.78 + Math.sin(t * 2) * 0.05;
    lock.rotation.y = -vault.rotation.y + Math.sin(t * 0.6) * 0.5; // keep it facing the camera
    shackle.position.y = 0.2 + ease(Math.min(1, lockOpen)) * 0.16;
    (lockGlow.material as THREE.SpriteMaterial).opacity = 0.3 + lockOpen * 0.6;
    holeMat.color.copy(LAV).lerp(GREEN, Math.min(1, lockOpen));
    vaultTop.set(0, vault.position.y + topY + 0.25, 0);

    // memory cells fade from bright to resting
    for (let i = 0; i < 9; i++) {
      const k = Math.max(0, 1 - (t - cellLit[i]) / 7);
      col.copy(CELL_REST).lerp(WHITE, k * k);
      cells.setColorAt(i, col);
    }
    cells.instanceColor!.needsUpdate = true;

    // galaxy
    boost = Math.max(0, boost - dt * 0.9);
    gUniforms.uTime.value = t;
    gUniforms.uBoost.value = boost;
    galaxy.rotation.x = Math.sin(t * 0.2) * 0.04;
    core.intensity = 14 + boost * 40;
    (baseGlow.material as THREE.SpriteMaterial).opacity = 0.5 + boost * 0.35;

    // nodes
    nodes.forEach((n, i) => {
      nodePos(i, n.mesh.position);
      n.pulse = Math.max(0, n.pulse - dt * 1.2);
      const active = (ct < OUT_START && i === src) || (ct >= OUT_START && i === dst);
      const accent = i === dst && ct >= OUT_START ? GREEN : VIOLET;
      n.glow += ((active ? 1 : 0.35) + n.pulse * 2 - n.glow) * 0.12;
      n.mat.emissive.copy(accent);
      n.mat.emissiveIntensity = 0.1 + n.glow * 0.35;
      n.mesh.scale.setScalar(1 + n.pulse * 0.25 + (active ? 0.08 : 0));
      n.halo.scale.setScalar(1.4 + n.glow * 1.1 + n.pulse * 2);
      const hm = n.halo.material as THREE.SpriteMaterial;
      hm.color.copy(accent);
      hm.opacity = 0.25 + n.glow * 0.45;
      const el = labels[i];
      if (el) {
        const depth = (n.mesh.position.z + RING_R) / (2 * RING_R); // 0 = back, 1 = front
        // labels sit above nodes at the back and below nodes at the front, so they never cover the vault
        place(el, n.mesh.position, depth > 0.5 ? 58 : -48);
        // fade a node's label while it passes right behind or in front of the vault
        const centre = Math.abs(n.mesh.position.x) / RING_R;
        const hide = centre < 0.45 ? (0.45 - centre) / 0.45 : 0;
        el.style.opacity = String((0.5 + depth * 0.5) * (1 - hide * (depth > 0.5 ? 0.35 : 0.85)));
        el.style.zIndex = String(depth > 0.5 ? 3 : 1);
      }
    });

    // inbound comet: fact → vault
    const inK = (ct - IN_START) / (IN_END - IN_START);
    nodePos(src, from);
    setCurve(inbound, from, vaultTop, 2.6);
    const inHead = inK <= 0 ? 0 : inK >= 1 ? 1.5 : ease(inK);
    inbound.uniforms.uHead.value = inHead;
    const inMat = inbound.head.material as THREE.SpriteMaterial;
    if (inK > 0 && inK < 1) {
      inbound.curve.getPoint(inHead, inbound.head.position);
      inMat.opacity = 1;
      place(packetIn, inbound.head.position, -22);
      packetIn.style.opacity = String(Math.min(1, inK * 6, (1 - inK) * 5));
    } else {
      inMat.opacity = 0;
      packetIn.style.opacity = '0';
    }
    if (inK >= 1 && !arrived) {
      arrived = true;
      arriveAt = t;
      sepV += 9;
      boost = 1;
      lockOpen = 1.4;
      cellLit[cellIdx] = t;
      cellIdx = (cellIdx + 4) % 9; // hop around the grid
      nodes[src].pulse = 0.6;
    }

    // shockwave + flash
    const wk = (t - arriveAt) / 1.1;
    if (wk >= 0 && wk <= 1) {
      wave.position.y = vaultTop.y - 0.3;
      wave.scale.setScalar(0.8 + ease(wk) * 4.2);
      waveMat.opacity = (1 - wk) * 0.9;
      (flash.material as THREE.SpriteMaterial).opacity = Math.max(0, 1 - wk * 2.2) * 0.9;
      flash.position.copy(vaultTop);
    } else {
      waveMat.opacity = 0;
      (flash.material as THREE.SpriteMaterial).opacity = 0;
    }

    // outbound comet: capsule → assistant
    const outK = (ct - OUT_START) / (OUT_END - OUT_START);
    nodePos(dst, from);
    setCurve(outbound, vaultTop, from, 2.2);
    const outHead = outK <= 0 ? 0 : outK >= 1 ? 1.5 : ease(outK);
    outbound.uniforms.uHead.value = outHead;
    const outMat = outbound.head.material as THREE.SpriteMaterial;
    if (outK > 0 && outK < 1) {
      outbound.curve.getPoint(outHead, outbound.head.position);
      outMat.opacity = 1;
      place(packetOut, outbound.head.position, -22);
      packetOut.style.opacity = String(Math.min(1, outK * 6, (1 - outK) * 5));
    } else {
      outMat.opacity = 0;
      packetOut.style.opacity = '0';
    }
    if (outK >= 1 && !delivered) {
      delivered = true;
      nodes[dst].pulse = 1;
      onDeliver(dst);
    }

    renderer.render(scene, camera);
  }

  const onVis = () => { clock.getDelta(); loop(); };
  document.addEventListener('visibilitychange', onVis);
  loop();

  return {
    dispose() {
      cancelAnimationFrame(raf);
      visible = false;
      io.disconnect();
      ro.disconnect();
      window.removeEventListener('pointermove', onMove);
      document.removeEventListener('visibilitychange', onVis);
      disposables.forEach((d) => d.dispose());
      renderer.dispose();
    },
  };
}
