import type { Metadata } from 'next';
import Link from 'next/link';
import BlockField from '@/components/landing/block-field';
import HeroVault3D from '@/components/landing/hero-vault-3d';
import InstallFilm from '@/components/landing/install-film';
import PrivacyGate from '@/components/landing/privacy-gate';
import { BENCHMARK_URL, GITHUB_URL, PYPI_URL, SECURITY_URL, SiteFooter, SiteNav } from '@/components/site/brand';
import { CopyCommand, CountUp, Reveal } from '@/components/site/interactive';

export const metadata: Metadata = {
  title: 'Memty: persistent memory for AI assistants and agents',
  description:
    'One private, local memory vault shared by ChatGPT, Claude, Gemini, Perplexity, Cursor and every MCP agent. Tell it once. Every assistant remembers.',
};

const CLIENTS = [
  'ChatGPT', 'Claude.ai', 'Gemini', 'Perplexity', 'Claude Code', 'Codex CLI',
  'Cursor', 'Windsurf', 'VS Code', 'Claude Desktop', 'Ollama', 'Python API',
];

const REPEATS = [
  { tool: 'ChatGPT', when: 'Monday' },
  { tool: 'Claude', when: 'Tuesday' },
  { tool: 'Cursor', when: 'Wednesday' },
  { tool: 'Gemini', when: 'Thursday' },
];

const STEPS = [
  {
    n: '01',
    title: 'Save',
    body: 'Select text in any chat and press ＋ Save to Memty, or call memty_propose from an agent. Facts arrive as proposals you approve.',
    code: '＋ Save to Memty',
  },
  {
    n: '02',
    title: 'Store',
    body: 'Memory becomes small namespace.slot = value facts, at most 40 tokens each, in one SQLite file on your disk. History is kept.',
    code: 'work.billing-api.database = "PostgreSQL 16"',
  },
  {
    n: '03',
    title: 'Gate',
    body: 'Every capsule passes the privacy gate for that assistant. Private values become [private]; secrets stop the request.',
    code: 'Client: [private]',
  },
  {
    n: '04',
    title: 'Recall',
    body: 'Press ⚡ Memty (Alt+M) in a chat, or let MCP agents call memty_sync. Only the relevant facts, under a hard token budget.',
    code: '[Memty context] … [/Memty]',
  },
];

const FEATURES = [
  { title: 'Local-first, for real', body: 'The vault is ~/.memty/ledger.sqlite3. No account, no cloud sync, no telemetry. Facts leave only when you press Send.', tag: 'Ownership' },
  { title: 'Forget means forget', body: 'A forgotten value is erased from the file on disk, including the search index and the write-ahead log.', tag: 'Deletion' },
  { title: 'Credentials are always SECRET', body: 'API keys, tokens, private keys and password lines are stored as SECRET however they are saved.', tag: 'Safety' },
  { title: 'Agents propose, you approve', body: 'memty_propose puts changes in your inbox. Extraction can never overwrite a fact you confirmed or revive one you deleted.', tag: 'Control' },
  { title: 'Zero-token project bootstrap', body: 'memty scan reads your manifests and saves baseline facts with no model and no tokens. Env files give key names only.', tag: 'Speed' },
  { title: 'Receipts for every capsule', body: 'See which facts went to which assistant, with per-fact hit counts, in memty receipts and memty report.', tag: 'Trust' },
  { title: 'Injection-proof capsules', body: 'A stored value cannot close or forge Memty’s context markers, so saved text can’t hijack a chat.', tag: 'Security' },
  { title: '61 adversarial tests', body: 'Every promise on this page is attacked in tests/test_memty_security.py. Run them yourself from a clone.', tag: 'Proof' },
];

