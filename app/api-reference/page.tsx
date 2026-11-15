import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import Link from 'next/link';
import { Callout, Code, DocLayout, DocSection } from '@/components/site/doc-layout';
import { DOCS_URL, GITHUB_URL } from '@/components/site/brand';

export const metadata: Metadata = {
  title: 'API reference | Memty',
  description: 'Build with Memty: the Python API, MCP tools, CLI and local bridge for a private, local AI memory vault.',
};

const TOC = [
  { id: 'overview', label: 'Overview' },
  { id: 'concepts', label: 'Core concepts' },
  { id: 'python', label: 'Python API' },
  { id: 'mcp', label: 'MCP tools' },
  { id: 'cli', label: 'Command line' },
  { id: 'bridge', label: 'Local HTTP bridge' },
  { id: 'errors', label: 'Errors' },
  { id: 'config', label: 'Configuration' },
  { id: 'limits', label: 'Limits' },
];

function Row({ cells }: { cells: ReactNode[] }) {
  return <tr>{cells.map((c, i) => <td key={i}>{c}</td>)}</tr>;
}

export default function ApiReferencePage() {
  return (
    <DocLayout
      path="/api-reference"
      eyebrow="Build with Memty"
      title="API reference"
      updated="November 15, 2026 · memty 0.2.1"
      toc={TOC}
      lede={<p>Every way to read and write a Memty vault from your own code, agents and tools. Everything runs on your computer: there is no hosted API, no API key and no rate limit.</p>}
    >
      <DocSection id="overview" title="Overview">
        <p>There are four ways in. All of them use the same vault and the same privacy gate.</p>
        <div className="doc-cards">
          <a href="#python"><b>Python API</b><span>Embed the vault in your own Python app or agent.</span></a>
          <a href="#mcp"><b>MCP tools</b><span>Claude Code, Cursor, Codex, VS Code, Windsurf, Claude Desktop.</span></a>
          <a href="#cli"><b>Command line</b><span>Scripts, terminals and the clipboard.</span></a>
          <a href="#bridge"><b>Local bridge</b><span>The HTTP service the browser extension uses.</span></a>
        </div>
        <Code label="Install">{`pip install memty     # Python 3.10+ on Windows, macOS or Linux`}</Code>
        <Callout title="Alpha (0.x)" tone="warn">
          <p>The vault&apos;s storage format is stable. Function signatures, commands and bridge routes may still change between 0.x versions. Pin a version in production: <code>memty==0.2.1</code>.</p>
        </Callout>
      </DocSection>

      <DocSection id="concepts" title="Core concepts">
        <ul>
          <li><strong>Fact.</strong> One atomic <code>namespace.slot = value</code> entry of at most 40 tokens, for example <code>work.project.editor = &quot;VS Code&quot;</code>. Writing a slot again keeps the old value in its history.</li>
          <li><strong>Namespace.</strong> A dotted name such as <code>personal</code> or <code>work.billing-api</code> that keeps contexts apart. A request only reads the namespace you give it.</li>
          <li><strong>Capsule.</strong> The compiled block of facts an assistant receives, built under a hard token budget.</li>
          <li><strong>Provider.</strong> Who will read the capsule. <code>local</code>, <code>ollama</code>, <code>local_ollama</code> and <code>memty_local</code> are local and see every value. Any other name is treated as a cloud assistant.</li>
          <li><strong>Sensitivity.</strong> Decides what the privacy gate lets through to cloud providers:</li>
        </ul>
        <div className="doc-table">
          <table>
            <thead><tr><th>Level</th><th>Cloud providers receive</th><th>Local providers receive</th></tr></thead>
            <tbody>
              <Row cells={[<span key="l" className="doc-lvl is-public">PUBLIC</span>, 'The value', 'The value']} />
              <Row cells={[<span key="l" className="doc-lvl is-internal">INTERNAL</span>, 'Nothing, unless trusted', 'The value']} />
              <Row cells={[<span key="l" className="doc-lvl is-confidential">CONFIDENTIAL</span>, <code key="c">[private]</code>, 'The value']} />
              <Row cells={[<span key="l" className="doc-lvl is-secret">SECRET</span>, <>Request refused: <code>LocalRoutingRequired</code></>, 'The value']} />
            </tbody>
          </table>
        </div>
        <p>Values that look like credentials (API keys, tokens, private keys, <code>password:</code> lines) are always stored as SECRET, whatever sensitivity you pass.</p>
      </DocSection>

      <DocSection id="python" title="Python API">
        <Code label="Python">{`from memty import open_ledger, LocalRoutingRequired

vault = open_ledger()  # ~/.memty/ledger.sqlite3, or MEMTY_VAULT_PATH

vault.record("work.project", "editor", "VS Code", verification_state="USER_CONFIRMED")
vault.record("work.project", "client", "Acme Corp", sensitivity="CONFIDENTIAL")

capsule = vault.context("Which editor do I use?", provider="claude", namespace="work.project")
print(capsule["text"])  # the client appears only as [private]

vault.record("work.project", "db_password", "hunter2", sensitivity="SECRET")
try:
    vault.context("database password", provider="claude", namespace="work.project")
except LocalRoutingRequired as refused:
    print(refused.as_dict())  # suggests a local model; never contains the secret`}</Code>

        <h3>Functions and methods</h3>
        <div className="doc-table">
          <table>
            <thead><tr><th>Call</th><th>What it does</th></tr></thead>
            <tbody>
              <Row cells={[<code key="c">open_ledger()</code>, 'Open the default vault and return a MemtyLedger.']} />
              <Row cells={[<code key="c">record(namespace, slot, value, *, sensitivity=&quot;PUBLIC&quot;, verification_state=&quot;EXTRACTED&quot;)</code>, 'Create a fact or supersede the current value of a slot. Returns the stored fact as a dict. Use verification_state="USER_CONFIRMED" for facts the user stated, so extraction never overwrites them.']} />
              <Row cells={[<code key="c">context(query, *, provider, token_budget=600, namespace=None)</code>, 'Compile a capsule for provider. Returns a dict with text and citations. Raises LocalRoutingRequired if a SECRET fact matches for a cloud provider.']} />
              <Row cells={[<code key="c">list(*, namespace=None)</code>, 'List active facts, optionally for one namespace.']} />
              <Row cells={[<code key="c">history(namespace, slot)</code>, 'Return every earlier version of a slot.']} />
              <Row cells={[<code key="c">forget(namespace, slot, *, purge_raw=False)</code>, 'Delete a fact and its history from disk, including the search index and write-ahead log. purge_raw=True also deletes archived source text.']} />
            </tbody>
          </table>
        </div>
        <p>An extracted write to a slot the user deleted raises <code>TombstonedSlot</code>, and an extracted write over a user-confirmed fact raises <code>LockedSlot</code>. Writes with <code>verification_state=&quot;USER_CONFIRMED&quot;</code> are allowed. Both exceptions are importable from <code>memty</code>.</p>
      </DocSection>

      <DocSection id="mcp" title="MCP tools">
        <p>Connect a client with <code>memty connect</code> (add <code>--dry-run</code> to preview). It runs <code>memty mcp</code> over stdio and offers three tools. MCP clients are treated as cloud providers, so the privacy gate applies.</p>
        <h3><code>memty_sync</code></h3>
        <p>Recall a capsule of up to 120 tokens for a namespace. Only on the user&apos;s explicit request, it can also save or forget facts.</p>
        <div className="doc-table">
          <table>
            <thead><tr><th>Parameter</th><th>Type</th><th>Description</th></tr></thead>
            <tbody>
              <Row cells={[<code key="c">namespace</code>, 'string', 'Required. The namespace to read or write.']} />
              <Row cells={[<code key="c">action</code>, 'string', <><code>recall</code> (default), <code>remember</code> or <code>forget</code>.</>]} />
              <Row cells={[<code key="c">query</code>, 'string', 'Optional question used to rank facts.']} />
              <Row cells={[<><code>slot</code>, <code>value</code></>, 'string', 'The fact to remember, or the slot to forget.']} />
              <Row cells={[<code key="c">sensitivity</code>, 'string', 'Level for a remembered fact. Default PUBLIC.']} />
              <Row cells={[<code key="c">set_slots</code>, 'object', 'Save 1 to 25 slot/value pairs at once, then return the updated capsule.']} />
            </tbody>
          </table>
        </div>
        <h3><code>memty_propose</code></h3>
        <p>Suggest a fact the agent learned: <code>namespace</code>, <code>slot</code>, <code>value</code>, optional <code>reason</code> and <code>sensitivity</code>. A new slot is saved as extracted. A change to an existing or deleted slot is queued for the user in <code>memty inbox</code> and returns <code>status: &quot;pending_review&quot;</code>.</p>
        <h3><code>memty_drill</code></h3>
        <p>Read the archived source text behind one slot (<code>namespace</code>, <code>slot</code>). Available only when the server runs as a local provider; cloud clients get <code>error: &quot;local_only&quot;</code>.</p>
        <Callout title="Clients don't load memory on their own">
          <p>Ask the assistant to call <code>memty_sync</code>, or add that instruction to the client&apos;s agent settings, for example a project <code>CLAUDE.md</code> or Cursor rules.</p>
        </Callout>
      </DocSection>

      <DocSection id="cli" title="Command line">
        <div className="doc-table">
          <table>
            <thead><tr><th>Command</th><th>What it does</th></tr></thead>
            <tbody>
              <Row cells={[<code key="c">memty remember NS SLOT VALUE</code>, <>Save a fact. <code>--sensitivity SECRET</code> keeps it on this computer.</>]} />
              <Row cells={[<code key="c">memty recall &quot;question&quot;</code>, <>Print the capsule for a question. <code>--namespace</code> and <code>--provider</code> narrow it.</>]} />
              <Row cells={[<code key="c">memty clip NS</code>, 'Copy a namespace’s capsule to the clipboard for any AI app.']} />
              <Row cells={[<code key="c">memty list</code>, 'List active facts.']} />
              <Row cells={[<code key="c">memty history NS SLOT</code>, 'Show earlier versions of one fact.']} />
              <Row cells={[<code key="c">memty forget NS SLOT</code>, <>Delete a fact and its history. <code>--purge-raw</code> also deletes archived source.</>]} />
              <Row cells={[<code key="c">memty scan</code>, 'Save baseline facts about a code project from its manifests, with no model and no network.']} />
              <Row cells={[<code key="c">memty inbox</code>, <>Facts agents proposed. <code>memty approve N</code> / <code>memty reject N</code>.</>]} />
              <Row cells={[<code key="c">memty report</code>, 'Receipts: capsules served, facts reused, tokens saved, secrets protected.']} />
              <Row cells={[<code key="c">memty serve --autostart</code>, <>Start the browser bridge now and at login. <code>--stop</code>, <code>--no-autostart</code>, <code>--new-token</code>.</>]} />
              <Row cells={[<code key="c">memty extension --open</code>, 'Install or update the browser extension folder and open it.']} />
              <Row cells={[<code key="c">memty pair</code>, 'Allow one more browser to pair within two minutes.']} />
              <Row cells={[<code key="c">memty connect</code>, 'Connect MCP clients through their official installers.']} />
              <Row cells={[<code key="c">memtyd status | start | stop</code>, 'Check or control the shared background daemon.']} />
            </tbody>
          </table>
        </div>
        <p>Run <code>memty --help</code> or <code>memty COMMAND --help</code> for every option. On Windows, use <code>py -m memty</code> if <code>memty</code> is not on your PATH.</p>
      </DocSection>

      <DocSection id="bridge" title="Local HTTP bridge">
        <p><code>memty serve</code> starts a small HTTP service on <code>http://127.0.0.1:8765</code>. It exists for the Memty Bridge browser extension and is locked down accordingly:</p>
        <ul>
          <li>Every data route needs <code>Authorization: Bearer &lt;token&gt;</code>. The token is stored beside the vault with owner-only permissions.</li>
          <li>Requests from web pages are refused. Only browser-extension origins, or an origin you allow with <code>--allow-origin</code>, are accepted.</li>
          <li>The <code>Host</code> header must be <code>127.0.0.1</code> or <code>localhost</code>, which blocks DNS rebinding.</li>
          <li>Writes must be <code>application/json</code>.</li>
          <li>Every capsule is compiled for a cloud provider, so the privacy gate always applies.</li>
        </ul>
        <Callout title="Internal interface" tone="warn">
          <p>The bridge is built for the extension and may change in any 0.x release. For your own integrations, prefer the Python API or MCP.</p>
        </Callout>
        <div className="doc-table">
          <table>
            <thead><tr><th>Route</th><th>Description</th></tr></thead>
            <tbody>
              <Row cells={[<code key="c">GET /health</code>, <>No auth. Returns <code>{'{"ok": true, "service": "memty"}'}</code>.</>]} />
              <Row cells={[<code key="c">GET /capsule</code>, <><code>namespace</code> (required), <code>provider</code>, <code>query</code>, <code>context</code>, <code>tokens</code> (default 350), <code>scope</code> (<code>latest</code> | <code>all</code>), <code>format</code> (<code>text</code> | <code>xml</code>). Returns <code>text</code>, <code>approx_tokens</code>, <code>facts</code>, <code>omitted</code>, <code>redacted</code>.</>]} />
              <Row cells={[<code key="c">GET /contexts</code>, 'Saved contexts with fact counts and a provider-safe preview.']} />
              <Row cells={[<code key="c">GET /facts</code>, 'Facts in a namespace. Private values are returned as null and never reach the browser.']} />
              <Row cells={[<code key="c">GET /namespaces</code>, 'Namespaces with fact counts.']} />
              <Row cells={[<code key="c">POST /extract</code>, <>Propose facts from <code>text</code> (up to 50,000 characters) using local rules.</>]} />
              <Row cells={[<code key="c">POST /facts</code>, <>Save facts: <code>namespace</code> and <code>facts</code>.</>]} />
              <Row cells={[<code key="c">POST /facts/update</code>, 'Edit, rename or change the privacy of a fact.']} />
              <Row cells={[<code key="c">POST /facts/delete</code>, <>Forget a fact: <code>namespace</code> and <code>slot</code>.</>]} />
              <Row cells={[<code key="c">POST /pair</code>, 'Pairing for the extension. Only browser-extension origins can call it.']} />
            </tbody>
          </table>
        </div>
      </DocSection>

      <DocSection id="errors" title="Errors">
        <div className="doc-table">
          <table>
            <thead><tr><th>Where</th><th>Error</th><th>Meaning</th></tr></thead>
            <tbody>
              <Row cells={['Python', <code key="c">LocalRoutingRequired</code>, <>A SECRET fact matched for a cloud provider. <code>as_dict()</code> gives <code>provider</code>, <code>suggested_provider</code>, <code>namespace</code> and <code>slot</code>, never the value.</>]} />
              <Row cells={['Python', <code key="c">LockedSlot</code>, 'Extraction tried to overwrite a fact the user confirmed.']} />
              <Row cells={['Python', <code key="c">TombstonedSlot</code>, 'An extracted write targeted a slot the user deleted.']} />
              <Row cells={['Bridge 400', <code key="c">invalid_request</code>, 'A parameter is missing or out of range.']} />
              <Row cells={['Bridge 401', <code key="c">unauthorized</code>, 'Missing or wrong pairing token.']} />
              <Row cells={['Bridge 403', <><code>origin_not_allowed</code>, <code>bad_host</code>, <code>pairing_required</code></>, 'The caller is a web page, the Host header is wrong, or this browser has not been paired (run memty pair).']} />
              <Row cells={['Bridge 404', <><code>not_found</code>, <code>context_not_found</code></>, 'Unknown route, or the selected context changed.']} />
              <Row cells={['Bridge 409', <code key="c">local_routing_required</code>, 'A SECRET fact cannot be sent to a web assistant.']} />
              <Row cells={['Bridge 415', <code key="c">json_required</code>, 'Writes must be application/json.']} />
            </tbody>
          </table>
        </div>
      </DocSection>

      <DocSection id="config" title="Configuration">
        <div className="doc-table">
          <table>
            <thead><tr><th>Setting</th><th>Default</th><th>Purpose</th></tr></thead>
            <tbody>
              <Row cells={[<><code>--db</code> or <code>MEMTY_VAULT_PATH</code></>, <code key="d">~/.memty/ledger.sqlite3</code>, 'Where the vault lives.']} />
              <Row cells={[<><code>--user</code> or <code>MEMTY_USER</code></>, <code key="d">local</code>, 'User inside the vault.']} />
              <Row cells={[<code key="c">MEMTY_PROVIDER</code>, <code key="d">mcp</code>, 'How MCP clients are treated by the privacy gate (cloud by default).']} />
              <Row cells={[<code key="c">MEMTY_OLLAMA_MODEL</code>, 'not set', 'Use a local Ollama model to extract facts.']} />
              <Row cells={[<code key="c">memty serve --port</code>, <code key="d">8765</code>, 'Port for the local bridge.']} />
            </tbody>
          </table>
        </div>
      </DocSection>

      <DocSection id="limits" title="Limits">
        <div className="doc-table">
          <table>
            <thead><tr><th>Limit</th><th>Value</th></tr></thead>
            <tbody>
              <Row cells={['Tokens per fact', '40']} />
              <Row cells={['Default capsule budget (Python)', '600 tokens']} />
              <Row cells={['MCP recall capsule', '120 tokens']} />
              <Row cells={['Bridge capsule', '350 tokens by default; 1 to 600, or up to 2,000 for a selected context']} />
              <Row cells={['memty_sync set_slots', '1 to 25 pairs']} />
              <Row cells={['Extraction input', '50,000 characters']} />
            </tbody>
          </table>
        </div>
        <p>More detail: the <a href={DOCS_URL} target="_blank" rel="noreferrer">package README</a>, the <Link href="/workspace">demo workspace</Link>, and the source on <a href={GITHUB_URL} target="_blank" rel="noreferrer">GitHub</a>.</p>
      </DocSection>
    </DocLayout>
  );
}
