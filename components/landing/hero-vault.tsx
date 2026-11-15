'use client';

import { useEffect, useRef, useState } from 'react';
import { usePrefersReducedMotion } from '@/components/site/interactive';
import { compileCapsule, toSlot, type Fact, type Provider, type Sensitivity } from '@/lib/memty-sim';

/**
 * The Vault Stack: Memty's three-layer mark built as a real 3D object.
 * An assistant saves a fact, it sinks into the locked vault, and a capsule rises
 * back out to a different assistant. Pure CSS 3D, no extra dependency.
 */
const NODES: (Provider & { via: string; fact: string })[] = [
  { id: 'chatgpt', name: 'ChatGPT', kind: 'cloud', via: 'extension', fact: 'db = "PostgreSQL 16"' },
  { id: 'claude', name: 'Claude.ai', kind: 'cloud', via: 'extension', fact: 'deploy = "Fly.io"' },
  { id: 'cursor', name: 'Cursor', kind: 'cloud', via: 'MCP', fact: 'style = "code first"' },
  { id: 'ollama', name: 'Ollama', kind: 'local', via: 'local model', fact: 'region = "eu-west"' },
  { id: 'claude_code', name: 'Claude Code', kind: 'cloud', via: 'MCP', fact: 'orm = "Drizzle"' },
  { id: 'gemini', name: 'Gemini', kind: 'cloud', via: 'extension', fact: 'tests = "vitest"' },
];

function fact(title: string, value: string, sensitivity: Sensitivity, i: number): Fact {
  return {
    id: `vs_${i}`, namespace: 'work.billing-api', slot: toSlot(title), value, sensitivity,
    verification: 'USER_CONFIRMED', contextId: 'hero', createdAt: i, history: [],
  };
}

const FACTS: Fact[] = [
  fact('Database', 'PostgreSQL 16 on Neon', 'PUBLIC', 1),
  fact('Deploy target', 'Fly.io', 'PUBLIC', 2),
  fact('Answer style', 'Code first, no filler', 'PUBLIC', 3),
  fact('Client', 'Acme Health', 'CONFIDENTIAL', 4),
];

const RADIUS = 40; // % of the stage
const STEP_MS = 3800;
const OUT_AT = 1400;

const pos = NODES.map((_, i) => {
  const a = (-90 + (360 / NODES.length) * i) * (Math.PI / 180);
  return { x: 50 + RADIUS * Math.cos(a), y: 50 + RADIUS * Math.sin(a) };
});

export default function HeroVault() {
  const reduce = usePrefersReducedMotion();
  const stage = useRef<HTMLDivElement>(null);
  const [step, setStep] = useState(0);
  const [out, setOut] = useState(true); // false while a fact is travelling in, true once the capsule leaves

  const src = step % NODES.length;
  const dst = (step + 3) % NODES.length;

  useEffect(() => {
    if (reduce) return;
    const id = window.setInterval(() => { setStep((s) => s + 1); setOut(false); }, STEP_MS);
    return () => window.clearInterval(id);
  }, [reduce]);

  useEffect(() => {
    if (reduce || out) return;
    const t = window.setTimeout(() => setOut(true), OUT_AT);
    return () => window.clearTimeout(t);
  }, [out, step, reduce]);

  // gentle parallax: the stack leans toward the pointer
  useEffect(() => {
    const el = stage.current;
    if (!el || reduce) return;
    const move = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      const dx = Math.max(-1, Math.min(1, (e.clientX - (r.left + r.width / 2)) / (window.innerWidth / 2)));
      const dy = Math.max(-1, Math.min(1, (e.clientY - (r.top + r.height / 2)) / (window.innerHeight / 2)));
      el.style.setProperty('--tz', `${-45 + dx * 10}deg`);
      el.style.setProperty('--tx', `${58 - dy * 6}deg`);
    };
    window.addEventListener('pointermove', move, { passive: true });
    return () => window.removeEventListener('pointermove', move);
  }, [reduce]);

  const active = out ? dst : src;
  const node = NODES[dst];
  const capsule = compileCapsule(FACTS, node, new Set());

  return (
    <div className="hero-orbit hero-vs" aria-label="Animation: assistants save facts into one locked Memty vault, which sends a capsule to another assistant">
      <div className="hero-orbit-stage vs-stage" ref={stage}>
        <div className="vs-floor" />

        <div className="vs-scene">
          <div className="vs-rig">
            <div className="vs-layer vs-l0" />
            <div className="vs-layer vs-l1" />
            <div key={`pulse-${step}`} className={`vs-layer vs-l2 ${step > 0 || !reduce ? 'is-pulse' : ''}`}>
              <i /><i /><i /><i />
            </div>
            <div className="vs-lock" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="100%" height="100%">
                <rect x="4.5" y="10.5" width="15" height="10.5" rx="2.4" fill="#0b0b14" />
                <path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" fill="none" stroke="#0b0b14" strokeWidth="2.2" />
                <circle cx="12" cy="15.4" r="1.5" fill="#b9b3ff" />
              </svg>
            </div>
          </div>
        </div>

        {NODES.map((n, i) => (
          <div
            key={n.id}
            className={`hero-node ${i === active ? 'is-active' : ''} ${n.kind === 'local' ? 'is-local' : ''}`}
            style={{ left: `${pos[i].x}%`, top: `${pos[i].y}%` }}
          >
            <span className="hero-node-name">{n.name}</span>
            <span className="hero-node-via">{n.via}</span>
          </div>
        ))}

        {!reduce && (
          <>
            <span
              key={`in-${step}`}
              className="vs-packet vs-in"
              style={{ ['--x0' as string]: `${pos[src].x}%`, ['--y0' as string]: `${pos[src].y}%` }}
            >
              {NODES[src].fact}
            </span>
            <span
              key={`out-${step}`}
              className="vs-packet vs-out"
              style={{ ['--x1' as string]: `${pos[dst].x}%`, ['--y1' as string]: `${pos[dst].y}%`, animationDelay: `${OUT_AT}ms` }}
            >
              [Memty] capsule
            </span>
          </>
        )}
      </div>

      <div className="hero-capsule" key={`${dst}-${out}`}>
        <div className="hero-capsule-head">
          <span className={`hero-capsule-dot ${node.kind === 'local' ? 'is-local' : ''}`} />
          <span>Pasted into <b>{node.name}</b></span>
          <span className="hero-capsule-tokens">{capsule.tokens} tokens</span>
        </div>
        <pre className="hero-capsule-body">
          {capsule.text.split('\n').map((line, i) => (
            <span key={i} className={`hero-capsule-line ${line.includes('[private]') ? 'is-private' : ''}`} style={{ animationDelay: `${i * 110}ms` }}>
              {line}{'\n'}
            </span>
          ))}
        </pre>
        <div className="hero-capsule-foot">
          {node.kind === 'local'
            ? 'Local model: CONFIDENTIAL values stay readable on your machine'
            : 'Cloud assistant: the CONFIDENTIAL client name is sent as [private]'}
        </div>
      </div>
    </div>
  );
}
