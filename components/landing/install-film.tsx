'use client';

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { MemtyMark } from '@/components/site/brand';
import { usePrefersReducedMotion } from '@/components/site/interactive';

type OS = 'unix' | 'windows';

type Scene = {
  chapter: string;
  title: string;
  benefit: string;
  command: (os: OS) => string;
  output: (os: OS) => string[];
  visual: (t: number) => ReactNode;
};

const DURATION = 7600;
const TYPE_DELAY = 350;
const CHAR_MS = 38;

const home = (os: OS) => (os === 'windows' ? 'C:\\Users\\you\\.memty' : '~/.memty');
const prefix = (os: OS) => (os === 'windows' ? 'py -m memty' : 'memty');

/** Show a step once the scene has played past `at` (0..1). */
const on = (t: number, at: number) => (t >= at ? 'is-on' : '');

const SCENES: Scene[] = [
  {
    chapter: 'Install',
    title: 'One package. Everything inside.',
    benefit: 'Pure Python and the standard library. No account, no API key, no cloud service to sign up for.',
    command: (os) => (os === 'windows' ? 'py -m pip install memty' : 'pip install memty'),
    output: () => ['Collecting memty', 'Installing collected packages: memty', 'Successfully installed memty-0.2.1'],
    visual: (t) => (
      <div className="film-pack">
        <div className={`film-pack-box ${on(t, 0.42)}`}>
          <MemtyMark size={44} />
          <span>memty 0.2.1</span>
        </div>
        <div className="film-pack-grid">
          {[
            ['Vault', 'one SQLite file you own'],
            ['memtyd', 'one daemon per vault'],
            ['MCP server', 'for desktop & coding agents'],
            ['Browser bridge', 'extension + 127.0.0.1 only'],
          ].map(([name, desc], i) => (
            <div key={name} className={`film-pack-tile ${on(t, 0.5 + i * 0.08)}`}>
              <b>{name}</b>
              <span>{desc}</span>
            </div>
          ))}
        </div>
      </div>
    ),
  },
  {
    chapter: 'Start',
    title: 'Start the local bridge once.',
    benefit: 'It starts at every login from now on. It only listens on your own machine and refuses web pages.',
    command: (os) => `${prefix(os)} serve --autostart`,
    output: () => [
      '{',
      '  "running": true,',
      '  "port": 8765,',
      '  "url": "http://127.0.0.1:8765",',
      '  "next": "Load the Memty Bridge extension; it pairs itself automatically."',
      '}',
    ],
    visual: (t) => (
      <div className="film-shield">
        <div className={`film-shield-core ${on(t, 0.4)}`}>
          <svg viewBox="0 0 48 56" width="54" height="62" aria-hidden="true">
            <path d="M24 2 44 9v17c0 13-8.6 23.4-20 28C12.6 49.4 4 39 4 26V9Z" fill="none" stroke="currentColor" strokeWidth="2.5" />
            <path d="m15 28 6.5 6.5L34 22" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <code>127.0.0.1:8765</code>
        </div>
        <ul className="film-checks">
          {[
            'Listens on 127.0.0.1 only',
            'Every request needs a token',
            'Web pages are refused',
            'Host header checked (no DNS rebinding)',
            'Starts again at every login',
          ].map((item, i) => (
            <li key={item} className={on(t, 0.48 + i * 0.07)}>{item}</li>
          ))}
        </ul>
      </div>
    ),
  },
  {
    chapter: 'Extension',
    title: 'Load the browser extension.',
    benefit: 'One time, in Chrome, Edge or Brave. It pairs itself with your vault, so there is no token to copy.',
    command: (os) => `${prefix(os)} extension --open`,
    output: (os) => [
      'Memty Bridge v0.5.1 is ready in:',
      `  ${home(os)}${os === 'windows' ? '\\' : '/'}browser-extension`,
      '',
      'Load it once (Chrome, Edge, or Brave):',
      '  1. Open chrome://extensions (edge://extensions in Edge)',
      '  2. Turn on Developer mode',
      '  3. Click Load unpacked and choose the folder above',
    ],
    visual: (t) => (
      <div className="film-browser">
        <div className="film-browser-bar">
          <span className="film-dots"><i /><i /><i /></span>
          <span className="film-url">chrome://extensions</span>
        </div>
        <div className="film-ext-body">
          <div className="film-ext-top">
            <span>Extensions</span>
            <span className={`film-toggle ${on(t, 0.52)}`}>Developer mode <i /></span>
          </div>
          <div className={`film-ext-actions ${on(t, 0.6)}`}>
            <span className={`film-chip-btn ${on(t, 0.68)}`}>Load unpacked</span>
            <span className="film-chip-btn is-ghost">Pack extension</span>
          </div>
          <div className={`film-ext-card ${on(t, 0.76)}`}>
            <MemtyMark size={34} />
            <div>
              <b>Memty Bridge <small>0.5.1</small></b>
              <span>Select to save, ⚡ to paste, your facts page</span>
            </div>
            <span className={`film-paired ${on(t, 0.86)}`}>Paired ✓</span>
          </div>
        </div>
      </div>
    ),
  },
  {
    chapter: 'Connect',
    title: 'Connect your agents. Same vault.',
    benefit: 'Each client is added through its own official installer. Memty never edits their settings files.',
    command: (os) => `${prefix(os)} connect`,
    output: () => [
      'claude-code     connected',
      'codex           connected',
      'vscode          connected',
      'cursor          manual_step: install link opened',
      'windsurf        manual_step: follow the printed steps',
      'claude-desktop  already_connected',
    ],
    visual: (t) => (
      <div className="film-hub">
        <div className={`film-hub-core ${on(t, 0.3)}`}>
          <MemtyMark size={36} />
          <span>memtyd</span>
        </div>
        {['Claude Code', 'Codex CLI', 'VS Code', 'Cursor', 'Windsurf', 'Claude Desktop'].map((name, i) => (
          <div key={name} className={`film-hub-node n${i} ${on(t, 0.42 + i * 0.075)}`}>
            <span>{name}</span>
          </div>
        ))}
        <svg className="film-hub-lines" viewBox="0 0 400 260" aria-hidden="true" preserveAspectRatio="none">
          {[[60, 40], [200, 22], [340, 40], [60, 220], [200, 238], [340, 220]].map(([x, y], i) => (
            <line key={i} x1="200" y1="130" x2={x} y2={y} className={on(t, 0.42 + i * 0.075)} />
          ))}
        </svg>
      </div>
    ),
  },
  {
    chapter: 'Save',
    title: 'Select text in any chat. Save it.',
    benefit: 'Memty proposes short facts from what you selected. You edit or untick them, then save. You stay in charge.',
    command: (os) => `${prefix(os)} list --namespace work.billing-api`,
    output: () => [
      'work.billing-api.database       PostgreSQL 16 on Neon      PUBLIC',
      'work.billing-api.deploy_target  Fly.io                     PUBLIC',
      'work.billing-api.client         Acme Health                CONFIDENTIAL',
    ],
    visual: (t) => (
      <div className="film-browser">
        <div className="film-browser-bar">
          <span className="film-dots"><i /><i /><i /></span>
          <span className="film-url">chatgpt.com</span>
        </div>
        <div className="film-chat">
          <div className="film-msg is-user">Here is our stack for the billing service.</div>
          <div className="film-msg">
            <span className={`film-select ${on(t, 0.08)}`}>
              Database: PostgreSQL 16 on Neon. Deploy target: Fly.io. Client: Acme Health.
            </span>
            {' '}Want me to draft the migration plan next?
          </div>
          <span className={`film-save-pill ${on(t, 0.18)} ${t >= 0.3 ? 'is-pressed' : ''}`}>＋ Save to Memty</span>
          <div className={`film-review ${on(t, 0.32)}`}>
            <div className="film-review-head">Review 3 facts · <b>work.billing-api</b></div>
            {[
              ['Database', 'PostgreSQL 16 on Neon', ''],
              ['Deploy target', 'Fly.io', ''],
              ['Client', 'Acme Health', 'private'],
            ].map(([k, v, tag], i) => (
              <div key={k} className={`film-review-row ${on(t, 0.38 + i * 0.05)}`}>
                <i className="film-tick" />
                <span><b>{k}:</b> {v}</span>
                {tag && <em className="film-tag">{tag}</em>}
              </div>
            ))}
            <span className={`film-review-save ${on(t, 0.56)} ${t >= 0.64 ? 'is-done' : ''}`}>
              {t >= 0.64 ? 'Saved ✓' : 'Save 3 facts'}
            </span>
          </div>
        </div>
      </div>
    ),
  },
  {
    chapter: 'Recall',
    title: 'Open another assistant. Press ⚡.',
    benefit: 'Alt+M pastes the context into the message box for you to check before sending. No re-explaining, far fewer tokens.',
    command: (os) => `${prefix(os)} recall "where do we deploy?" --namespace work.billing-api`,
    output: () => ['[Memty context]', '1. Deploy target: Fly.io', '2. Database: PostgreSQL 16 on Neon', '[/Memty]'],
    visual: (t) => (
      <div className="film-browser">
        <div className="film-browser-bar">
          <span className="film-dots"><i /><i /><i /></span>
          <span className="film-url">claude.ai</span>
        </div>
        <div className="film-chat">
          <div className={`film-picker ${on(t, 0.12)} ${t >= 0.42 ? 'is-gone' : ''}`}>
            <div className="film-picker-head">⚡ Memty · pick a context</div>
            <div className={`film-picker-row is-hot ${on(t, 0.22)}`}><b>Billing API stack</b><span>3 facts · just now</span></div>
            <div className="film-picker-row"><b>How I like to work</b><span>3 facts · 1 h ago</span></div>
          </div>
          <div className={`film-composer ${on(t, 0.44)}`}>
            <pre>{`[Memty context]
1. Database: PostgreSQL 16 on Neon
2. Deploy target: Fly.io
3. Client: [private]
[/Memty]`}</pre>
            <span className={`film-typed ${on(t, 0.6)}`}>Draft the migration plan for this stack.</span>
            <span className="film-kbd">Alt + M</span>
          </div>
          <div className={`film-msg ${on(t, 0.78)}`}>Got it: Postgres 16 on Neon, deploying to Fly.io. Here’s the plan…</div>
        </div>
      </div>
    ),
  },
];

