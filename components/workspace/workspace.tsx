'use client';

import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { BRAND_LOGOS } from '@/components/landing/brand-logos';
import { MemtyMark } from '@/components/site/brand';
import {
  cliQuote, compileCapsule, estimateTokens, extractProposals, looksLikeCredential, PROVIDERS, recall, seedVault,
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
  { id: 'save', title: 'Save facts from a chat', hint: 'Highlight text in the reply, then click Save to Memty' },
  { id: 'paste', title: 'Insert your memory', hint: 'Click Memty in the composer, or press Alt+M' },
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
      : [{ id: uid('m'), role: 'system', provider: p.id, text: `New ${p.name} chat. It knows nothing about you yet. Click Memty below to bring your memory here.` }];
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
    return `I don’t have any context about you or your project yet, so I’d be guessing. Which stack, deploy target and preferences should I assume?\n\n(Tip: click Memty below the message box to paste what you’ve already told other assistants.)`;
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

const LEVEL_LABEL: Record<Sensitivity, string> = {
  PUBLIC: 'Public', INTERNAL: 'Internal', CONFIDENTIAL: 'Confidential', SECRET: 'Secret',
};

function LevelTag({ level, onClick }: { level: Sensitivity; onClick?: () => void }) {
  const cls = `wx-level is-${level.toLowerCase()}`;
  if (!onClick) return <span className={cls}><i />{LEVEL_LABEL[level]}</span>;
  return (
    <button type="button" className={`${cls} is-button`} onClick={onClick} title="Change sensitivity">
      <i />{LEVEL_LABEL[level]}
    </button>
  );
}

const ICONS: Record<string, string> = {
  plus: 'M12 5v14M5 12h14',
  search: 'M4 11a7 7 0 1 0 14 0a7 7 0 1 0-14 0M20 20l-3.5-3.5',
  edit: 'M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z',
  trash: 'M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6',
  lock: 'M7 11h10a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2v-6a2 2 0 0 1 2-2ZM8 11V7a4 4 0 0 1 8 0v4',
  reset: 'M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5',
  info: 'M2 12a10 10 0 1 0 20 0a10 10 0 1 0-20 0M12 16v-4M12 8h.01',
  arrowUp: 'M12 19V5M5 12l7-7 7 7',
  sparkles: 'M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9ZM19 3v4M17 5h4',
  check: 'M20 6 9 17l-5-5',
  alert: 'M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z',
  ban: 'M2 12a10 10 0 1 0 20 0a10 10 0 1 0-20 0M4.9 4.9l14.2 14.2',
  eyeOff: 'M9.9 4.2A10 10 0 0 1 12 4c7 0 10 8 10 8a13 13 0 0 1-1.7 2.7M6.6 6.6A13 13 0 0 0 2 12s3 8 10 8a9.7 9.7 0 0 0 5.4-1.6M2 2l20 20M9.9 9.9a3 3 0 0 0 4.2 4.2',
  minus: 'M5 12h14',
  cursor: 'M4 4l7 17 2.5-7.5L21 11Z',
  copy: 'M11 9h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-8a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2ZM5 15V5a2 2 0 0 1 2-2h10',
  terminal: 'm4 17 6-6-6-6M12 19h8',
  receipt: 'M5 2v20l2.5-1.5L10 22l2-1.5 2 1.5 2.5-1.5L19 22V2l-2.5 1.5L14 2l-2 1.5L10 2 7.5 3.5ZM9 8h6M9 12h6M9 16h4',
  flag: 'M4 22V15M4 15V4a1 1 0 0 1 1-1h12l-2.5 5L17 13H4',
  box: 'M21 8 12 3 3 8v8l9 5 9-5ZM3 8l9 5 9-5M12 13v8',
  x: 'M18 6 6 18M6 6l12 12',
  chevron: 'm6 9 6 6 6-6',
};

function Icon({ name, size = 16, className }: { name: keyof typeof ICONS; size?: number; className?: string }) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d={ICONS[name]} />
    </svg>
  );
}

