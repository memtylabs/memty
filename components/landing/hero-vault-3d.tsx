'use client';

import { useEffect, useRef, useState } from 'react';
import { BRAND_LOGOS } from '@/components/landing/brand-logos';
import HeroVault from '@/components/landing/hero-vault';
import { usePrefersReducedMotion } from '@/components/site/interactive';
import { compileCapsule, toSlot, type Fact, type Provider, type Sensitivity } from '@/lib/memty-sim';

/**
 * WebGL version of the Vault Stack. The scene module (and three.js) loads only on
 * the client, after first paint. Falls back to the CSS version when WebGL is not
 * available or the visitor prefers reduced motion.
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
    id: `v3_${i}`, namespace: 'work.billing-api', slot: toSlot(title), value, sensitivity,
    verification: 'USER_CONFIRMED', contextId: 'hero', createdAt: i, history: [],
  };
}

const FACTS: Fact[] = [
  fact('Database', 'PostgreSQL 16 on Neon', 'PUBLIC', 1),
  fact('Deploy target', 'Fly.io', 'PUBLIC', 2),
  fact('Answer style', 'Code first, no filler', 'PUBLIC', 3),
  fact('Client', 'Acme Health', 'CONFIDENTIAL', 4),
];

function hasWebGL() {
  try {
    const c = document.createElement('canvas');
    return !!(c.getContext('webgl2') || c.getContext('webgl'));
  } catch {
    return false;
  }
}

export default function HeroVault3D() {
  const reduce = usePrefersReducedMotion();
  const [gl, setGl] = useState<boolean | null>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const labels = useRef<(HTMLDivElement | null)[]>([]);
  const packetIn = useRef<HTMLSpanElement>(null);
  const packetOut = useRef<HTMLSpanElement>(null);
  const [src, setSrc] = useState(0);
  const [dst, setDst] = useState(3);
  const [shown, setShown] = useState(3);
  const [ready, setReady] = useState(false);

  useEffect(() => { setGl(hasWebGL()); }, []);

  useEffect(() => {
    if (!gl || reduce || !canvas.current || !packetIn.current || !packetOut.current) return;
    let dispose: (() => void) | undefined;
    let cancelled = false;
    import('@/components/landing/vault-scene').then(({ createVaultScene }) => {
      if (cancelled || !canvas.current || !packetIn.current || !packetOut.current) return;
      const scene = createVaultScene({
        canvas: canvas.current,
        labels: labels.current.filter((l): l is HTMLDivElement => !!l),
        packetIn: packetIn.current,
        packetOut: packetOut.current,
        count: NODES.length,
        logos: NODES.map((n) => BRAND_LOGOS[n.id]),
        onCycle: (s, d) => { setSrc(s); setDst(d); },
        onDeliver: (d) => setShown(d),
      });
      dispose = scene.dispose;
      setReady(true);
    }).catch(() => setGl(false));
    return () => { cancelled = true; dispose?.(); };
  }, [gl, reduce]);

  if (gl === false || reduce) return <HeroVault />;

  const node = NODES[shown];
  const capsule = compileCapsule(FACTS, node, new Set());

  return (
    <div className="hero-orbit hero-v3" aria-label="Animation: assistants save facts into one locked Memty vault, which sends a capsule to another assistant">
      <div className="hero-orbit-stage">
        <div className={`v3-layer ${ready ? 'is-ready' : ''}`}>
          <canvas ref={canvas} className="v3-canvas" aria-hidden="true" />
          {NODES.map((n, i) => (
            <div
              key={n.id}
              ref={(el) => { labels.current[i] = el; }}
              className={`v3-node ${i === src ? 'is-src' : ''} ${i === dst ? 'is-dst' : ''} ${n.kind === 'local' ? 'is-local' : ''}`}
            >
              <span className="hero-node-name">{n.name}</span>
              <span className="hero-node-via">{n.via}</span>
            </div>
          ))}
          <span ref={packetIn} className="v3-packet">{NODES[src].fact}</span>
          <span ref={packetOut} className="v3-packet is-out">[Memty] {capsule.tokens} tokens</span>
        </div>
      </div>

      <div className="hero-capsule" key={shown}>
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