export default function InstallFilm() {
  const reduce = usePrefersReducedMotion();
  const rootRef = useRef<HTMLDivElement>(null);
  const [os, setOs] = useState<OS>('unix');
  const [scene, setScene] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [visible, setVisible] = useState(false);
  const userPaused = useRef(false);
  const elapsedRef = useRef(0);

  const setElapsedBoth = useCallback((value: number) => {
    elapsedRef.current = value;
    setElapsed(value);
  }, []);

  useEffect(() => {
    if (typeof navigator !== 'undefined' && /Win/i.test(navigator.userAgent)) setOs('windows');
  }, []);

  useEffect(() => {
    const node = rootRef.current;
    if (!node || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver(
      (entries) => setVisible(entries.some((e) => e.isIntersecting)),
      { threshold: 0.35 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (reduce) { setPlaying(false); setElapsedBoth(DURATION); return; }
    if (visible && !userPaused.current) setPlaying(true);
    if (!visible) setPlaying(false);
  }, [visible, reduce, setElapsedBoth]);

  useEffect(() => {
    if (!playing) return;
    let last = performance.now();
    let frame = 0;
    const step = (now: number) => {
      elapsedRef.current += now - last;
      last = now;
      if (elapsedRef.current >= DURATION) {
        elapsedRef.current = 0;
        setScene((s) => (s + 1) % SCENES.length);
      }
      setElapsed(elapsedRef.current);
      frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [playing]);

  const goTo = useCallback((index: number) => {
    setScene((index + SCENES.length) % SCENES.length);
    setElapsedBoth(reduce ? DURATION : 0);
  }, [reduce, setElapsedBoth]);

  const togglePlay = () => {
    userPaused.current = playing;
    if (!playing && elapsed >= DURATION) setElapsedBoth(0);
    setPlaying(!playing);
  };

  const current = SCENES[scene];
  const command = current.command(os);
  const typed = reduce ? command.length : Math.max(0, Math.min(command.length, Math.floor((elapsed - TYPE_DELAY) / CHAR_MS)));
  const typedDone = TYPE_DELAY + command.length * CHAR_MS;
  const outputLines = current.output(os);
  const shownLines = reduce ? outputLines.length : Math.max(0, Math.floor((elapsed - typedDone - 200) / 140));
  const t = Math.min(1, elapsed / DURATION);

  return (
    <div className="film" ref={rootRef}>
      <div className="film-top">
        <ol className="film-chapters" aria-label="Install steps">
          {SCENES.map((s, i) => (
            <li key={s.chapter}>
              <button
                type="button"
                className={`film-chapter ${i === scene ? 'is-current' : ''} ${i < scene ? 'is-done' : ''}`}
                onClick={() => goTo(i)}
                aria-current={i === scene ? 'step' : undefined}
              >
                <span className="film-chapter-num">{String(i + 1).padStart(2, '0')}</span>
                <span className="film-chapter-name">{s.chapter}</span>
                <span className="film-chapter-bar"><i style={{ width: i === scene ? `${t * 100}%` : i < scene ? '100%' : '0%' }} /></span>
              </button>
            </li>
          ))}
        </ol>
        <div className="film-controls">
          <div className="film-os" role="group" aria-label="Operating system">
            <button type="button" className={os === 'unix' ? 'is-on' : ''} onClick={() => setOs('unix')}>macOS / Linux</button>
            <button type="button" className={os === 'windows' ? 'is-on' : ''} onClick={() => setOs('windows')}>Windows</button>
          </div>
          <button type="button" className="film-ctl" onClick={() => goTo(scene - 1)} aria-label="Previous step">‹</button>
          <button type="button" className="film-ctl film-ctl-play" onClick={togglePlay} aria-label={playing ? 'Pause' : 'Play'}>
            {playing ? (
              <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><rect x="2" y="1" width="3.5" height="12" rx="1" fill="currentColor" /><rect x="8.5" y="1" width="3.5" height="12" rx="1" fill="currentColor" /></svg>
            ) : (
              <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M3 1.5v11l9-5.5Z" fill="currentColor" /></svg>
            )}
          </button>
          <button type="button" className="film-ctl" onClick={() => goTo(scene + 1)} aria-label="Next step">›</button>
        </div>
      </div>

      <div className="film-caption" key={`cap-${scene}`}>
        <h3>{current.title}</h3>
        <p>{current.benefit}</p>
      </div>

      <div className="film-stage">
        <div className="film-term" aria-label="Terminal">
          <div className="film-term-bar">
            <span className="film-dots"><i /><i /><i /></span>
            <span>{os === 'windows' ? 'PowerShell' : 'Terminal'}</span>
          </div>
          <pre className="film-term-body">
            <span className="film-term-prompt">{os === 'windows' ? 'PS> ' : '$ '}</span>
            <span className="film-term-cmd">{command.slice(0, typed)}</span>
            {typed < command.length && <span className="film-caret" />}
            {'\n'}
            {outputLines.slice(0, shownLines).map((line, i) => (
              <span key={`${scene}-${i}`} className="film-term-out">{line}{'\n'}</span>
            ))}
            {typed >= command.length && shownLines >= outputLines.length && (
              <>
                <span className="film-term-prompt">{os === 'windows' ? 'PS> ' : '$ '}</span>
                <span className="film-caret" />
              </>
            )}
          </pre>
        </div>
        <div className="film-visual" key={`vis-${scene}`}>{current.visual(t)}</div>
      </div>
    </div>
  );
}
