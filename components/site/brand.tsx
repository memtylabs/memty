import Link from 'next/link';

export const GITHUB_URL = 'https://github.com/memtylabs/memty';
export const PYPI_URL = 'https://pypi.org/project/memty/';
export const DOCS_URL = 'https://github.com/memtylabs/memty/blob/main/memty/README.md';
export const CHANGELOG_URL = 'https://github.com/memtylabs/memty/blob/main/memty/CHANGELOG.md';
export const BENCHMARK_URL = 'https://github.com/memtylabs/memty/blob/main/benchmarks/token_burn/README.md';
export const SECURITY_URL = 'https://github.com/memtylabs/memty/blob/main/docs/SECURITY_TESTING.md';

/** The Memty mark: an M holding three memory layers, the top one locked. */
export function MemtyMark({ size = 28, className }: { size?: number; className?: string }) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 64 56" aria-hidden="true">
      <path
        d="M3 11.5 15.5 4l16.5 9.6L48.5 4 61 11.5v33.6l-8.6 5V19.3L32 31.2 11.6 19.3v30.8L3 45.1Z"
        fill="currentColor"
      />
      <path d="M19 31.5 32 24l13 7.5L32 39Z" fill="#b9b3ff" />
      <path d="M19 36.6 32 44.1l13-7.5v3.6L32 47.7l-13-7.5Z" fill="#6d5cff" />
      <path d="M19 42.2 32 49.7l13-7.5v3.6L32 53.3l-13-7.5Z" fill="#3b1ff0" />
      <rect x="29" y="29.4" width="6" height="4.6" rx="1" fill="#0b0b14" />
      <path d="M30.3 29.6v-1.4a1.7 1.7 0 0 1 3.4 0v1.4" fill="none" stroke="#0b0b14" strokeWidth="1.1" />
    </svg>
  );
}

export function MemtyLogo({ href = '/' }: { href?: string }) {
  return (
    <Link className="mt-logo" href={href} aria-label="Memty home">
      <MemtyMark size={30} />
      <span>Memty</span>
    </Link>
  );
}

export function GitHubIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" fill="currentColor">
      <path d="M12 .5a12 12 0 0 0-3.8 23.4c.6.1.8-.3.8-.6v-2c-3.3.7-4-1.6-4-1.6-.6-1.4-1.4-1.8-1.4-1.8-1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.7-1.6-2.7-.3-5.5-1.3-5.5-5.9 0-1.3.5-2.4 1.2-3.2-.1-.3-.5-1.5.1-3.2 0 0 1-.3 3.3 1.2a11.5 11.5 0 0 1 6 0C17.3 4.7 18.3 5 18.3 5c.7 1.7.2 2.9.1 3.2.8.8 1.2 1.9 1.2 3.2 0 4.6-2.8 5.6-5.5 5.9.4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6A12 12 0 0 0 12 .5Z" />
    </svg>
  );
}

export function SiteNav({ current }: { current?: 'home' | 'workspace' | 'docs' }) {
  return (
    <header className="mt-nav">
      <div className="mt-nav-inner">
        <MemtyLogo />
        <nav className="mt-nav-links" aria-label="Main">
          {current !== 'home' ? (
            <>
              <Link href="/#how">How it works</Link>
              <Link href="/#install">Install</Link>
              <Link href="/#privacy">Privacy</Link>
            </>
          ) : (
            <>
              <a href="#how">How it works</a>
              <a href="#install">Install</a>
              <a href="#privacy">Privacy</a>
              <a href="#proof">Benchmark</a>
            </>
          )}
        </nav>
        <div className="mt-nav-actions">
          <a className="mt-icon-link" href={GITHUB_URL} target="_blank" rel="noreferrer" aria-label="Memty on GitHub">
            <GitHubIcon />
          </a>
          {current !== 'home' ? (
            <Link className="mt-btn mt-btn-primary mt-btn-sm" href="/#install">Install Memty</Link>
          ) : (
            <Link className="mt-btn mt-btn-primary mt-btn-sm" href="/workspace">Try the demo</Link>
          )}
        </div>
      </div>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="mt-footer">
      <div className="mt-footer-inner">
        <div className="mt-footer-brand">
          <MemtyLogo />
          <p>Persistent memory for AI assistants and agents. One local vault, every tool, owned by you.</p>
          <p className="mt-footer-meta">Fair Source (FSL-1.1-ALv2) · alpha (0.x) · no account, no cloud, no telemetry</p>
        </div>
        <div className="mt-footer-cols">
          <div>
            <h4>Product</h4>
            <Link href="/#how">How it works</Link>
            <Link href="/#install">Install</Link>
            <Link href="/workspace">Demo workspace</Link>
            <Link href="/#privacy">Privacy gate</Link>
          </div>
          <div>
            <h4>Resources</h4>
            <a href={DOCS_URL} target="_blank" rel="noreferrer">Package docs</a>
            <Link href="/api-reference">API reference</Link>
            <a href={CHANGELOG_URL} target="_blank" rel="noreferrer">Changelog</a>
            <a href={BENCHMARK_URL} target="_blank" rel="noreferrer">Benchmark method</a>
            <a href={SECURITY_URL} target="_blank" rel="noreferrer">Security tests</a>
          </div>
          <div>
            <h4>Project</h4>
            <a href={GITHUB_URL} target="_blank" rel="noreferrer">GitHub</a>
            <a href={PYPI_URL} target="_blank" rel="noreferrer">PyPI</a>
            <Link href="/privacy">Privacy notice</Link>
            <Link href="/terms">Terms of use</Link>
          </div>
        </div>
      </div>
    </footer>
  );
}