/** An assistant's real brand mark on its disc (paths from Simple Icons, see brand-logos.ts). */
function BrandIcon({ id, size = 18 }: { id: string; size?: number }) {
  const gid = useId();
  const logo = BRAND_LOGOS[id];
  if (!logo) return <span className="wx-brand-fallback" style={{ width: size, height: size }} />;
  const fill = logo.ink === 'gemini' ? `url(#${gid})` : logo.ink;
  return (
    <svg className="wx-brand-icon" width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      {logo.ink === 'gemini' && (
        <defs>
          <linearGradient id={gid} x1="0" y1="1" x2="1" y2="0">
            <stop offset="0" stopColor="#1c7dff" /><stop offset=".55" stopColor="#9b72cb" /><stop offset="1" stopColor="#d96570" />
          </linearGradient>
        </defs>
      )}
      <circle cx="12" cy="12" r="12" fill={logo.disc} />
      <g transform="translate(5.2 5.2) scale(0.5667)"><path d={logo.path} fill={fill} /></g>
    </svg>
  );
}

function Ring({ value, size = 16 }: { value: number; size?: number }) {
  const r = 6.5;
  const c = 2 * Math.PI * r;
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true" className="wx-ring">
      <circle cx="8" cy="8" r={r} fill="none" strokeWidth="2" className="wx-ring-track" />
      <circle cx="8" cy="8" r={r} fill="none" strokeWidth="2" className="wx-ring-fill"
        strokeDasharray={c} strokeDashoffset={c * (1 - value / 100)} transform="rotate(-90 8 8)" strokeLinecap="round" />
    </svg>
  );
}

