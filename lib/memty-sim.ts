/**
 * A small in-browser model of the Memty vault, used by the landing page and
 * the demo workspace. It mirrors the rules of the real `memty` package so the
 * demo behaves like the product:
 *
 * - token estimate: memty/vault/tokens.py (`estimate_tokens`)
 * - capsule format and budget: memty/context/compiler.py
 * - privacy gate: memty/context/privacy.py
 * - slot labels: memty/context/render.py (`slot_label`)
 * - credentials are always SECRET: memty/vault/credentials.py
 *
 * Nothing here talks to a server. The real vault lives in
 * ~/.memty/ledger.sqlite3 once someone runs `pip install memty`.
 */

export type Sensitivity = 'PUBLIC' | 'INTERNAL' | 'CONFIDENTIAL' | 'SECRET';
export const SENSITIVITIES: Sensitivity[] = ['PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'SECRET'];

export const FACT_TOKEN_LIMIT = 40;
export const MAX_CONTEXT_FACTS = 25;

export type FactVersion = { value: string; at: number };

export type Fact = {
  id: string;
  namespace: string;
  slot: string;
  value: string;
  sensitivity: Sensitivity;
  verification: 'USER_CONFIRMED' | 'EXTRACTED';
  contextId: string | null;
  createdAt: number;
  history: FactVersion[];
};

export type Context = {
  id: string;
  namespace: string;
  title: string;
  createdAt: number;
  factIds: string[];
};

export type Provider = {
  id: string;
  name: string;
  kind: 'cloud' | 'local';
};

export const PROVIDERS: Provider[] = [
  { id: 'chatgpt', name: 'ChatGPT', kind: 'cloud' },
  { id: 'claude', name: 'Claude.ai', kind: 'cloud' },
  { id: 'gemini', name: 'Gemini', kind: 'cloud' },
  { id: 'perplexity', name: 'Perplexity', kind: 'cloud' },
  { id: 'ollama', name: 'Ollama (local)', kind: 'local' },
];

// Built with the constructor because `\p{…}` literals need an ES2018 target.
const TOKEN_RE = new RegExp('[\\p{L}\\p{N}_]+|[^\\p{L}\\p{N}_\\s]', 'gu');

/** Conservative token count, same formula as memty/vault/tokens.py. */
export function estimateTokens(text: string): number {
  if (!text) return 0;
  const words = text.match(TOKEN_RE)?.length ?? 0;
  return Math.max(words, Math.floor((text.length + 3) / 4));
}

/** `deploy_target_2` -> `Deploy target`. */
export function slotLabel(slot: string): string {
  const label = slot.replace(/_\d+$/, '').replace(/[_.]/g, ' ').trim();
  return label.charAt(0).toUpperCase() + label.slice(1);
}

/** Turn a free-form title into a valid slot key (`[a-z0-9][a-z0-9_-]{0,63}`). */
export function toSlot(title: string): string {
  const slot = title
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 64);
  return slot || 'note';
}

const CREDENTIAL_PATTERNS: RegExp[] = [
  /\bsk-(?:live|test|proj|ant)?[-_]?[A-Za-z0-9]{12,}/,
  /\bsk_(?:live|test)_[A-Za-z0-9]{8,}/,
  /\bgh[pousr]_[A-Za-z0-9]{20,}/,
  /\bAKIA[0-9A-Z]{16}\b/,
  /\bAIza[0-9A-Za-z_-]{20,}/,
  /\bxox[abpr]-[A-Za-z0-9-]{10,}/,
  /-----BEGIN [A-Z ]*PRIVATE KEY-----/,
  /\b(?:password|passwd|pwd|api[_ -]?key|secret|access[_ -]?token|auth[_ -]?token)\s*[:=]\s*\S{4,}/i,
];

/** Pasted keys and passwords are stored as SECRET however they are saved. */
export function looksLikeCredential(text: string): boolean {
  return CREDENTIAL_PATTERNS.some((pattern) => pattern.test(text));
}

