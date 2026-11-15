import type { ReactNode } from 'react';
import Link from 'next/link';
import { SiteFooter, SiteNav } from '@/components/site/brand';

export type TocItem = { id: string; label: string };

const DOCS = [
  { href: '/privacy', label: 'Privacy notice' },
  { href: '/terms', label: 'Terms of use' },
  { href: '/api-reference', label: 'API reference' },
];

/** Shared layout for the privacy notice, terms and API reference. */
export function DocLayout({
  path, eyebrow, title, lede, updated, toc, children,
}: {
  path: string; eyebrow: string; title: string; lede: ReactNode; updated: string; toc: TocItem[]; children: ReactNode;
}) {
  return (
    <div className="mt">
      <SiteNav current="docs" />
      <main className="doc">
        <header className="doc-head">
          <p className="mt-eyebrow">{eyebrow}</p>
          <h1>{title}</h1>
          <div className="doc-lede">{lede}</div>
          <p className="doc-updated">Last updated {updated}</p>
        </header>
        <div className="doc-body">
          <aside className="doc-aside" aria-label="On this page">
            <nav className="doc-switch" aria-label="Documents">
              {DOCS.map((d) => (
                <Link key={d.href} href={d.href} className={d.href === path ? 'is-on' : ''} aria-current={d.href === path ? 'page' : undefined}>{d.label}</Link>
              ))}
            </nav>
            <p className="doc-toc-label">On this page</p>
            <ol className="doc-toc">
              {toc.map((t) => <li key={t.id}><a href={`#${t.id}`}>{t.label}</a></li>)}
            </ol>
          </aside>
          <article className="doc-article">{children}</article>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}

export function DocSection({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} className="doc-section">
      <h2><a href={`#${id}`} aria-label={`Link to ${title}`}>#</a>{title}</h2>
      {children}
    </section>
  );
}

export function Callout({ title, children, tone = 'info' }: { title: string; children: ReactNode; tone?: 'info' | 'good' | 'warn' }) {
  return (
    <div className={`doc-callout is-${tone}`}>
      <b>{title}</b>
      <div>{children}</div>
    </div>
  );
}

export function Code({ children, label }: { children: string; label?: string }) {
  return (
    <div className="doc-code">
      {label && <span className="doc-code-label">{label}</span>}
      <pre><code>{children}</code></pre>
    </div>
  );
}