export default function Page() {
  return (
    <div className="mt">
      <div className="mt-bg" aria-hidden="true">
        <div className="mt-bg-grid" />
        <BlockField />
        <div className="mt-bg-glow mt-bg-glow-a" />
        <div className="mt-bg-glow mt-bg-glow-b" />
      </div>
      <SiteNav current="home" />

      <main>
        {/* ── Hero ─────────────────────────────────────────── */}
        <section className="hero">
          <div className="hero-copy">
            <a className="mt-pill" href={PYPI_URL} target="_blank" rel="noreferrer">
              <span className="mt-pill-dot" /> v0.2.1 on PyPI · source on GitHub · Fair Source
            </a>
            <h1>
              Your AI forgets.
              <br />
              <span className="mt-grad">Memty remembers.</span>
            </h1>
            <p className="hero-sub">
              Persistent memory for AI assistants and agents. One private vault on <em>your</em> computer,
              shared by ChatGPT, Claude, Gemini, Perplexity, Cursor and every MCP agent.
              Tell it once. Every assistant knows.
            </p>
            <div className="hero-cta">
              <CopyCommand command="pip install memty" />
              <Link className="mt-btn mt-btn-primary" href="/workspace">
                Try it live in your browser <span aria-hidden="true">→</span>
              </Link>
            </div>
            <ul className="hero-proof">
              <li><b>61%</b> fewer input tokens<sup>*</sup></li>
              <li><b>0</b> cloud services</li>
              <li><b>1</b> SQLite file you own</li>
            </ul>
          </div>
          <HeroVault3D />
        </section>

        {/* ── Works with ───────────────────────────────────── */}
        <section className="marquee" aria-label="Works with">
          <div className="marquee-track">
            {[...CLIENTS, ...CLIENTS].map((c, i) => (
              <span key={`${c}-${i}`} className="marquee-item" aria-hidden={i >= CLIENTS.length}>{c}</span>
            ))}
          </div>
        </section>

        {/* ── Problem ──────────────────────────────────────── */}
        <section className="mt-section problem">
          <Reveal className="mt-section-head">
            <p className="mt-eyebrow">The problem</p>
            <h2>Every new chat starts at <em>zero.</em></h2>
            <p>
              You explain your stack, your clients and how you like answers, again and again, to every tool.
              Each tool keeps its own memory, locked inside its own product.
            </p>
          </Reveal>
          <div className="problem-grid">
            <Reveal className="problem-card is-before">
              <div className="problem-card-head"><span className="problem-badge is-bad">Without Memty</span><span>4 tools · 4 re-explanations</span></div>
              <div className="problem-repeats">
                {REPEATS.map((r, i) => (
                  <div key={r.tool} className="problem-repeat" style={{ animationDelay: `${i * 160}ms` }}>
                    <span className="problem-tool">{r.tool} · {r.when}</span>
                    <p>“We use Postgres 16 on Neon, deploy to Fly.io, the client is Acme Health, and please keep answers short…”</p>
                  </div>
                ))}
              </div>
              <div className="problem-meter"><span>Context you paid for</span><b>4×</b></div>
            </Reveal>
            <Reveal className="problem-card is-after" delay={120}>
              <div className="problem-card-head"><span className="problem-badge is-good">With Memty</span><span>told once · recalled everywhere</span></div>
              <pre className="problem-capsule">{`[Memty context]
1. Database: PostgreSQL 16 on Neon
2. Deploy target: Fly.io
3. Client: [private]
4. Answer style: Short, code first
[/Memty]`}</pre>
              <ul className="problem-points">
                <li>Same memory in every assistant and agent</li>
                <li>Only the facts that matter, under a token budget</li>
                <li>Private values stay private, per assistant</li>
              </ul>
              <div className="problem-meter is-good"><span>Context you paid for</span><b>1×</b></div>
            </Reveal>
          </div>
        </section>

        {/* ── How it works ─────────────────────────────────── */}
        <section className="mt-section" id="how">
          <Reveal className="mt-section-head">
            <p className="mt-eyebrow">How it works</p>
            <h2>Four moves. <em>One memory.</em></h2>
            <p>Small facts, kept apart by namespace, compiled into a tiny capsule for each request and checked by a privacy gate.</p>
          </Reveal>
          <div className="steps">
            {STEPS.map((s, i) => (
              <Reveal key={s.n} className="step" delay={i * 90}>
                <span className="step-n">{s.n}</span>
                <h3>{s.title}</h3>
                <p>{s.body}</p>
                <code className="step-code">{s.code}</code>
              </Reveal>
            ))}
          </div>
          <Reveal className="arch">
            <div className="arch-col">
              <span className="arch-label">Chat websites</span>
              <div className="arch-chips"><span>ChatGPT</span><span>Claude.ai</span><span>Gemini</span><span>Perplexity</span></div>
              <span className="arch-via">browser extension → <code>memty serve</code> (127.0.0.1)</span>
            </div>
            <div className="arch-col">
              <span className="arch-label">Desktop &amp; coding agents</span>
              <div className="arch-chips"><span>Claude Code</span><span>Codex CLI</span><span>Cursor</span><span>VS Code</span><span>Windsurf</span></div>
              <span className="arch-via">MCP over stdio → <code>memty mcp</code></span>
            </div>
            <div className="arch-col">
              <span className="arch-label">Everything else</span>
              <div className="arch-chips"><span>memty CLI</span><span>Python API</span><span>memty clip</span></div>
              <span className="arch-via">direct → daemon</span>
            </div>
            {/* Three sources merge into one daemon, which owns the vault file. */}
            <svg className="arch-merge" viewBox="0 0 600 80" preserveAspectRatio="none" aria-hidden="true">
              {[
                'M100 0 V28 Q100 40 112 40 H288 Q300 40 300 52 V80',
                'M300 0 V80',
                'M500 0 V28 Q500 40 488 40 H312 Q300 40 300 52 V80',
              ].map((d, i) => (
                <g key={d}>
                  <path d={d} className="arch-wire" />
                  <path d={d} className="arch-pulse" style={{ animationDelay: `${i * -0.6}s` }} />
                </g>
              ))}
            </svg>
            <div className="arch-link arch-link-merge" aria-hidden="true"><i /></div>
            <div className="arch-node">
              <b>memtyd</b>
              <span>one local daemon per vault</span>
            </div>
            <div className="arch-link" aria-hidden="true"><i /><em>reads &amp; writes</em></div>
            <div className="arch-node is-vault">
              <b>~/.memty/ledger.sqlite3</b>
              <span>your vault: one SQLite file you own</span>
            </div>
          </Reveal>
        </section>

        {/* ── Install film ─────────────────────────────────── */}
        <section className="mt-section install" id="install">
          <Reveal className="mt-section-head">
            <p className="mt-eyebrow">Install in about a minute</p>
            <h2>From <code>pip install</code> to <em>remembered.</em></h2>
            <p>Watch the whole setup, step by step. Pick your OS, pause anywhere, or jump to a step.</p>
          </Reveal>
          <Reveal><InstallFilm /></Reveal>
          <Reveal className="install-quick">
            <div>
              <h3>The whole setup</h3>
              <p>Python 3.10 or newer on Windows, macOS or Linux.</p>
            </div>
            <pre className="install-code">{`pip install memty
memty serve --autostart   # bridge now and at every login
memty extension --open    # then Load unpacked in chrome://extensions
memty connect             # optional: Claude Code, Codex, Cursor, VS Code…`}</pre>
          </Reveal>
        </section>

        {/* ── Privacy gate ─────────────────────────────────── */}
        <section className="mt-section" id="privacy">
          <Reveal className="mt-section-head">
            <p className="mt-eyebrow">The privacy gate</p>
            <h2>Each assistant sees <em>only what it should.</em></h2>
            <p>
              Try it. Change a fact’s level or switch assistants, and watch the capsule change. This runs the same
              rules as the package: PUBLIC is shared, INTERNAL needs trust, CONFIDENTIAL is masked, SECRET never leaves.
            </p>
          </Reveal>
          <Reveal><PrivacyGate /></Reveal>
        </section>

        {/* ── Proof ────────────────────────────────────────── */}
        <section className="mt-section proof" id="proof">
          <Reveal className="mt-section-head">
            <p className="mt-eyebrow">Measured, not promised</p>
            <h2>Less context. <em>Better answers.</em></h2>
          </Reveal>
          <div className="proof-grid">
            <Reveal className="proof-stat">
              <b><CountUp to={61.1} decimals={1} suffix="%" /></b>
              <span>fewer provider-reported input tokens than full document replay</span>
            </Reveal>
            <Reveal className="proof-stat" delay={90}>
              <b><CountUp to={30} />/30</b>
              <span>exact answers with Memty, vs 27/30 for both baselines</span>
            </Reveal>
            <Reveal className="proof-stat" delay={180}>
              <b><CountUp to={1816} /></b>
              <span>average input tokens per run, vs 4,663 for full replay</span>
            </Reveal>
          </div>
          <Reveal className="proof-bars">
            {[
              ['Full document replay', 4663, '27/30'],
              ['Simulated retrieval', 3128.7, '27/30'],
              ['Selected Memty context', 1816, '30/30'],
            ].map(([label, value, exact]) => (
              <div key={label as string} className={`proof-bar ${label === 'Selected Memty context' ? 'is-memty' : ''}`}>
                <span className="proof-bar-label">{label}</span>
                <span className="proof-bar-track"><i style={{ width: `${((value as number) / 4663) * 100}%` }} /></span>
                <span className="proof-bar-value">{Math.round(value as number).toLocaleString('en-US')} · {exact}</span>
              </div>
            ))}
          </Reveal>
          <p className="proof-note">
            <sup>*</sup> Three live runs of one synthetic five-turn architecture handoff between Claude Haiku 5.5 and
            Gemini 2.5 Flash. Encouraging, but one fixture, not proof of universal savings.{' '}
            <a href={BENCHMARK_URL} target="_blank" rel="noreferrer">Read the method and every run →</a>
          </p>
        </section>

        {/* ── Features ─────────────────────────────────────── */}
        <section className="mt-section">
          <Reveal className="mt-section-head">
            <p className="mt-eyebrow">Built for trust</p>
            <h2>Memory you can <em>see, edit and delete.</em></h2>
          </Reveal>
          <div className="features">
            {FEATURES.map((f, i) => (
              <Reveal key={f.title} className="feature" delay={(i % 4) * 70}>
                <span className="feature-tag">{f.tag}</span>
                <h3>{f.title}</h3>
                <p>{f.body}</p>
              </Reveal>
            ))}
          </div>
          <p className="features-more">
            <a href={SECURITY_URL} target="_blank" rel="noreferrer">See how to attack it yourself →</a>
          </p>
        </section>

        {/* ── Final CTA ────────────────────────────────────── */}
        <section className="final">
          <Reveal className="final-card">
            <h2>Tell it once.<br /><span className="mt-grad">Every assistant remembers.</span></h2>
            <p>Free to use, with every line of source on GitHub. Your memory stays in one file on your computer.</p>
            <div className="hero-cta is-center">
              <CopyCommand command="pip install memty" />
              <Link className="mt-btn mt-btn-primary" href="/workspace">Open the demo workspace →</Link>
              <a className="mt-btn mt-btn-ghost" href={GITHUB_URL} target="_blank" rel="noreferrer">Star on GitHub</a>
            </div>
          </Reveal>
        </section>
      </main>

      <SiteFooter />
    </div>
  );
}
