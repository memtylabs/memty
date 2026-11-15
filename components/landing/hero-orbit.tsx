'use client';

import { useEffect, useMemo, useState } from 'react';
import { MemtyMark } from '@/components/site/brand';
import { usePrefersReducedMotion } from '@/components/site/interactive';
import { compileCapsule, toSlot, type Fact, type Provider, type Sensitivity } from '@/lib/memty-sim';

const NODES: (Provider & { short: string; via: string })[] = [
  { id: 'chatgpt', name: 'ChatGPT', short: 'GPT', kind: 'cloud', via: 'extension' },
  { id: 'claude', name: 'Claude.ai', short: 'C', kind: 'cloud', via: 'extension' },
  { id: 'cursor', name: 'Cursor', short: 'Cu', kind: 'cloud', via: 'MCP' },
  { id: 'ollama', name: 'Ollama', short: 'Ol', kind: 'local', via: 'local model' },
  { id: 'claude_code', name: 'Claude Code', short: 'CC', kind: 'cloud', via: 'MCP' },
  { id: 'gemini', name: 'Gemini', short: 'G', kind: 'cloud', via: 'extension' },
];

function fact(title: string, value: string, sensitivity: Sensitivity, i: number): Fact {
  return {
    id: `hero_${i}`, namespace: 'work.billing-api', slot: toSlot(title), value, sensitivity,
    verification: 'USER_CONFIRMED', contextId: 'hero', createdAt: i, history: [],
  };
}

const FACTS: Fact[] = [
  fact('Database', 'PostgreSQL 16 on Neon', 'PUBLIC', 1),
  fact('Deploy target', 'Fly.io', 'PUBLIC', 2),
  fact('Answer style', 'Code first, no filler', 'PUBLIC', 3),
  fact('Client', 'Acme Health', 'CONFIDENTIAL', 4),
];

const CENTER = 250;
const RADIUS = 186;

export default function HeroOrbit() {
  const reduce = usePrefersReducedMotion();
  const [active, setActive] = useState(0);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (reduce) return;
    const id = window.setInterval(() => {
      setActive((a) => (a + 1) % NODES.length);
      setTick((t) => t + 1);
    }, 3400);
    return () => window.clearInterval(id);
  }, [reduce]);

  const positions = useMemo(
    () => NODES.map((_, i) => {
      const angle = (-90 + (360 / NODES.length) * i) * (Math.PI / 180);
      return { x: CENTER + RADIUS * Math.cos(angle), y: CENTER + RADIUS * Math.sin(angle) };
    }),
    [],
  );

  const node = NODES[active];
  const capsule = compileCapsule(FACTS, node, new Set());
  const target = positions[active];

  return (
    <div className="hero-orbit" aria-label="Animation: one Memty vault sends a context capsule to each assistant">
      <div className="hero-orbit-stage">
        <svg viewBox="0 0 500 500" className="hero-orbit-svg" aria-hidden="true">
          <defs>
            <radialGradient id="orbitGlow" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="#6d5cff" stopOpacity="0.55" />
              <stop offset="60%" stopColor="#3b1ff0" stopOpacity="0.08" />
              <stop offset="100%" stopColor="#3b1ff0" stopOpacity="0" />
            </radialGradient>
            <linearGradient id="beam" x1="0" x2="1">
              <stop offset="0%" stopColor="#b9b3ff" stopOpacity="0.9" />
              <stop offset="100%" stopColor="#6d5cff" stopOpacity="0.2" />
            </linearGradient>
          </defs>
          <circle cx={CENTER} cy={CENTER} r="210" fill="url(#orbitGlow)" />
          <circle cx={CENTER} cy={CENTER} r={RADIUS} className="orbit-ring" />
          <circle cx={CENTER} cy={CENTER} r={RADIUS - 62} className="orbit-ring orbit-ring-inner" />
          {positions.map((p, i) => (
            <line
              key={NODES[i].id}
              x1={CENTER} y1={CENTER} x2={p.x} y2={p.y}
              className={`orbit-spoke ${i === active ? 'is-active' : ''}`}
            />
          ))}
          {!reduce && (
            <circle key={tick} r="6" className="orbit-packet">
              <animateMotion dur="1.05s" fill="freeze" path={`M${CENTER} ${CENTER} L${target.x} ${target.y}`} />
              <animate attributeName="opacity" values="0;1;1;0" keyTimes="0;0.1;0.85;1" dur="1.05s" fill="freeze" />
            </circle>
          )}
        </svg>

        <div className="hero-vault">
          <span className="hero-vault-pulse" />
          <MemtyMark size={56} />
          <span className="hero-vault-label">ledger.sqlite3</span>
        </div>

        {NODES.map((n, i) => (
          <div
            key={n.id}
            className={`hero-node ${i === active ? 'is-active' : ''} ${n.kind === 'local' ? 'is-local' : ''}`}
            style={{ left: `${(positions[i].x / 500) * 100}%`, top: `${(positions[i].y / 500) * 100}%` }}
          >
            <span className="hero-node-name">{n.name}</span>
            <span className="hero-node-via">{n.via}</span>
          </div>
        ))}
      </div>

      <div className="hero-capsule" key={`${active}-${tick}`}>
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
