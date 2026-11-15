'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { MemtyLogo } from '@/components/site/brand';
import {
  cliQuote, compileCapsule, extractProposals, looksLikeCredential, PROVIDERS, recall, seedVault,
  SENSITIVITIES, slotLabel, toSlot, uid,
  type Capsule, type Context, type Fact, type Proposal, type Provider, type Sensitivity, type Vault,
} from '@/lib/memty-sim';

/* ------------------------------------------------------------------ */
/* Types and persistence                                               */
/* ------------------------------------------------------------------ */

type Message = { id: string; role: 'user' | 'assistant' | 'system'; text: string; provider: string };
type Receipt = { id: string; at: number; provider: string; facts: number; redacted: number; tokens: number; blocked?: boolean; context: string };
type TaskId = 'save' | 'paste' | 'send' | 'switch' | 'private' | 'secret' | 'forget';
type State = {
  vault: Vault;
  chats: Record<string, Message[]>;
  receipts: Receipt[];
  done: TaskId[];
  firstPasteProvider: string | null;
};

const STORAGE_KEY = 'memty-demo-workspace-v1';

const TASKS: { id: TaskId; title: string; hint: string }[] = [
  { id: 'save', title: 'Save facts from a chat', hint: 'Select text in the reply, press ＋ Save to Memty' },
  { id: 'paste', title: 'Paste with ⚡ Memty', hint: 'Click ⚡ Memty in the composer (or Alt+M)' },
  { id: 'send', title: 'Send with your context', hint: 'Ask a question below the pasted capsule' },
  { id: 'switch', title: 'Switch assistants', hint: 'Open another tab and paste the same context' },
  { id: 'private', title: 'Make a fact private', hint: 'Set a fact to CONF and paste into a cloud tab' },
  { id: 'secret', title: 'Watch a secret get blocked', hint: 'Paste a context holding a SECRET into a cloud tab' },
  { id: 'forget', title: 'Forget a fact', hint: 'Use the trash icon in the vault' },
];

const SAMPLE_REPLY = `Here’s the setup we agreed on for the storefront:

- Frontend: Next.js 15 on Vercel
- Auth: Clerk with Google sign-in
- Queue: Upstash Redis
- Error tracking: Sentry
- Payments API key: sk-proj-demoNOTaREALkey000

We deploy to Vercel from the main branch. Want the checkout flow next?`;

function welcome(provider: Provider): Message[] {
  return [
    {
      id: uid('m'), role: 'system', provider: provider.id,
      text: `This is a simulated ${provider.name} tab. No model is called and nothing leaves your browser.`,
    },
    { id: uid('m'), role: 'user', provider: provider.id, text: 'Can you summarize the stack we picked for the storefront?' },
    { id: uid('m'), role: 'assistant', provider: provider.id, text: SAMPLE_REPLY },
  ];
}

function freshState(): State {
  const chats: Record<string, Message[]> = {};
  PROVIDERS.forEach((p) => {
    chats[p.id] = p.id === 'chatgpt'
      ? welcome(p)
      : [{ id: uid('m'), role: 'system', provider: p.id, text: `New ${p.name} chat. It knows nothing about you yet. Press ⚡ Memty to bring your memory here.` }];
  });
  return { vault: seedVault(), chats, receipts: [], done: [], firstPasteProvider: null };
}

function loadState(): State | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as State;
    if (!parsed?.vault?.facts || !parsed.chats) return null;
    return parsed;
  } catch {
    return null;
  }
}

function saveState(state: State) {
  try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch { /* storage unavailable */ }
}

/* ------------------------------------------------------------------ */
/* Simulated assistant                                                 */
/* ------------------------------------------------------------------ */

const CAPSULE_RE = /\[Memty context\]([\s\S]*?)\[\/Memty\]/;

function simulatedReply(text: string, provider: Provider): string {
  const match = text.match(CAPSULE_RE);
  const question = text.replace(CAPSULE_RE, '').trim();
  if (!match) {
    return `I don’t have any context about you or your project yet, so I’d be guessing. Which stack, deploy target and preferences should I assume?\n\n(Tip: press ⚡ Memty to paste what you’ve already told other assistants.)`;
  }
  const lines = match[1].split('\n').map((l) => l.trim()).filter(Boolean)
    .map((l) => l.replace(/^\d+\.\s*/, ''))
    .map((l) => { const i = l.indexOf(':'); return { label: l.slice(0, i).trim(), value: l.slice(i + 1).trim() }; });
  const privateCount = lines.filter((l) => l.value === '[private]').length;
  const qTerms = new Set((question.toLowerCase().match(/[a-z0-9]+/g) ?? []).filter((w) => w.length > 2));
  const relevant = lines.filter((l) => [...qTerms].some((t) => `${l.label} ${l.value}`.toLowerCase().includes(t)));
  const used = (relevant.length ? relevant : lines).slice(0, 4);
  const bullets = used.map((l) => (l.value === '[private]'
    ? `• ${l.label}: kept private by Memty, so I’ll refer to it generically.`
    : `• ${l.label}: ${l.value}. I’ll build on that.`)).join('\n');
  const ask = question ? `“${question.length > 80 ? `${question.slice(0, 77)}…` : question}”` : 'your next step';
  return `Thanks, I have your Memty context (${lines.length} fact${lines.length === 1 ? '' : 's'}${privateCount ? `, ${privateCount} private` : ''}). For ${ask}, here’s what I’m working from:\n\n${bullets}\n\nNo re-explaining needed. This is where ${provider.name}’s real answer would continue.`;
}