export function uid(prefix = 'f'): string {
  const random = Math.random().toString(36).slice(2, 10);
  return `${prefix}_${Date.now().toString(36)}${random}`;
}

/* ------------------------------------------------------------------ */
/* Privacy gate                                                        */
/* ------------------------------------------------------------------ */

export type GateDecision =
  | { fact: Fact; action: 'share' }
  | { fact: Fact; action: 'redact' }
  | { fact: Fact; action: 'withhold'; reason: string }
  | { fact: Fact; action: 'stop' };

export function gateFact(fact: Fact, provider: Provider, trusted: Set<string>): GateDecision {
  const local = provider.kind === 'local';
  const isTrusted = local || trusted.has(provider.id);
  if (fact.sensitivity === 'INTERNAL' && !isTrusted) {
    return { fact, action: 'withhold', reason: 'INTERNAL facts only go to local or trusted assistants' };
  }
  if (fact.sensitivity === 'SECRET' && !local) return { fact, action: 'stop' };
  if (fact.sensitivity === 'CONFIDENTIAL' && !isTrusted) return { fact, action: 'redact' };
  return { fact, action: 'share' };
}

export type Capsule = {
  ok: boolean;
  text: string;
  tokens: number;
  included: Fact[];
  redacted: number;
  omitted: number;
  decisions: GateDecision[];
  /** Set when a SECRET fact matched and the provider is not local. */
  stoppedBy: Fact | null;
};

/** Plain one-line value, as memty/context/compiler.py `_plain_value` does. */
function plainValue(value: string): string {
  return value.replace(/\s+/g, ' ').replace(/\[\/?Memty[^\]]*\]/gi, '').trim();
}

/** Build the `[Memty context]` capsule a provider would receive. */
export function compileCapsule(
  facts: Fact[],
  provider: Provider,
  trusted: Set<string>,
  tokenBudget = 2000,
): Capsule {
  const decisions = facts.map((fact) => gateFact(fact, provider, trusted));
  const stop = decisions.find((d) => d.action === 'stop');
  if (stop) {
    return { ok: false, text: '', tokens: 0, included: [], redacted: 0, omitted: facts.length, decisions, stoppedBy: stop.fact };
  }
  const header = '[Memty context]';
  const footer = '[/Memty]';
  const lines: string[] = [];
  const included: Fact[] = [];
  let redacted = 0;
  for (const decision of decisions) {
    if (decision.action === 'withhold') continue;
    const value = decision.action === 'redact' ? '[private]' : plainValue(decision.fact.value);
    const line = `${lines.length + 1}. ${slotLabel(decision.fact.slot)}: ${value}`;
    if (estimateTokens([header, ...lines, line, footer].join('\n')) > tokenBudget) break;
    lines.push(line);
    included.push(decision.fact);
    if (decision.action === 'redact') redacted += 1;
  }
  const text = lines.length ? [header, ...lines, footer].join('\n') : '';
  return {
    ok: true,
    text,
    tokens: estimateTokens(text),
    included,
    redacted,
    omitted: facts.length - included.length,
    decisions,
    stoppedBy: null,
  };
}

/* ------------------------------------------------------------------ */
/* Recall: pick the facts most relevant to a question                  */
/* ------------------------------------------------------------------ */

const STOP_WORDS = new Set(
  'a an and are as at be by do does for from how i in is it me my of on or our so that the this to was we what when where which who why will with you your use used using'.split(' '),
);

function terms(text: string): Set<string> {
  return new Set(
    (text.toLowerCase().match(/[a-z0-9]+/g) ?? []).filter((t) => t.length > 1 && !STOP_WORDS.has(t)),
  );
}

