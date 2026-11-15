'use client';

import { useEffect, useRef } from 'react';

/**
 * Random 3D tiles that glow across the landing page background. Tiles sit on the
 * same 56px grid as the background lines, light up at random, hold for HOLD ms,
 * then drop and fade out one by one.
 */
const CELL = 56;
const HOLD = 1500; // ms a tile stays lit
const RISE = 140; // ms to lift
const FALL = 520; // ms to fade out
const MAX_LIFT = 7;
const AMBIENT_EVERY = 380; // ms between new random tiles

// [top, side, glow] per palette: violet, lavender, cyan
const PALETTES = [
  ['#8b7bff', '#3b1ff0', 'rgba(109,92,255,.9)'],
  ['#cfcaff', '#6d5cff', 'rgba(185,179,255,.85)'],
  ['#8be9f7', '#2a8fa6', 'rgba(103,232,249,.8)'],
];

type Lit = { born: number; palette: number };

export default function BlockField() {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const lit = new Map<string, Lit>();
    let w = 0;
    let h = 0;
    let ox = 0; // canvas offset inside the page grid, so tiles line up with the background lines
    let oy = 0;
    let raf = 0;
    let lastAmbient = 0;

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = canvas.clientWidth;
      h = canvas.clientHeight;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const origin = (canvas.closest('.mt') ?? document.body).getBoundingClientRect();
      const c = canvas.getBoundingClientRect();
      ox = (((c.left - origin.left) % CELL) + CELL) % CELL;
      oy = (((c.top - origin.top) % CELL) + CELL) % CELL;
    };
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    resize();

    const light = (cx: number, cy: number, now: number) => {
      const left = cx * CELL - ox;
      const top = cy * CELL - oy;
      if (left + CELL <= 0 || top + CELL <= 0 || left >= w || top >= h) return;
      const key = `${cx},${cy}`;
      const cur = lit.get(key);
      // re-hovering a tile that is still holding refreshes it; one that is falling re-lights
      if (cur && now - cur.born < HOLD) return;
      const r = Math.abs(cx * 73856093 ^ cy * 19349663) % 100;
      lit.set(key, { born: now, palette: r < 60 ? 0 : r < 85 ? 1 : 2 });
    };

    const draw = (now: number) => {
      ctx.clearRect(0, 0, w, h);

      if (!reduced && now - lastAmbient > AMBIENT_EVERY && document.visibilityState === 'visible') {
        lastAmbient = now;
        const n = 1 + Math.floor(Math.random() * 2);
        for (let i = 0; i < n; i++) {
          light(Math.floor((Math.random() * w + ox) / CELL), Math.floor((Math.random() * h + oy) / CELL), now);
        }
      }

      for (const [key, t] of lit) {
        const age = now - t.born;
        if (age > HOLD + FALL) { lit.delete(key); continue; }
        const up = Math.min(age / RISE, 1);
        const down = age > HOLD ? 1 - (age - HOLD) / FALL : 1;
        const k = up * down;
        const [cx, cy] = key.split(',').map(Number);
        const [top, side, glow] = PALETTES[t.palette];
        const lift = reduced ? 0 : MAX_LIFT * k;
        const x = cx * CELL - ox + 1;
        const y = cy * CELL - oy + 1;
        const s = CELL - 2;

        ctx.save();
        ctx.globalAlpha = Math.min(0.28, k * 0.28);
        // front face gives the block its depth
        ctx.fillStyle = side;
        ctx.beginPath();
        ctx.moveTo(x, y + s - lift);
        ctx.lineTo(x + s, y + s - lift);
        ctx.lineTo(x + s, y + s);
        ctx.lineTo(x, y + s);
        ctx.closePath();
        ctx.fill();
        // glowing top face
        ctx.shadowColor = glow;
        ctx.shadowBlur = 18 * k;
        const g = ctx.createLinearGradient(x, y - lift, x + s, y + s - lift);
        g.addColorStop(0, top);
        g.addColorStop(1, side);
        ctx.fillStyle = g;
        ctx.globalAlpha = Math.min(0.32, k * 0.32);
        ctx.fillRect(x, y - lift, s, s);
        ctx.shadowBlur = 0;
        ctx.strokeStyle = 'rgba(255,255,255,.35)';
        ctx.lineWidth = 1;
        ctx.strokeRect(x + 0.5, y - lift + 0.5, s - 1, s - 1);
        ctx.restore();
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, []);

  return <canvas ref={ref} className="mt-bg-blocks" aria-hidden="true" />;
}