/** The capsule a user pasted, shown as an attachment card inside their message. */
function CapsuleCard({ text }: { text: string }) {
  const body = text.match(CAPSULE_RE)?.[1] ?? '';
  const lines = body.split('\n').map((l) => l.trim()).filter(Boolean).map((l) => l.replace(/^\d+\.\s*/, ''));
  return (
    <div className="wx-attach">
      <div className="wx-attach-head">
        <MemtyMark size={14} />
        <b>Memty context</b>
        <span>{lines.length} fact{lines.length === 1 ? '' : 's'} · {estimateTokens(text.match(CAPSULE_RE)?.[0] ?? '')} tokens</span>
      </div>
      <ul>
        {lines.map((l, i) => {
          const at = l.indexOf(':');
          const key = at > 0 ? l.slice(0, at) : l;
          const value = at > 0 ? l.slice(at + 1).trim() : '';
          return (
            <li key={i}>
              <span>{key}</span>
              <em className={value === '[private]' ? 'is-private' : ''}>{value === '[private]' ? 'private' : value}</em>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function timeAgo(at: number): string {
  const s = Math.max(1, Math.round((Date.now() - at) / 1000));
  if (s < 60) return 'just now';
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

type InspectorTab = 'tour' | 'capsule' | 'terminal' | 'receipts';

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
  const [itab, setItab] = useState<InspectorTab>('tour');
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
    return <div className="wx-loading"><span className="wx-spinner" /> Opening your demo vault…</div>;
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
  const currentTask = TASKS.find((t) => !state.done.includes(t.id));
  const nsCount = (ns: string) => (ns === 'all' ? vault.facts.length : vault.facts.filter((f) => f.namespace === ns).length);
  const shortName = (p: Provider) => p.name.replace(' (local)', '');
  const providerByName = (name: string) => PROVIDERS.find((p) => p.name === name);
  const copyCapsule = () => {
    if (!inspectCapsule?.text) return;
    navigator.clipboard?.writeText(inspectCapsule.text).then(() => notify('Capsule copied to the clipboard.'), () => notify('Copy is not available here.', 'warn'));
  };
  const openTab = (t: InspectorTab) => { setItab(t); setMobilePane('inspect'); };

  return (
    <div className="wx" data-pane={mobilePane}>
      {/* ── top bar ─────────────────────────────────────────── */}
      <header className="wx-top">
        <Link href="/" className="wx-home" aria-label="Memty home">
          <MemtyMark size={22} />
          <span>Memty</span>
        </Link>
        <span className="wx-sep" aria-hidden="true">/</span>
        <span className="wx-crumb">Demo workspace</span>
        <span className="wx-tag">Sandbox</span>

        <div className="wx-top-right">
          <span className="wx-status"><Icon name="lock" size={13} /> Local only · nothing leaves this browser</span>
          <button type="button" className="wx-tour-chip" onClick={() => openTab('tour')} title="Open the guided tour">
            <Ring value={progress} /> Tour <b>{state.done.length}/{TASKS.length}</b>
          </button>
          <button type="button" className="wx-btn is-ghost" onClick={reset}><Icon name="reset" size={14} /> Reset</button>
          <Link className="wx-btn is-primary" href="/#install">Install Memty</Link>
        </div>
      </header>

      <nav className="wx-mtabs" aria-label="Workspace panes">
        {(['vault', 'chat', 'inspect'] as const).map((p) => (
          <button key={p} type="button" className={mobilePane === p ? 'is-on' : ''} onClick={() => setMobilePane(p)}>
            {p === 'vault' ? <>Vault <span>{vault.facts.length}</span></> : p === 'chat' ? 'Chat' : <>Inspector <span>{state.done.length}/{TASKS.length}</span></>}
          </button>
        ))}
      </nav>

      <div className="wx-grid">
        {/* ── Vault ──────────────────────────────────────────── */}
        <aside className="wx-pane wx-side" aria-label="Your vault">
          <div className="wx-side-head">
            <div>
              <h2>Vault</h2>
              <code>~/.memty/ledger.sqlite3</code>
            </div>
            <button type="button" className={`wx-icon-btn ${adding ? 'is-on' : ''}`} onClick={() => setAdding((a) => !a)} aria-expanded={adding} title="New fact">
              <Icon name={adding ? 'x' : 'plus'} size={15} />
            </button>
          </div>

          {adding && (
            <form className="wx-add" onSubmit={(e) => { e.preventDefault(); addFact(e.currentTarget); }}>
              <div className="wx-add-title">New fact</div>
              <label><span>Namespace</span><input name="namespace" placeholder="personal" defaultValue={nsFilter !== 'all' ? nsFilter : 'personal'} /></label>
              <label><span>Title</span><input name="title" placeholder="Editor" required autoFocus /></label>
              <label><span>Value</span><input name="value" placeholder="VS Code" required maxLength={160} /></label>
              <div className="wx-add-row">
                <label><span>Sensitivity</span>
                  <select name="level" defaultValue="PUBLIC">
                    {SENSITIVITIES.map((s) => <option key={s} value={s}>{LEVEL_LABEL[s]}</option>)}
                  </select>
                </label>
                <button type="submit" className="wx-btn is-primary">Remember</button>
              </div>
            </form>
          )}

          <label className="wx-search">
            <Icon name="search" size={14} />
            <input type="search" placeholder="Search facts" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search facts" />
          </label>

          <div className="wx-ns" role="tablist" aria-label="Namespaces">
            {['all', ...namespaces].map((ns) => (
              <button key={ns} type="button" role="tab" aria-selected={nsFilter === ns} className={nsFilter === ns ? 'is-on' : ''} onClick={() => setNsFilter(ns)}>
                {ns === 'all' ? 'All' : ns}<span>{nsCount(ns)}</span>
              </button>
            ))}
          </div>

          <div className="wx-groups">
            {visibleContexts.length === 0 && (
              <div className="wx-empty">
                <Icon name="box" size={20} />
                <b>No facts here yet</b>
                <span>Highlight text in the chat and click Save to Memty.</span>
              </div>
            )}
            {visibleContexts.map((ctx) => (
              <section key={ctx.id} className={`wx-group ${inspectContext?.id === ctx.id ? 'is-active' : ''}`}>
                <button type="button" className="wx-group-head" onClick={() => { setInspectId(ctx.id); setItab('capsule'); }} title="Preview this context as a capsule">
                  <span className="wx-group-title">{ctx.title}</span>
                  <span className="wx-group-meta">{ctx.namespace} · {timeAgo(ctx.createdAt)}</span>
                </button>
                <ul>
                  {contextFacts(ctx).map((f) => (
                    <li key={f.id} className="wx-fact">
                      <div className="wx-fact-body">
                        <span className="wx-fact-key">
                          {slotLabel(f.slot)}
                          {f.history.length > 1 && <em title={`${f.history.length} versions kept`}>v{f.history.length}</em>}
                        </span>
                        {editing?.id === f.id ? (
                          <input
                            className="wx-fact-edit" autoFocus value={editing.value}
                            onChange={(e) => setEditing({ id: f.id, value: e.target.value })}
                            onBlur={saveEdit}
                            onKeyDown={(e) => { if (e.key === 'Enter') saveEdit(); if (e.key === 'Escape') setEditing(null); }}
                            aria-label={`Edit ${slotLabel(f.slot)}`}
                          />
                        ) : f.sensitivity === 'SECRET' ? (
                          <span className="wx-fact-value is-secret"><Icon name="lock" size={12} /> Stored on this device only</span>
                        ) : (
                          <span className="wx-fact-value">{f.value}</span>
                        )}
                      </div>
                      <div className="wx-fact-side">
                        <LevelTag level={f.sensitivity} onClick={() => cycleLevel(f)} />
                        <div className="wx-fact-actions">
                          {f.sensitivity !== 'SECRET' && (
                            <button type="button" onClick={() => setEditing({ id: f.id, value: f.value })} aria-label={`Edit ${slotLabel(f.slot)}`} title="Edit"><Icon name="edit" size={13} /></button>
                          )}
                          <button type="button" className="is-danger" onClick={() => forgetFact(f)} aria-label={`Forget ${slotLabel(f.slot)}`} title="Forget permanently"><Icon name="trash" size={13} /></button>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>

          <footer className="wx-side-foot">
            <span><b>{vault.facts.length}</b> facts</span>
            <span><b>{vault.contexts.length}</b> contexts</span>
            <span><b>{namespaces.length}</b> namespaces</span>
            <span className="wx-mono">≈{totalTokens} tok</span>
          </footer>
        </aside>

        {/* ── Chat ───────────────────────────────────────────── */}
        <section className="wx-pane wx-chat" aria-label="Simulated assistant">
          <div className="wx-chat-head">
            <div className="wx-ptabs" role="tablist" aria-label="Assistant">
              {PROVIDERS.map((p) => (
                <button
                  key={p.id} type="button" role="tab" aria-selected={p.id === provider.id}
                  className={`wx-ptab ${p.id === provider.id ? 'is-on' : ''}`}
                  onClick={() => { setProviderId(p.id); setSelection(null); setPickerOpen(false); }}
                >
                  <BrandIcon id={p.id} size={18} />
                  <span>{shortName(p)}</span>
                  {p.kind === 'local' && <em>Local</em>}
                </button>
              ))}
            </div>
          </div>

          <div className="wx-transcript" ref={transcriptRef} onMouseUp={onTranscriptMouseUp} onTouchEnd={() => window.setTimeout(onTranscriptMouseUp, 50)}>
            <div className="wx-thread">
              {messages.map((m) => {
                if (m.role === 'system') {
                  return <div key={m.id} className="wx-sys"><Icon name="info" size={13} />{m.text}</div>;
                }
                if (m.role === 'user') {
                  const rest = m.text.replace(CAPSULE_RE, '').trim();
                  return (
                    <div key={m.id} className="wx-user">
                      <div className="wx-bubble">
                        {CAPSULE_RE.test(m.text) && <CapsuleCard text={m.text} />}
                        {rest && <p>{rest}</p>}
                      </div>
                    </div>
                  );
                }
                return (
                  <div key={m.id} className="wx-bot">
                    <BrandIcon id={provider.id} size={28} />
                    <div className="wx-bot-body">
                      <span className="wx-bot-name">{shortName(provider)}</span>
                      <div className="wx-bot-text">{m.text}</div>
                    </div>
                  </div>
                );
              })}
              {typing && (
                <div className="wx-bot">
                  <BrandIcon id={provider.id} size={28} />
                  <div className="wx-bot-body"><span className="wx-bot-name">{shortName(provider)}</span><div className="wx-typing"><i /><i /><i /></div></div>
                </div>
              )}
              {messages.length > 0 && provider.id === 'chatgpt' && !state.done.includes('save') && (
                <div className="wx-coach">
                  <span className="wx-coach-icon"><Icon name="cursor" size={14} /></span>
                  <div>
                    <b>Try it: save these facts</b>
                    <span>Highlight the bullet list in the reply above, then click <kbd>Save to Memty</kbd>.</span>
                  </div>
                </div>
              )}
            </div>
            {selection && (
              <button
                type="button" className="wx-selbar"
                style={{ left: selection.x, top: selection.y }}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => openReview(selection.text)}
              >
                <MemtyMark size={14} /> Save to Memty
              </button>
            )}
          </div>

          <div className="wx-compose-wrap">
            <div className={`wx-composer ${pickerOpen ? 'has-picker' : ''}`}>
              {pickerOpen && (
                <div className="wx-picker" role="dialog" aria-label="Insert a Memty context">
                  <div className="wx-picker-head">
                    <span><MemtyMark size={13} /> Insert context into {shortName(provider)}</span>
                    <kbd>Esc</kbd>
                  </div>
                  <button type="button" className="wx-picker-row is-auto" onClick={() => pasteContext('auto')}>
                    <span className="wx-picker-icon"><Icon name="sparkles" size={15} /></span>
                    <span className="wx-picker-main">
                      <b>Most relevant to my message</b>
                      <small>{draft.trim() ? 'Ranked against your draft' : 'Type a question first for the best match'}</small>
                    </span>
                  </button>
                  <div className="wx-picker-label">Saved contexts</div>
                  {contexts.map((ctx) => {
                    const facts = contextFacts(ctx);
                    const preview = compileCapsule(facts, provider, trusted, budget);
                    return (
                      <button key={ctx.id} type="button" className="wx-picker-row" onClick={() => pasteContext(ctx)}>
                        <span className="wx-picker-icon"><Icon name="box" size={15} /></span>
                        <span className="wx-picker-main">
                          <b>{ctx.title}</b>
                          <small>{facts.length} fact{facts.length === 1 ? '' : 's'} · {ctx.namespace} · {timeAgo(ctx.createdAt)}</small>
                        </span>
                        {!preview.ok && <span className="wx-pill is-secret">Secret</span>}
                        {preview.ok && preview.redacted > 0 && <span className="wx-pill is-confidential">{preview.redacted} private</span>}
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
                placeholder={`Message ${shortName(provider)}`}
                rows={Math.min(9, Math.max(2, draft.split('\n').length))}
                aria-label={`Message ${shortName(provider)}`}
              />
              <div className="wx-composer-bar">
                <button type="button" className={`wx-memty ${pickerOpen ? 'is-on' : ''}`} onClick={() => setPickerOpen((o) => !o)} aria-expanded={pickerOpen}>
                  <MemtyMark size={15} /> Memty <kbd>Alt M</kbd>
                </button>
                <span className={`wx-gate ${provider.kind === 'local' ? 'is-local' : ''}`}>
                  <i />{provider.kind === 'local' ? 'Local model · secrets may be used' : 'Cloud · privacy gate on'}
                </span>
                <button type="button" className="wx-send" onClick={send} disabled={!draft.trim() || typing} aria-label="Send">
                  <Icon name="arrowUp" size={16} />
                </button>
              </div>
            </div>
            <p className="wx-disclaimer">Simulated {shortName(provider)} tab. No model is called and nothing is uploaded.</p>
          </div>
        </section>

        {/* ── Inspector ──────────────────────────────────────── */}
        <aside className="wx-pane wx-insp" aria-label="Inspector">
          <div className="wx-itabs" role="tablist" aria-label="Inspector">
            {([
              ['tour', 'Tour', 'flag', `${state.done.length}/${TASKS.length}`],
              ['capsule', 'Capsule', 'box', inspectCapsule?.ok ? `${inspectCapsule.tokens}` : ''],
              ['terminal', 'CLI', 'terminal', ''],
              ['receipts', 'Receipts', 'receipt', state.receipts.length ? String(state.receipts.length) : ''],
            ] as const).map(([id, label, icon, badge]) => (
              <button key={id} type="button" role="tab" aria-selected={itab === id} className={itab === id ? 'is-on' : ''} onClick={() => setItab(id)}>
                <Icon name={icon} size={14} />{label}{badge && <span>{badge}</span>}
              </button>
            ))}
          </div>

          <div className="wx-insp-body">
            {itab === 'tour' && (
              <div className="wx-tour">
                <div className="wx-tour-head">
                  <div>
                    <h3>Guided tour</h3>
                    <p>Seven steps through the whole Memty loop.</p>
                  </div>
                  <span className="wx-tour-pct">{progress}%</span>
                </div>
                <div className="wx-bar"><i style={{ width: `${progress}%` }} /></div>
                <ol className="wx-steps">
                  {TASKS.map((t, i) => {
                    const done = state.done.includes(t.id);
                    const current = currentTask?.id === t.id;
                    return (
                      <li key={t.id} className={`${done ? 'is-done' : ''} ${current ? 'is-current' : ''}`}>
                        <span className="wx-step-n">{done ? <Icon name="check" size={12} /> : i + 1}</span>
                        <div>
                          <b>{t.title}</b>
                          {(current || done) && <span>{t.hint}</span>}
                        </div>
                      </li>
                    );
                  })}
                </ol>
                {progress === 100 && (
                  <div className="wx-done">
                    <b>You have seen the whole loop.</b>
                    <span>Make it real on your machine:</span>
                    <code>pip install memty</code>
                  </div>
                )}
              </div>
            )}

            {itab === 'capsule' && (
              <div className="wx-cap">
                <div className="wx-cap-head">
                  <BrandIcon id={provider.id} size={22} />
                  <div>
                    <h3>What {shortName(provider)} receives</h3>
                    <p>{provider.kind === 'local' ? 'Local model: Confidential values stay readable on your machine' : 'Cloud assistant: the privacy gate applies'}</p>
                  </div>
                </div>

                {inspectContext ? (
                  <>
                    <label className="wx-field">
                      <span>Context</span>
                      <div className="wx-select">
                        <select value={inspectContext.id} onChange={(e) => setInspectId(e.target.value)}>
                          {contexts.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
                        </select>
                        <Icon name="chevron" size={14} />
                      </div>
                    </label>

                    {inspectCapsule && !inspectCapsule.ok ? (
                      <div className="wx-blocked">
                        <Icon name="ban" size={18} />
                        <div>
                          <b>Request stopped</b>
                          <span>“{slotLabel(inspectCapsule.stoppedBy!.slot)}” is Secret. Cloud assistants never receive it. Switch to Ollama to use it locally.</span>
                        </div>
                      </div>
                    ) : (
                      <div className="wx-code">
                        <div className="wx-code-head">
                          <span>capsule.txt</span>
                          <span className="wx-mono">{inspectCapsule?.tokens ?? 0} tokens</span>
                          <button type="button" onClick={copyCapsule} title="Copy capsule" aria-label="Copy capsule"><Icon name="copy" size={13} /></button>
                        </div>
                        <pre>{inspectCapsule?.text || '(nothing in this context may be shared)'}</pre>
                      </div>
                    )}

                    <div className="wx-section-label">Privacy gate decisions</div>
                    <ul className="wx-decisions">
                      {inspectCapsule?.decisions.map((d) => {
                        const sent = d.action === 'share' && inspectCapsule.included.includes(d.fact);
                        const outcome = d.action === 'share' ? (sent ? 'Sent' : 'Over budget')
                          : d.action === 'redact' ? 'Masked' : d.action === 'withhold' ? 'Withheld' : 'Stops send';
                        const icon = d.action === 'share' ? (sent ? 'check' : 'minus') : d.action === 'redact' ? 'eyeOff' : d.action === 'withhold' ? 'minus' : 'ban';
                        return (
                          <li key={d.fact.id} className={`is-${d.action} ${d.action === 'share' && !sent ? 'is-over' : ''}`}>
                            <span className="wx-dec-key">{slotLabel(d.fact.slot)}</span>
                            <LevelTag level={d.fact.sensitivity} />
                            <span className="wx-dec-out"><Icon name={icon} size={12} />{outcome}</span>
                          </li>
                        );
                      })}
                    </ul>

                    <label className="wx-range">
                      <span>Token budget</span><b className="wx-mono">{budget}</b>
                      <input type="range" min={20} max={400} step={10} value={budget} onChange={(e) => setBudget(Number(e.target.value))} />
                    </label>
                  </>
                ) : (
                  <div className="wx-empty"><Icon name="box" size={20} /><b>No contexts yet</b><span>Save some facts to preview a capsule.</span></div>
                )}

                <div className="wx-section-label">Trusted assistants <small>may see Internal and Confidential</small></div>
                <ul className="wx-trust">
                  {PROVIDERS.filter((p) => p.kind === 'cloud').map((p) => {
                    const on = vault.trusted.includes(p.id);
                    return (
                      <li key={p.id}>
                        <BrandIcon id={p.id} size={18} />
                        <span>{p.name}</span>
                        <button type="button" role="switch" aria-checked={on} aria-label={`Trust ${p.name}`} className={`wx-switch ${on ? 'is-on' : ''}`} onClick={() => toggleTrusted(p.id)}><i /></button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}

            {itab === 'terminal' && (
              <div className="wx-term-wrap">
                <p className="wx-insp-note">Every action in this workspace has a CLI equivalent. This is what you just did:</p>
                <div className="wx-term">
                  <div className="wx-term-bar"><i /><i /><i /><span>~ zsh</span></div>
                  <pre>
                    {cli.map((line, i) => (line.startsWith('#')
                      ? <span key={i} className="wx-term-c">{line}{'\n'}</span>
                      : <span key={i}><span className="wx-term-p">$ </span>{line}{'\n'}</span>))}
                  </pre>
                </div>
              </div>
            )}

            {itab === 'receipts' && (
              <div className="wx-receipts-wrap">
                <p className="wx-insp-note">Every capsule leaves a receipt: who received it, how many facts and tokens. Values are never stored in receipts.</p>
                {state.receipts.length === 0 ? (
                  <div className="wx-empty"><Icon name="receipt" size={20} /><b>No receipts yet</b><span>Insert a context with Memty to create one.</span></div>
                ) : (
                  <ul className="wx-receipts">
                    {state.receipts.slice(0, 12).map((r) => (
                      <li key={r.id} className={r.blocked ? 'is-blocked' : ''}>
                        <BrandIcon id={providerByName(r.provider)?.id ?? ''} size={22} />
                        <div>
                          <b>{r.provider}</b>
                          <span>{r.context} · {timeAgo(r.at)}</span>
                        </div>
                        <em className="wx-mono">{r.blocked ? 'Blocked' : `${r.facts} facts · ${r.tokens} tok${r.redacted ? ` · ${r.redacted} masked` : ''}`}</em>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        </aside>
      </div>

      {/* ── Review dialog ─────────────────────────────────────── */}
      {review && (
        <div className="wx-modal" role="dialog" aria-modal="true" aria-label="Review facts before saving" onClick={(e) => { if (e.target === e.currentTarget) setReview(null); }}>
          <div className="wx-modal-card">
            <div className="wx-modal-head">
              <span className="wx-modal-mark"><MemtyMark size={18} /></span>
              <div>
                <h3>Review before saving</h3>
                <p>Proposed with local rules: no model and no network. Edit or untick anything.</p>
              </div>
              <button type="button" className="wx-icon-btn" onClick={() => setReview(null)} aria-label="Close"><Icon name="x" size={15} /></button>
            </div>
            <div className="wx-modal-meta">
              <label className="wx-field"><span>Namespace</span><input value={review.namespace} onChange={(e) => setReview({ ...review, namespace: e.target.value })} /></label>
              <label className="wx-field"><span>Context title</span><input value={review.title} onChange={(e) => setReview({ ...review, title: e.target.value })} /></label>
            </div>
            <div className="wx-props">
              <div className="wx-props-head"><span /><span>Title</span><span>Value</span><span>Sensitivity</span></div>
              {review.proposals.map((p, i) => (
                <div key={p.id} className={`wx-prop ${p.selected ? '' : 'is-off'}`}>
                  <input
                    type="checkbox" checked={p.selected} aria-label={`Keep ${p.title}`}
                    onChange={(e) => setReview({ ...review, proposals: review.proposals.map((q, j) => (j === i ? { ...q, selected: e.target.checked } : q)) })}
                  />
                  <input
                    className="wx-prop-title" value={p.title} aria-label="Title"
                    onChange={(e) => setReview({ ...review, proposals: review.proposals.map((q, j) => (j === i ? { ...q, title: e.target.value } : q)) })}
                  />
                  <input
                    className="wx-prop-value" value={p.value} aria-label="Value"
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
                  <div className={`wx-select is-${p.sensitivity.toLowerCase()}`}>
                    <select
                      value={p.sensitivity} aria-label="Sensitivity"
                      onChange={(e) => {
                        const level = e.target.value as Sensitivity;
                        if (p.sensitivity === 'SECRET' && looksLikeCredential(p.value) && level !== 'SECRET') {
                          notify('Credentials stay Secret. Only the terminal can change that.', 'warn');
                          return;
                        }
                        setReview({ ...review, proposals: review.proposals.map((q, j) => (j === i ? { ...q, sensitivity: level } : q)) });
                      }}
                    >
                      {SENSITIVITIES.map((s) => <option key={s} value={s}>{LEVEL_LABEL[s]}</option>)}
                    </select>
                    <Icon name="chevron" size={13} />
                  </div>
                  {p.note && <span className="wx-prop-note"><Icon name="alert" size={12} />{p.note}</span>}
                </div>
              ))}
            </div>
            <div className="wx-modal-foot">
              <span>{review.proposals.filter((p) => p.selected).length} of {review.proposals.length} selected · max 40 tokens per fact</span>
              <div>
                <button type="button" className="wx-btn is-ghost" onClick={() => setReview(null)}>Cancel</button>
                <button type="button" className="wx-btn is-primary" onClick={commitReview}>Save to vault</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {toast && (
        <div className={`wx-toast is-${toast.tone}`} role="status">
          <Icon name={toast.tone === 'ok' ? 'check' : toast.tone === 'warn' ? 'alert' : 'ban'} size={15} />
          <span>{toast.text}</span>
        </div>
      )}
    </div>
  );
}
