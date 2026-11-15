import type { Metadata } from 'next';
import Link from 'next/link';
import { Callout, Code, DocLayout, DocSection } from '@/components/site/doc-layout';
import { GITHUB_URL, SECURITY_URL } from '@/components/site/brand';

export const metadata: Metadata = {
  title: 'Privacy notice | Memty',
  description: 'How Memty handles your data: a local vault on your computer, no account, no cloud sync and no telemetry.',
};

const TOC = [
  { id: 'summary', label: 'Summary' },
  { id: 'scope', label: 'What this covers' },
  { id: 'package', label: 'The Memty package' },
  { id: 'extension', label: 'The browser extension' },
  { id: 'mcp', label: 'Coding agents (MCP)' },
  { id: 'providers', label: 'AI providers you choose' },
  { id: 'website', label: 'This website' },
  { id: 'demo', label: 'The demo workspace' },
  { id: 'control', label: 'Your control and deletion' },
  { id: 'security', label: 'Security' },
  { id: 'children', label: 'Children' },
  { id: 'changes', label: 'Changes and contact' },
];

export default function PrivacyPage() {
  return (
    <DocLayout
      path="/privacy"
      eyebrow="Legal"
      title="Privacy notice"
      updated="November 15, 2026"
      toc={TOC}
      lede={<p>Memty is built so that your memory stays yours. This notice explains, in plain language, what data each part of Memty touches and where it goes.</p>}
    >
      <DocSection id="summary" title="Summary">
        <Callout title="We don't collect your data" tone="good">
          <p>Memty has no account, no server that stores your memory, no cloud sync and no telemetry. Your facts live in one file on your own computer. The Memty project never receives them.</p>
        </Callout>
        <ul>
          <li>Your vault is a SQLite file on your computer: <code>~/.memty/ledger.sqlite3</code>.</li>
          <li>Facts leave your computer only when <strong>you</strong> paste a capsule into an AI assistant, or an agent you connected asks for one.</li>
          <li>Before anything is shared, the privacy gate masks private values and refuses to send secrets.</li>
          <li>This website and its demo store nothing about you on a server.</li>
        </ul>
      </DocSection>

      <DocSection id="scope" title="What this covers">
        <p>This notice covers the open-source Memty project published at <a href={GITHUB_URL} target="_blank" rel="noreferrer">github.com/memtylabs/memty</a>:</p>
        <ul>
          <li>the <code>memty</code> Python package, its local bridge and its background daemon (<code>memtyd</code>);</li>
          <li>the Memty Bridge browser extension;</li>
          <li>the Memty MCP server used by coding agents and desktop apps;</li>
          <li>this website, including the demo workspace.</li>
        </ul>
        <p>It does not cover the AI assistants you use with Memty, such as ChatGPT, Claude, Gemini, Perplexity or Cursor. Their own privacy policies apply to anything you send them.</p>
      </DocSection>

      <DocSection id="package" title="The Memty package">
        <p><strong>Where your data lives.</strong> Facts, their earlier versions, archived source text you chose to keep, agent proposals and usage receipts are stored in your vault file, by default <code>~/.memty/ledger.sqlite3</code>. You can move it with <code>--db</code> or <code>MEMTY_VAULT_PATH</code>. A pairing token for the browser extension is stored beside it with owner-only permissions.</p>
        <p><strong>What leaves your computer.</strong> Nothing, on its own. The package does not phone home, check for updates or send analytics. Its only network activity is:</p>
        <ul>
          <li>the local bridge, which listens on <code>127.0.0.1</code> (port 8765 by default) and is reachable only from your own computer;</li>
          <li>optionally, a local Ollama model at <code>127.0.0.1:11434</code>, used to extract facts only if you set <code>MEMTY_OLLAMA_MODEL</code>.</li>
        </ul>
        <p>Installing or upgrading with <code>pip</code> downloads the package from PyPI, which is governed by PyPI&apos;s own terms and privacy policy.</p>
        <p><strong>Receipts.</strong> When a capsule is served, Memty records which assistant received it, how many facts and tokens it contained and which slots were used. Receipts never contain fact values. See them with <code>memty report</code>.</p>
        <Callout title="The vault file is not encrypted" tone="warn">
          <p>Memty relies on your computer account&apos;s protection. If your home folder is synced to OneDrive, Dropbox, iCloud or similar, your vault may be uploaded there. Keep it out of synced folders unless you want that.</p>
        </Callout>
      </DocSection>

      <DocSection id="extension" title="The browser extension">
        <p>The Memty Bridge extension runs only on the chat sites it supports: ChatGPT, Claude.ai, Gemini and Perplexity. On those pages it adds Memty buttons. It reads text only when you select it and click <strong>Save to Memty</strong>, and it writes a capsule into the message box only when you click <strong>Memty</strong>.</p>
        <p>The extension talks only to the bridge on <code>127.0.0.1</code>. In your browser&apos;s extension storage it keeps the pairing token, the namespace you picked and the position of its button. It does not send data to the Memty project or to anyone else.</p>
        <p>A capsule you paste into a chat is sent to that AI provider <strong>when you press send</strong>, under that provider&apos;s terms. You can review and edit it before sending.</p>
      </DocSection>

      <DocSection id="mcp" title="Coding agents and desktop apps (MCP)">
        <p>When you connect an app with <code>memty connect</code>, it can ask Memty for a capsule (<code>memty_sync</code>) or propose a fact (<code>memty_propose</code>). MCP clients are treated as cloud assistants, so the privacy gate applies to every capsule they receive. A change an agent proposes to an existing fact waits in <code>memty inbox</code> until you approve it.</p>
        <p>What the agent then sends to its model provider is governed by that app and provider.</p>
      </DocSection>

      <DocSection id="providers" title="AI providers you choose">
        <p>Memty decides what an assistant <em>may</em> see. The privacy gate applies these rules to every capsule:</p>
        <div className="doc-table">
          <table>
            <thead><tr><th>Level</th><th>Cloud assistants receive</th></tr></thead>
            <tbody>
              <tr><td><span className="doc-lvl is-public">PUBLIC</span></td><td>The value</td></tr>
              <tr><td><span className="doc-lvl is-internal">INTERNAL</span></td><td>Nothing, unless you trust that assistant</td></tr>
              <tr><td><span className="doc-lvl is-confidential">CONFIDENTIAL</span></td><td>The placeholder <code>[private]</code></td></tr>
              <tr><td><span className="doc-lvl is-secret">SECRET</span></td><td>Nothing. The request is refused and a local model is suggested.</td></tr>
            </tbody>
          </table>
        </div>
        <p>API keys, tokens, private keys and password lines are always stored as SECRET. Once you send a message, the provider&apos;s own policies decide how it is stored and used. The privacy gate is a safeguard, not a substitute for checking what you send.</p>
      </DocSection>

      <DocSection id="website" title="This website">
        <p>This site is a static website hosted on GitHub Pages. It has no login, sets no cookies and uses no analytics or advertising trackers.</p>
        <ul>
          <li><strong>Hosting.</strong> GitHub serves the pages and, like any web host, may log technical data such as your IP address. See the <a href="https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement" target="_blank" rel="noreferrer">GitHub Privacy Statement</a>.</li>
          <li><strong>Fonts.</strong> Typefaces are loaded from Google Fonts, so your browser contacts Google&apos;s servers. See the <a href="https://policies.google.com/privacy" target="_blank" rel="noreferrer">Google Privacy Policy</a>.</li>
          <li><strong>Links.</strong> Links to GitHub, PyPI and other sites take you to services with their own policies.</li>
        </ul>
      </DocSection>

      <DocSection id="demo" title="The demo workspace">
        <p>The <Link href="/workspace">demo workspace</Link> runs entirely in your browser. It never calls an AI model, and nothing you type is uploaded. The assistants in it are simulated.</p>
        <p>Your demo vault, chats and tour progress are saved in your browser&apos;s local storage on this device, so they are still there when you come back. Click <strong>Reset</strong> in the demo, or clear this site&apos;s data in your browser, to remove them.</p>
      </DocSection>

      <DocSection id="control" title="Your control and deletion">
        <p>Because your data is on your computer, you control it directly:</p>
        <Code label="Terminal">{`memty list                          # see every active fact
memty forget work.project client    # delete a fact and its history
memty forget work.project client --purge-raw   # also delete archived source text
memty serve --new-token             # revoke every paired browser`}</Code>
        <p><code>memty forget</code> erases the value from the vault file on disk, including the search index and the write-ahead log. To remove everything, uninstall Memty and delete the <code>~/.memty</code> folder:</p>
        <Code label="Terminal">{`memty serve --no-autostart
pip uninstall memty`}</Code>
        <p>Remove the extension from <code>chrome://extensions</code> to delete its browser storage.</p>
      </DocSection>

      <DocSection id="security" title="Security">
        <p>The bridge accepts requests only from your paired browser extension, checks the <code>Host</code> header to block DNS rebinding and accepts only JSON writes. These protections are tested by adversarial tests anyone can run. See <a href={SECURITY_URL} target="_blank" rel="noreferrer">security testing</a>.</p>
        <p>Memty is alpha software (0.x) and has not been independently audited. To report a vulnerability, use the private <a href={`${GITHUB_URL}/security/advisories/new`} target="_blank" rel="noreferrer">GitHub security advisory form</a>. Please don&apos;t open a public issue.</p>
      </DocSection>

      <DocSection id="children" title="Children">
        <p>Memty is a developer tool and is not directed at children under 13, or a higher age where local law requires.</p>
      </DocSection>

      <DocSection id="changes" title="Changes and contact">
        <p>We will update this notice when Memty&apos;s data handling changes, and change the date at the top. Every revision is public in the project&apos;s <a href={`${GITHUB_URL}/commits/main/app/privacy/page.tsx`} target="_blank" rel="noreferrer">Git history</a>.</p>
        <p>Questions about privacy: open an issue on <a href={`${GITHUB_URL}/issues`} target="_blank" rel="noreferrer">GitHub</a>. Never include your real facts or tokens in an issue.</p>
      </DocSection>
    </DocLayout>
  );
}