export function recall(facts: Fact[], question: string, limit = 6): Fact[] {
  const q = terms(question);
  if (!q.size) return [...facts].sort((a, b) => b.createdAt - a.createdAt).slice(0, limit);
  const scored = facts
    .map((fact) => {
      const f = terms(`${slotLabel(fact.slot)} ${fact.value}`);
      let overlap = 0;
      q.forEach((t) => {
        if (f.has(t)) overlap += 1;
        else if ([...f].some((w) => w.startsWith(t) || t.startsWith(w))) overlap += 0.5;
      });
      return { fact, score: overlap };
    })
    .filter((s) => s.score > 0)
    .sort((a, b) => b.score - a.score || b.fact.createdAt - a.fact.createdAt);
  return scored.slice(0, limit).map((s) => s.fact);
}

/* ------------------------------------------------------------------ */
/* Local extraction: propose short facts from selected chat text       */
/* ------------------------------------------------------------------ */

export type Proposal = {
  id: string;
  title: string;
  value: string;
  sensitivity: Sensitivity;
  selected: boolean;
  note?: string;
};

function clampToFactLimit(title: string, value: string): string {
  let out = value.trim();
  while (estimateTokens(`${title}: ${out}`) > FACT_TOKEN_LIMIT && out.includes(' ')) {
    out = out.slice(0, out.lastIndexOf(' '));
  }
  return out;
}