/* ------------------------------------------------------------------ */
/* Small UI pieces                                                     */
/* ------------------------------------------------------------------ */

function Level({ level, onClick, title }: { level: Sensitivity; onClick?: () => void; title?: string }) {
  const short = level === 'CONFIDENTIAL' ? 'CONF' : level;
  if (!onClick) return <span className={`lvl lvl-${level.toLowerCase()} is-on`}>{short}</span>;
  return (
    <button type="button" className={`lvl lvl-${level.toLowerCase()} is-on`} onClick={onClick} title={title ?? 'Change sensitivity'}>
      {short}
    </button>
  );
}

function EditIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round">
      <path d="M10.5 2.5l3 3L5 14H2v-3z" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2.5 4h11M6 4V2.5h4V4M4 4l.7 9.5h6.6L12 4M6.8 7v4M9.2 7v4" />
    </svg>
  );
}

function timeAgo(at: number): string {
  const s = Math.max(1, Math.round((Date.now() - at) / 1000));
  if (s < 60) return 'just now';
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  return `${Math.round(h / 24)} d ago`;
}

/* ------------------------------------------------------------------ */
/* Workspace                                                           */
/* ------------------------------------------------------------------ */

export default function Workspace() {
  const [state, setState] = useState<State | null>(null);
  const [providerId, setProviderId] = useState('chatgpt');
  const [draft, setDraft] = useState('');
  const [nsFilter, setNsFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [pickerOpen, setPickerOpen] = useState(false);
  const [selection, setSelection] = useState<{ text: string; x: number; y: number } | null>(null);
  const [review, setReview] = useState<{ proposals: Proposal[]; namespace: string; title: string } | null>(null);
  const [inspectId, setInspectId] = useState<string | null>(null);
  const [budget, setBudget] = useState(200);
  const [cli, setCli] = useState<string[]>(['memty list --namespace work.billing-api']);
  const [toast, setToast] = useState<{ text: string; tone: 'ok' | 'warn' | 'bad' } | null>(null);
  const [typing, setTyping] = useState(false);
  const [editing, setEditing] = useState<{ id: string; value: string } | null>(null);
  const [adding, setAdding] = useState(false);
  const [mobilePane, setMobilePane] = useState<'vault' | 'chat' | 'inspect'>('chat');
  const transcriptRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { setState(loadState() ?? freshState()); }, []);
  useEffect(() => { if (state) saveState(state); }, [state]);

  const provider = PROVIDERS.find((p) => p.id === providerId) ?? PROVIDERS[0];
  const trusted = useMemo(() => new Set(state?.vault.trusted ?? []), [state?.vault.trusted]);

  const notify = useCallback((text: string, tone: 'ok' | 'warn' | 'bad' = 'ok') => {
    setToast({ text, tone });
    window.setTimeout(() => setToast((t) => (t?.text === text ? null : t)), 3200);
  }, []);

  const complete = useCallback((task: TaskId) => {
    setState((s) => (s && !s.done.includes(task) ? { ...s, done: [...s.done, task] } : s));
  }, []);

  useEffect(() => {
    transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight, behavior: 'smooth' });
  }, [state?.chats, providerId, typing]);

  // Alt+M opens the picker, as the real extension does.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.altKey && (e.key === 'm' || e.key === 'M')) { e.preventDefault(); setPickerOpen((o) => !o); }
      if (e.key === 'Escape') { setPickerOpen(false); setSelection(null); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  if (!state) {
    return <div className="ws-loading"><span className="ws-spinner" /> Opening your demo vault…</div>;
  }

  const { vault } = state;
  const contexts = [...vault.contexts].sort((a, b) => b.createdAt - a.createdAt);
  const factsById = new Map(vault.facts.map((f) => [f.id, f]));
  const namespaces = Array.from(new Set(vault.facts.map((f) => f.namespace))).sort();
  const contextFacts = (ctx: Context) => ctx.factIds.map((id) => factsById.get(id)).filter((f): f is Fact => Boolean(f));

  const inspectContext = contexts.find((c) => c.id === inspectId) ?? contexts[0] ?? null;
  const inspectCapsule: Capsule | null = inspectContext
    ? compileCapsule(contextFacts(inspectContext), provider, trusted, budget)
    : null;

  /* ── vault mutations ─────────────────────────────────────────────── */

  const updateVault = (fn: (v: Vault) => Vault) => setState((s) => (s ? { ...s, vault: fn(s.vault) } : s));

  const cycleLevel = (fact: Fact) => {
    const next = SENSITIVITIES[(SENSITIVITIES.indexOf(fact.sensitivity) + 1) % SENSITIVITIES.length];
    if (fact.sensitivity === 'SECRET' && looksLikeCredential(fact.value)) {
      notify('This looks like a credential, so it stays SECRET. Making a secret public needs the terminal.', 'warn');
      return;
    }
    updateVault((v) => ({ ...v, facts: v.facts.map((f) => (f.id === fact.id ? { ...f, sensitivity: next } : f)) }));
    setCli([`memty remember ${fact.namespace} ${fact.slot} ${cliQuote(fact.value)} --sensitivity ${next}`]);
    if (next === 'CONFIDENTIAL') complete('private');
  };

  const forgetFact = (fact: Fact) => {
    updateVault((v) => ({
      ...v,
      facts: v.facts.filter((f) => f.id !== fact.id),
      contexts: v.contexts
        .map((c) => ({ ...c, factIds: c.factIds.filter((id) => id !== fact.id) }))
        .filter((c) => c.factIds.length > 0),
    }));
    setCli([`memty forget ${fact.namespace} ${fact.slot}`, '# erased from the file on disk, the search index and the WAL']);
    notify(`Forgot “${slotLabel(fact.slot)}”. It’s gone for good.`);
    complete('forget');
  };

  const saveEdit = () => {
    if (!editing) return;
    const fact = factsById.get(editing.id);
    const value = editing.value.trim();
    setEditing(null);
    if (!fact || !value || value === fact.value) return;
    const secret = looksLikeCredential(value);
    updateVault((v) => ({
      ...v,
      facts: v.facts.map((f) => (f.id === fact.id
        ? { ...f, value, sensitivity: secret ? 'SECRET' : f.sensitivity, history: [...f.history, { value, at: Date.now() }] }
        : f)),
    }));
    setCli([
      `memty remember ${fact.namespace} ${fact.slot} ${cliQuote(value)}`,
      `memty history ${fact.namespace} ${fact.slot}   # version ${fact.history.length + 1}, old value kept`,
    ]);
    if (secret) notify('That looks like a credential, so it is now SECRET.', 'warn');
  };

  const addFact = (form: HTMLFormElement) => {
    const data = new FormData(form);
    const namespace = String(data.get('namespace') || 'personal').trim().toLowerCase().replace(/[^a-z0-9._-]/g, '-');
    const title = String(data.get('title') || '').trim();
    const value = String(data.get('value') || '').trim();
    let sensitivity = String(data.get('level') || 'PUBLIC') as Sensitivity;
    if (!title || !value) return;
    if (looksLikeCredential(value)) sensitivity = 'SECRET';
    const now = Date.now();
    const fact: Fact = {
      id: uid('f'), namespace, slot: toSlot(title), value, sensitivity, verification: 'USER_CONFIRMED',
      contextId: null, createdAt: now, history: [{ value, at: now }],
    };
    const ctx: Context = { id: uid('c'), namespace, title, createdAt: now, factIds: [fact.id] };
    fact.contextId = ctx.id;
    updateVault((v) => ({ ...v, facts: [...v.facts, fact], contexts: [...v.contexts, ctx] }));
    setCli([`memty remember ${namespace} ${fact.slot} ${cliQuote(value)}${sensitivity !== 'PUBLIC' ? ` --sensitivity ${sensitivity}` : ''}`]);
    setAdding(false);
    notify(sensitivity === 'SECRET' && String(data.get('level')) !== 'SECRET' ? 'Saved as SECRET: it looks like a credential.' : 'Fact saved to your vault.', sensitivity === 'SECRET' ? 'warn' : 'ok');
  };

  const toggleTrusted = (id: string) => updateVault((v) => ({
    ...v, trusted: v.trusted.includes(id) ? v.trusted.filter((t) => t !== id) : [...v.trusted, id],
  }));

  /* ── chat actions ────────────────────────────────────────────────── */

  const pushMessage = (pid: string, message: Message) =>
    setState((s) => (s ? { ...s, chats: { ...s.chats, [pid]: [...(s.chats[pid] ?? []), message] } } : s));

  const pasteContext = (ctx: Context | 'auto') => {
    setPickerOpen(false);
    let facts: Fact[];
    let label: string;
    if (ctx === 'auto') {
      facts = recall(vault.facts, draft, 6);
      label = 'most relevant';
      if (!facts.length) { notify('No saved facts match yet. Pick a context instead.', 'warn'); return; }
    } else {
      facts = contextFacts(ctx);
      label = ctx.title;
      setInspectId(ctx.id);
    }
    const capsule = compileCapsule(facts, provider, trusted, budget);
    const receipt: Receipt = {
      id: uid('r'), at: Date.now(), provider: provider.name, facts: capsule.included.length,
      redacted: capsule.redacted, tokens: capsule.tokens, blocked: !capsule.ok, context: label,
    };
    setState((s) => (s ? { ...s, receipts: [receipt, ...s.receipts].slice(0, 30) } : s));
    if (!capsule.ok) {
      notify(`Blocked: “${slotLabel(capsule.stoppedBy!.slot)}” is SECRET, so it can’t be pasted into ${provider.name}. Nothing was sent.`, 'bad');
      setCli([`memty clip ${facts[0]?.namespace ?? 'personal'} --provider ${provider.id}`, '# error: local_routing_required (SECRET matched; use a local model)']);
      complete('secret');
      return;
    }
    if (!capsule.text) { notify(`Nothing in “${label}” may be shared with ${provider.name}.`, 'warn'); return; }
    setDraft((d) => `${capsule.text}\n\n${d.replace(CAPSULE_RE, '').trim()}`.trimEnd() + (d.trim() ? '' : '\n'));
    setCli([`memty clip ${facts[0].namespace}${ctx === 'auto' && draft ? ` --query ${cliQuote(draft.slice(0, 40))}` : ''} --provider ${provider.id} --tokens ${budget}`]);
    if (capsule.redacted) complete('private');
    complete('paste');
    setState((s) => {
      if (!s) return s;
      if (s.firstPasteProvider && s.firstPasteProvider !== provider.id && !s.done.includes('switch')) {
        return { ...s, done: [...s.done, 'switch'] };
      }
      return s.firstPasteProvider ? s : { ...s, firstPasteProvider: provider.id };
    });
    notify(`Pasted ${capsule.included.length} fact${capsule.included.length === 1 ? '' : 's'} · ${capsule.tokens} tokens${capsule.redacted ? ` · ${capsule.redacted} private` : ''}. Check it, then send.`);
    window.setTimeout(() => composerRef.current?.focus(), 30);
  };

  const send = () => {
    const text = draft.trim();
    if (!text || typing) return;
    const pid = provider.id;
    pushMessage(pid, { id: uid('m'), role: 'user', provider: pid, text });
    setDraft('');
    setTyping(true);
    if (CAPSULE_RE.test(text)) complete('send');
    window.setTimeout(() => {
      pushMessage(pid, { id: uid('m'), role: 'assistant', provider: pid, text: simulatedReply(text, provider) });
      setTyping(false);
    }, 900);
  };

  const onTranscriptMouseUp = () => {
    const sel = window.getSelection();
    const text = sel?.toString().trim() ?? '';
    const box = transcriptRef.current;
    if (!sel || !text || !box || sel.rangeCount === 0 || !box.contains(sel.anchorNode)) { setSelection(null); return; }
    const rect = sel.getRangeAt(0).getBoundingClientRect();
    const host = box.getBoundingClientRect();
    setSelection({
      text,
      x: Math.min(Math.max(rect.left - host.left + rect.width / 2, 80), host.width - 80),
      y: rect.top - host.top + box.scrollTop - 8,
    });
  };

  const openReview = (text: string) => {
    const proposals = extractProposals(text);
    setSelection(null);
    window.getSelection()?.removeAllRanges();
    if (!proposals.length) { notify('Nothing fact-like in that selection. Try lines like “Key: value”.', 'warn'); return; }
    const firstWords = proposals[0]?.title === 'Note' ? 'Saved from chat' : proposals.slice(0, 2).map((p) => p.title).join(' & ');
    setReview({ proposals, namespace: 'work.storefront', title: firstWords });
  };

  const commitReview = () => {
    if (!review) return;
    const chosen = review.proposals.filter((p) => p.selected && p.title.trim() && p.value.trim());
    if (!chosen.length) { setReview(null); return; }
    const namespace = review.namespace.trim().toLowerCase().replace(/[^a-z0-9._-]/g, '-') || 'personal';
    const now = Date.now();
    const ctx: Context = { id: uid('c'), namespace, title: review.title.trim() || 'Saved from chat', createdAt: now, factIds: [] };
    const facts: Fact[] = chosen.map((p, i) => {
      const sensitivity: Sensitivity = looksLikeCredential(p.value) ? 'SECRET' : p.sensitivity;
      return {
        id: uid('f'), namespace, slot: toSlot(p.title), value: p.value.trim(), sensitivity,
        verification: 'USER_CONFIRMED', contextId: ctx.id, createdAt: now + i, history: [{ value: p.value.trim(), at: now }],
      };
    });
    ctx.factIds = facts.map((f) => f.id);
    updateVault((v) => ({ ...v, facts: [...v.facts, ...facts], contexts: [...v.contexts, ctx] }));
    setInspectId(ctx.id);
    setNsFilter('all');
    setReview(null);
    setCli([
      '# the extension saves through the local bridge; the same facts from a terminal:',
      ...facts.slice(0, 4).map((f) => `memty remember ${namespace} ${f.slot} ${cliQuote(f.sensitivity === 'SECRET' ? '•••' : f.value)}${f.sensitivity !== 'PUBLIC' ? ` --sensitivity ${f.sensitivity}` : ''}`),
    ]);
    const secrets = facts.filter((f) => f.sensitivity === 'SECRET').length;
    notify(`Saved ${facts.length} fact${facts.length === 1 ? '' : 's'} as “${ctx.title}”${secrets ? ` · ${secrets} stored as SECRET` : ''}.`, secrets ? 'warn' : 'ok');
    complete('save');
  };

  const reset = () => {
    try { window.localStorage.removeItem(STORAGE_KEY); } catch { /* ignore */ }
    setState(freshState());
    setProviderId('chatgpt');
    setDraft('');
    setInspectId(null);
    setCli(['memty list --namespace work.billing-api']);
    notify('Demo reset to a fresh vault.');
  };

  /* ── render ──────────────────────────────────────────────────────── */

  const visibleContexts = contexts.filter((ctx) => {
    if (nsFilter !== 'all' && ctx.namespace !== nsFilter) return false;
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return ctx.title.toLowerCase().includes(q) || contextFacts(ctx).some((f) => `${slotLabel(f.slot)} ${f.value}`.toLowerCase().includes(q));
  });
  const messages = state.chats[provider.id] ?? [];
  const progress = Math.round((state.done.length / TASKS.length) * 100);
  const totalTokens = vault.facts.reduce((n, f) => n + Math.max(1, Math.ceil(`${slotLabel(f.slot)}: ${f.value}`.length / 4)), 0);

  return (
    <div className="ws" data-pane={mobilePane}>
      {/* top bar */}
      <header className="ws-top">
        <MemtyLogo />
        <span className="ws-badge">Demo workspace</span>
        <span className="ws-local"><i /> Runs in your browser · nothing is uploaded</span>
        <div className="ws-top-actions">
          <div className="ws-progress" title={`${state.done.length} of ${TASKS.length} tour steps done`}>
            <span>Tour</span><span className="ws-progress-bar"><i style={{ width: `${progress}%` }} /></span><b>{state.done.length}/{TASKS.length}</b>
          </div>
          <button type="button" className="mt-btn mt-btn-ghost mt-btn-sm" onClick={reset}>Reset</button>
          <Link className="mt-btn mt-btn-primary mt-btn-sm" href="/#install">Install Memty</Link>
        </div>
      </header>

      <nav className="ws-tabs" aria-label="Workspace panes">
        {(['vault', 'chat', 'inspect'] as const).map((p) => (
          <button key={p} type="button" className={mobilePane === p ? 'is-on' : ''} onClick={() => setMobilePane(p)}>
            {p === 'vault' ? `Vault (${vault.facts.length})` : p === 'chat' ? 'Chat' : `Inspector ${state.done.length}/${TASKS.length}`}
          </button>
        ))}
      </nav>

      <div className="ws-grid">
        {/* ── Vault pane ─────────────────────────────────────── */}
        <aside className="ws-pane ws-vault" aria-label="Your vault">
          <div className="ws-pane-head">
            <div>
              <h2>Your vault</h2>
              <code className="ws-path">~/.memty/ledger.sqlite3</code>
            </div>
            <button type="button" className="ws-icon-btn" onClick={() => setAdding((a) => !a)} aria-expanded={adding} title="Add a fact">＋</button>
          </div>

          {adding && (
            <form className="ws-add" onSubmit={(e) => { e.preventDefault(); addFact(e.currentTarget); }}>
              <input name="namespace" placeholder="namespace (e.g. personal)" defaultValue={nsFilter !== 'all' ? nsFilter : 'personal'} aria-label="Namespace" />
              <input name="title" placeholder="Title (e.g. Editor)" aria-label="Title" required />
              <input name="value" placeholder="Value (e.g. VS Code)" aria-label="Value" required maxLength={160} />
              <div className="ws-add-row">
                <select name="level" aria-label="Sensitivity" defaultValue="PUBLIC">
                  {SENSITIVITIES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
                <button type="submit" className="mt-btn mt-btn-primary mt-btn-sm">Remember</button>
              </div>
            </form>
          )}

          <div className="ws-filters">
            <input className="ws-search" type="search" placeholder="Search facts" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search facts" />
            <div className="ws-ns">
              {['all', ...namespaces].map((ns) => (
                <button key={ns} type="button" className={nsFilter === ns ? 'is-on' : ''} onClick={() => setNsFilter(ns)}>
                  {ns === 'all' ? 'All' : ns}
                </button>
              ))}
            </div>
          </div>

          <div className="ws-contexts">
            {visibleContexts.length === 0 && <p className="ws-empty">No facts here yet. Select text in the chat and press ＋ Save to Memty.</p>}
            {visibleContexts.map((ctx) => (
              <section key={ctx.id} className={`ws-ctx ${inspectContext?.id === ctx.id ? 'is-inspected' : ''}`}>
                <button type="button" className="ws-ctx-head" onClick={() => setInspectId(ctx.id)} title="Inspect this context">
                  <b>{ctx.title}</b>
                  <span>{ctx.namespace} · {timeAgo(ctx.createdAt)}</span>
                </button>
                {contextFacts(ctx).map((f) => (
                  <div key={f.id} className="ws-fact">
                    <div className="ws-fact-main">
                      <span className="ws-fact-label">{slotLabel(f.slot)}{f.history.length > 1 && <em title={`${f.history.length} versions`}> v{f.history.length}</em>}</span>
                      {editing?.id === f.id ? (
                        <input
                          className="ws-fact-edit" autoFocus value={editing.value}
                          onChange={(e) => setEditing({ id: f.id, value: e.target.value })}
                          onBlur={saveEdit}
                          onKeyDown={(e) => { if (e.key === 'Enter') saveEdit(); if (e.key === 'Escape') setEditing(null); }}
                          aria-label={`Edit ${slotLabel(f.slot)}`}
                        />
                      ) : (
                        <span className={`ws-fact-value ${f.sensitivity === 'SECRET' ? 'is-secret' : ''}`}>
                          {f.sensitivity === 'SECRET' ? '•••••••• (stays on this device)' : f.value}
                        </span>
                      )}
                    </div>
                    <div className="ws-fact-actions">
                      <Level level={f.sensitivity} onClick={() => cycleLevel(f)} title="Click to change sensitivity" />
                      {f.sensitivity !== 'SECRET' && (
                        <button type="button" className="ws-mini" onClick={() => setEditing({ id: f.id, value: f.value })} aria-label={`Edit ${slotLabel(f.slot)}`} title="Edit"><EditIcon /></button>
                      )}
                      <button type="button" className="ws-mini is-danger" onClick={() => forgetFact(f)} aria-label={`Forget ${slotLabel(f.slot)}`} title="Forget permanently"><TrashIcon /></button>
                    </div>
                  </div>
                ))}
              </section>
            ))}
          </div>

          <div className="ws-vault-foot">
            <span><b>{vault.facts.length}</b> facts</span>
            <span><b>{vault.contexts.length}</b> contexts</span>
            <span><b>{namespaces.length}</b> namespaces</span>
            <span>~{totalTokens} tokens</span>
          </div>
        </aside>

        {/* ── Chat pane ──────────────────────────────────────── */}
        <section className="ws-pane ws-chat" aria-label="Simulated assistant">
          <div className="ws-providers" role="tablist" aria-label="Assistant">
            {PROVIDERS.map((p) => (
              <button
                key={p.id} type="button" role="tab" aria-selected={p.id === provider.id}
                className={`ws-provider ${p.id === provider.id ? 'is-on' : ''} ${p.kind === 'local' ? 'is-local' : ''}`}
                onClick={() => { setProviderId(p.id); setSelection(null); setPickerOpen(false); }}
              >
                <span className="ws-provider-dot" />{p.name}
              </button>
            ))}
          </div>

          <div className="ws-transcript" ref={transcriptRef} onMouseUp={onTranscriptMouseUp} onTouchEnd={() => window.setTimeout(onTranscriptMouseUp, 50)}>
            {messages.map((m) => (
              <div key={m.id} className={`ws-msg is-${m.role}`}>
                {m.role !== 'system' && <span className="ws-msg-who">{m.role === 'user' ? 'You' : provider.name}</span>}
                <div className="ws-msg-text">
                  {m.text.split(CAPSULE_RE).length > 1 ? (
                    <>
                      <pre className="ws-msg-capsule">{m.text.match(CAPSULE_RE)?.[0]}</pre>
                      {m.text.replace(CAPSULE_RE, '').trim() && <p>{m.text.replace(CAPSULE_RE, '').trim()}</p>}
                    </>
                  ) : m.text}
                </div>
              </div>
            ))}
            {typing && <div className="ws-msg is-assistant"><span className="ws-msg-who">{provider.name}</span><div className="ws-typing"><i /><i /><i /></div></div>}
            {messages.length > 0 && provider.id === 'chatgpt' && !state.done.includes('save') && (
              <div className="ws-coach">👆 Select the bullet list above, then press <b>＋ Save to Memty</b>.</div>
            )}
            {selection && (
              <button
                type="button" className="ws-save-pill"
                style={{ left: selection.x, top: selection.y }}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => openReview(selection.text)}
              >
                ＋ Save to Memty
              </button>
            )}
          </div>

          <div className="ws-composer">
            {pickerOpen && (
              <div className="ws-picker" role="dialog" aria-label="Pick a Memty context">
                <div className="ws-picker-head">⚡ Memty · paste into {provider.name}<span>newest first</span></div>
                <button type="button" className="ws-picker-row is-auto" onClick={() => pasteContext('auto')}>
                  <b>✨ Most relevant to my message</b><span>{draft.trim() ? 'ranked by your draft' : 'type a question first for best results'}</span>
                </button>
                {contexts.map((ctx) => {
                  const facts = contextFacts(ctx);
                  const preview = compileCapsule(facts, provider, trusted, budget);
                  return (
                    <button key={ctx.id} type="button" className="ws-picker-row" onClick={() => pasteContext(ctx)}>
                      <b>{ctx.title}</b>
                      <span>
                        {facts.length} fact{facts.length === 1 ? '' : 's'} · {ctx.namespace} · {timeAgo(ctx.createdAt)}
                        {!preview.ok && <em className="is-bad"> · has a SECRET</em>}
                        {preview.ok && preview.redacted > 0 && <em> · {preview.redacted} private</em>}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
            <textarea
              ref={composerRef}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder={`Message ${provider.name}… (Alt+M for ⚡ Memty)`}
              rows={Math.min(9, Math.max(2, draft.split('\n').length))}
              aria-label={`Message ${provider.name}`}
            />
            <div className="ws-composer-bar">
              <button type="button" className={`ws-zap ${pickerOpen ? 'is-on' : ''}`} onClick={() => setPickerOpen((o) => !o)} aria-expanded={pickerOpen}>
                ⚡ Memty <kbd>Alt+M</kbd>
              </button>
              <span className="ws-composer-note">{provider.kind === 'local' ? 'Local model: secrets may be used here' : 'Cloud assistant: privacy gate applies'}</span>
              <button type="button" className="mt-btn mt-btn-primary mt-btn-sm" onClick={send} disabled={!draft.trim() || typing}>Send</button>
            </div>
          </div>
        </section>

        {/* ── Inspector pane ─────────────────────────────────── */}
        <aside className="ws-pane ws-inspect" aria-label="Inspector">
          <div className="ws-card">
            <div className="ws-card-head"><h3>Guided tour</h3><span>{progress}%</span></div>
            <ol className="ws-tasks">
              {TASKS.map((t) => {
                const done = state.done.includes(t.id);
                return (
                  <li key={t.id} className={done ? 'is-done' : ''}>
                    <span className="ws-task-check">{done ? '✓' : ''}</span>
                    <div><b>{t.title}</b><span>{t.hint}</span></div>
                  </li>
                );
              })}
            </ol>
            {progress === 100 && (
              <div className="ws-done">
                You’ve seen the whole loop. Now make it real: <code>pip install memty</code>
              </div>
            )}
          </div>

          <div className="ws-card">
            <div className="ws-card-head">
              <h3>What {provider.name} would receive</h3>
              {inspectCapsule?.ok && <span>{inspectCapsule.tokens} tok</span>}
            </div>
            {inspectContext ? (
              <>
                <p className="ws-card-sub">Context: <b>{inspectContext.title}</b></p>
                {inspectCapsule && !inspectCapsule.ok ? (
                  <div className="ws-blocked">
                    <b>Request stopped</b>
                    <span>“{slotLabel(inspectCapsule.stoppedBy!.slot)}” is SECRET. Cloud assistants never receive it; switch to Ollama (local).</span>
                  </div>
                ) : (
                  <pre className="ws-capsule">{inspectCapsule?.text || '(nothing may be shared)'}</pre>
                )}
                <ul className="ws-decisions">
                  {inspectCapsule?.decisions.map((d) => (
                    <li key={d.fact.id} className={`is-${d.action}`}>
                      <span>{slotLabel(d.fact.slot)}</span>
                      <Level level={d.fact.sensitivity} />
                      <em>
                        {d.action === 'share' && (inspectCapsule.included.includes(d.fact) ? 'sent' : 'over budget')}
                        {d.action === 'redact' && '→ [private]'}
                        {d.action === 'withhold' && 'withheld'}
                        {d.action === 'stop' && 'stops send'}
                      </em>
                    </li>
                  ))}
                </ul>
                <label className="ws-budget">
                  <span>Token budget <b>{budget}</b></span>
                  <input type="range" min={20} max={400} step={10} value={budget} onChange={(e) => setBudget(Number(e.target.value))} />
                </label>
              </>
            ) : <p className="ws-card-sub">Save some facts to see a capsule.</p>}
            <div className="ws-trust">
              <span>Trusted assistants <small>(may see INTERNAL and CONFIDENTIAL)</small></span>
              <div>
                {PROVIDERS.filter((p) => p.kind === 'cloud').map((p) => (
                  <button key={p.id} type="button" className={vault.trusted.includes(p.id) ? 'is-on' : ''} onClick={() => toggleTrusted(p.id)}>
                    {vault.trusted.includes(p.id) ? '✓ ' : ''}{p.name}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="ws-card">
            <div className="ws-card-head"><h3>Same thing in the terminal</h3></div>
            <pre className="ws-cli">{cli.map((line) => (line.startsWith('#') ? line : `$ ${line}`)).join('\n')}</pre>
          </div>

          <div className="ws-card">
            <div className="ws-card-head"><h3>Context receipts</h3><span>no values stored</span></div>
            {state.receipts.length === 0 ? (
              <p className="ws-card-sub">Every capsule leaves a receipt: who got it, how many facts, how many tokens. Paste one to see.</p>
            ) : (
              <ul className="ws-receipts">
                {state.receipts.slice(0, 6).map((r) => (
                  <li key={r.id} className={r.blocked ? 'is-blocked' : ''}>
                    <b>{r.provider}</b>
                    <span>{r.blocked ? 'blocked: SECRET matched' : `${r.facts} facts · ${r.tokens} tok${r.redacted ? ` · ${r.redacted} private` : ''}`}</span>
                    <em>{r.context}</em>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>
      </div>

      {/* ── Review dialog ─────────────────────────────────────── */}
      {review && (
        <div className="ws-modal" role="dialog" aria-modal="true" aria-label="Review facts before saving" onClick={(e) => { if (e.target === e.currentTarget) setReview(null); }}>
          <div className="ws-modal-card">
            <div className="ws-modal-head">
              <h3>Review before saving</h3>
              <p>Memty proposed these facts using local rules: no model, no network. Edit or untick anything.</p>
            </div>
            <div className="ws-modal-meta">
              <label>Namespace<input value={review.namespace} onChange={(e) => setReview({ ...review, namespace: e.target.value })} /></label>
              <label>Context title<input value={review.title} onChange={(e) => setReview({ ...review, title: e.target.value })} /></label>
            </div>
            <div className="ws-proposals">
              {review.proposals.map((p, i) => (
                <div key={p.id} className={`ws-proposal ${p.selected ? '' : 'is-off'}`}>
                  <input
                    type="checkbox" checked={p.selected} aria-label={`Keep ${p.title}`}
                    onChange={(e) => setReview({ ...review, proposals: review.proposals.map((q, j) => (j === i ? { ...q, selected: e.target.checked } : q)) })}
                  />
                  <input
                    className="ws-proposal-title" value={p.title} aria-label="Title"
                    onChange={(e) => setReview({ ...review, proposals: review.proposals.map((q, j) => (j === i ? { ...q, title: e.target.value } : q)) })}
                  />
                  <input
                    className="ws-proposal-value" value={p.value} aria-label="Value"
                    onChange={(e) => {
                      const value = e.target.value;
                      setReview({
                        ...review,
                        proposals: review.proposals.map((q, j) => (j === i
                          ? { ...q, value, sensitivity: looksLikeCredential(value) ? 'SECRET' : q.sensitivity }
                          : q)),
                      });
                    }}
                  />
                  <select
                    value={p.sensitivity} aria-label="Sensitivity"
                    className={`lvl-select lvl-${p.sensitivity.toLowerCase()}`}
                    onChange={(e) => {
                      const level = e.target.value as Sensitivity;
                      if (p.sensitivity === 'SECRET' && looksLikeCredential(p.value) && level !== 'SECRET') {
                        notify('Credentials stay SECRET. Only the terminal can change that.', 'warn');
                        return;
                      }
                      setReview({ ...review, proposals: review.proposals.map((q, j) => (j === i ? { ...q, sensitivity: level } : q)) });
                    }}
                  >
                    {SENSITIVITIES.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                  {p.note && <span className="ws-proposal-note">{p.note}</span>}
                </div>
              ))}
            </div>
            <div className="ws-modal-foot">
              <span>{review.proposals.filter((p) => p.selected).length} of {review.proposals.length} selected · max 40 tokens per fact</span>
              <div>
                <button type="button" className="mt-btn mt-btn-ghost mt-btn-sm" onClick={() => setReview(null)}>Cancel</button>
                <button type="button" className="mt-btn mt-btn-primary mt-btn-sm" onClick={commitReview}>Save to vault</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {toast && <div className={`ws-toast is-${toast.tone}`} role="status">{toast.text}</div>}
    </div>
  );
}
