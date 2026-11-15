'use client';

import { useState } from 'react';
import { compileCapsule, PROVIDERS, SENSITIVITIES, slotLabel, toSlot, type Fact, type Sensitivity } from '@/lib/memty-sim';

const LEVEL_HELP: Record<Sensitivity, string> = {
  PUBLIC: 'Shared with any assistant',
  INTERNAL: 'Only local or trusted assistants',
  CONFIDENTIAL: 'Cloud assistants see [private]',
  SECRET: 'Never leaves your machine',
};

const START: [string, string, Sensitivity][] = [
  ['Database', 'PostgreSQL 16 on Neon', 'PUBLIC'],
  ['Deploy target', 'Fly.io', 'PUBLIC'],
  ['Q1 roadmap', 'Usage-based pricing in March', 'INTERNAL'],
  ['Client', 'Acme Health', 'CONFIDENTIAL'],
  ['Stripe key', 'sk-proj-demo…NOTREAL', 'SECRET'],
];

export default function PrivacyGate() {
  const [facts, setFacts] = useState<Fact[]>(() =>
    START.map(([title, value, sensitivity], i) => ({
      id: `pg_${i}`, namespace: 'work.billing-api', slot: toSlot(title), value, sensitivity,
      verification: 'USER_CONFIRMED', contextId: 'pg', createdAt: i, history: [],
    })),
  );
  const [providerId, setProviderId] = useState('chatgpt');
  const [trusted, setTrusted] = useState(false);

  const provider = PROVIDERS.find((p) => p.id === providerId) ?? PROVIDERS[0];
  const trustedSet = new Set(trusted ? [provider.id] : []);
  const capsule = compileCapsule(facts, provider, trustedSet);
  const decisions = new Map(capsule.decisions.map((d) => [d.fact.id, d.action]));

  const setLevel = (id: string, level: Sensitivity) =>
    setFacts((all) => all.map((f) => (f.id === id ? { ...f, sensitivity: level } : f)));

  return (
    <div className="gate">
      <div className="gate-facts">
        <div className="gate-head">
          <span>Your vault · <code>work.billing-api</code></span>
          <span className="gate-hint">Change a level ↓</span>
        </div>
        {facts.map((f) => {
          const action = decisions.get(f.id);
          return (
            <div key={f.id} className={`gate-row is-${action}`}>
              <div className="gate-fact">
                <b>{slotLabel(f.slot)}</b>
                <span>{f.value}</span>
              </div>
              <div className="gate-levels" role="radiogroup" aria-label={`Sensitivity for ${slotLabel(f.slot)}`}>
                {SENSITIVITIES.map((level) => (
                  <button
                    key={level}
                    type="button"
                    role="radio"
                    aria-checked={f.sensitivity === level}
                    title={LEVEL_HELP[level]}
                    className={`lvl lvl-${level.toLowerCase()} ${f.sensitivity === level ? 'is-on' : ''}`}
                    onClick={() => setLevel(f.id, level)}
                  >
                    {level.slice(0, 4)}
                  </button>
                ))}
              </div>
              <span className={`gate-verdict is-${action}`}>
                {action === 'share' && 'sent'}
                {action === 'redact' && '[private]'}
                {action === 'withhold' && 'withheld'}
                {action === 'stop' && 'blocks send'}
              </span>
            </div>
          );
        })}
      </div>

      <div className="gate-out">
        <div className="gate-providers" role="tablist" aria-label="Assistant">
          {PROVIDERS.map((p) => (
            <button
              key={p.id}
              type="button"
              role="tab"
              aria-selected={p.id === providerId}
              className={`gate-provider ${p.id === providerId ? 'is-on' : ''} ${p.kind === 'local' ? 'is-local' : ''}`}
              onClick={() => setProviderId(p.id)}
            >
              {p.name}
            </button>
          ))}
        </div>
        {provider.kind === 'cloud' && (
          <label className="gate-trust">
            <input type="checkbox" checked={trusted} onChange={(e) => setTrusted(e.target.checked)} />
            <span>Trust {provider.name} <small>(<code>--trusted-provider {provider.id}</code>)</small></span>
          </label>
        )}
        <div className={`gate-screen ${capsule.ok ? '' : 'is-stopped'}`}>
          <div className="gate-screen-head">
            <span>What {provider.name} receives</span>
            {capsule.ok && <span>{capsule.tokens} tokens</span>}
          </div>
          {capsule.ok ? (
            <pre>{capsule.text || '(nothing to send)'}</pre>
          ) : (
            <div className="gate-stop">
              <b>Request stopped. Nothing was sent.</b>
              <p>
                <code>{slotLabel(capsule.stoppedBy!.slot)}</code> is SECRET and {provider.name} is a cloud assistant.
                Memty raises <code>local_routing_required</code> and suggests a local model such as Ollama.
              </p>
            </div>
          )}
        </div>
        <ul className="gate-legend">
          {SENSITIVITIES.map((level) => (
            <li key={level}><span className={`lvl lvl-${level.toLowerCase()} is-on`}>{level}</span>{LEVEL_HELP[level]}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