const SUBJECT_RE = /^(?:our|my|the|we're on|we are on)?\s*([a-z][\w .\/-]{1,32}?)\s+(?:is|are|=|will be|lives on|runs on)\s+(.+)$/i;
const VERB_RE = /^(?:we|i)\s+(use|deploy to|deploy on|host on|prefer|write in|work in|build with)\s+(.+)$/i;

function proposalFromSentence(sentence: string): { title: string; value: string } | null {
  const text = sentence.replace(/[.!]+$/, '').trim();
  if (!text || text.endsWith('?')) return null;
  const subject = text.match(SUBJECT_RE);
  if (subject) {
    const title = subject[1].trim();
    return { title: title.charAt(0).toUpperCase() + title.slice(1), value: subject[2].trim() };
  }
  const verb = text.match(VERB_RE);
  if (verb) {
    const v = verb[1].toLowerCase();
    const title = v.startsWith('deploy') || v.startsWith('host') ? 'Deploy target'
      : v === 'prefer' ? 'Preference'
      : v.startsWith('write') || v.startsWith('work') ? 'Language'
      : 'Uses';
    return { title, value: verb[2].trim() };
  }
  return { title: 'Note', value: text };
}

/**
 * Propose facts from selected text using local rules, like the package's
 * default extractor: `Key: value` lines and bullets become facts; questions,
 * headings and raw code are skipped; code blocks become one-line summaries.
 */
export function extractProposals(text: string): Proposal[] {
  const proposals: Proposal[] = [];
  const seen = new Set<string>();
  const push = (title: string, value: string, note?: string) => {
    const cleanTitle = title.replace(/\*\*/g, '').trim().slice(0, 48) || 'Note';
    const cleanValue = clampToFactLimit(cleanTitle, value.replace(/\*\*/g, '').replace(/`/g, ''));
    const key = `${cleanTitle.toLowerCase()}=${cleanValue.toLowerCase()}`;
    if (!cleanValue || seen.has(key)) return;
    seen.add(key);
    const secret = looksLikeCredential(`${cleanTitle}: ${cleanValue}`) || looksLikeCredential(cleanValue);
    proposals.push({
      id: uid('p'),
      title: cleanTitle,
      value: cleanValue,
      sensitivity: secret ? 'SECRET' : 'PUBLIC',
      selected: true,
      note: secret ? 'Looks like a credential, so it is stored as SECRET' : note,
    });
  };

  const codeBlocks: string[] = [];
  const withoutCode = text.replace(/```(\w+)?\n?([\s\S]*?)```/g, (_m, lang: string | undefined, body: string) => {
    const lines = body.trim().split('\n').filter(Boolean).length;
    codeBlocks.push(`${lang ? `${lang} ` : ''}snippet, ${lines} line${lines === 1 ? '' : 's'} (summarized, not copied)`);
    return '\n';
  });

  for (const raw of withoutCode.split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    if (/^#{1,6}\s/.test(line) || /^[^:]{1,60}:$/.test(line)) continue; // headings
    if (/^(?:\$|>|PS>|C:\\)/.test(line)) continue; // shell prompts
    const bullet = line.replace(/^(?:[-*•]|\d+[.)])\s+/, '');
    const kv = bullet.match(/^([A-Za-z][\w .\/()-]{1,40}?)\s*[:=]\s+(.+)$/);
    if (kv && !/^https?$/i.test(kv[1])) {
      push(kv[1], kv[2]);
      continue;
    }
    for (const sentence of bullet.replace(/([.!?])\s+/g, '$1\n').split('\n')) {
      const proposal = proposalFromSentence(sentence);
      if (proposal) push(proposal.title, proposal.value);
    }
  }
  codeBlocks.forEach((summary) => push('Code', summary, 'Code is summarized in one line'));
  return proposals.slice(0, MAX_CONTEXT_FACTS);
}

/* ------------------------------------------------------------------ */
/* Seed vault for the demo                                             */
/* ------------------------------------------------------------------ */

export type Vault = { facts: Fact[]; contexts: Context[]; trusted: string[] };

export function seedVault(now = Date.now()): Vault {
  const make = (
    contextId: string,
    namespace: string,
    title: string,
    value: string,
    sensitivity: Sensitivity,
    offset: number,
  ): Fact => ({
    id: uid('f'),
    namespace,
    slot: toSlot(title),
    value,
    sensitivity: looksLikeCredential(value) ? 'SECRET' : sensitivity,
    verification: 'USER_CONFIRMED',
    contextId,
    createdAt: now - offset,
    history: [{ value, at: now - offset }],
  });

  const stack = 'ctx_stack';
  const prefs = 'ctx_prefs';
  const stackFacts = [
    make(stack, 'work.billing-api', 'Database', 'PostgreSQL 16 on Neon', 'PUBLIC', 86_400_000),
    make(stack, 'work.billing-api', 'Deploy target', 'Fly.io, two regions (iad, fra)', 'PUBLIC', 86_399_000),
    make(stack, 'work.billing-api', 'Language', 'TypeScript 5 on Node 22', 'PUBLIC', 86_398_000),
    make(stack, 'work.billing-api', 'Client', 'Acme Health', 'CONFIDENTIAL', 86_397_000),
    make(stack, 'work.billing-api', 'Q1 roadmap', 'Usage-based pricing launch in March', 'INTERNAL', 86_396_000),
  ];
  const prefFacts = [
    make(prefs, 'personal', 'Editor', 'VS Code with Vim keys', 'PUBLIC', 3_600_000),
    make(prefs, 'personal', 'Answer style', 'Short answers, code first, no filler', 'PUBLIC', 3_599_000),
    make(prefs, 'personal', 'Timezone', 'IST (UTC+5:30)', 'PUBLIC', 3_598_000),
  ];
  return {
    facts: [...stackFacts, ...prefFacts],
    contexts: [
      { id: stack, namespace: 'work.billing-api', title: 'Billing API stack', createdAt: now - 86_400_000, factIds: stackFacts.map((f) => f.id) },
      { id: prefs, namespace: 'personal', title: 'How I like to work', createdAt: now - 3_600_000, factIds: prefFacts.map((f) => f.id) },
    ],
    trusted: [],
  };
}

/** Shell-quote a value the way the docs write CLI examples. */
export function cliQuote(value: string): string {
  return /^[\w.@/-]+$/.test(value) ? value : `"${value.replace(/(["\\$`])/g, '\\$1')}"`;
}
