import type { Metadata } from 'next';
import Link from 'next/link';
import { Callout, DocLayout, DocSection } from '@/components/site/doc-layout';
import { GITHUB_URL } from '@/components/site/brand';

export const metadata: Metadata = {
  title: 'Terms of use | Memty',
  description: 'Terms for using the Memty open-source software, this website and the demo workspace.',
};

const LICENSE_URL = `${GITHUB_URL}/blob/main/LICENSE`;

const TOC = [
  { id: 'overview', label: 'Overview' },
  { id: 'license', label: 'The software license' },
  { id: 'alpha', label: 'Alpha software' },
  { id: 'your-data', label: 'Your data and choices' },
  { id: 'third-parties', label: 'Third-party services' },
  { id: 'trademarks', label: 'Names and logos' },
  { id: 'acceptable-use', label: 'Acceptable use' },
  { id: 'warranty', label: 'No warranty' },
  { id: 'liability', label: 'Limitation of liability' },
  { id: 'changes', label: 'Changes and contact' },
];

export default function TermsPage() {
  return (
    <DocLayout
      path="/terms"
      eyebrow="Legal"
      title="Terms of use"
      updated="November 15, 2026"
      toc={TOC}
      lede={<p>Memty is free, open-source software. These terms explain what you can expect from it, and what is up to you, when you use the software, this website or the demo workspace.</p>}
    >
      <DocSection id="overview" title="Overview">
        <Callout title="In short">
          <ul>
            <li>The software is MIT licensed: use, change and share it freely.</li>
            <li>It is alpha software, provided as is, without warranty.</li>
            <li>Your memory stays on your computer, and you decide what to send to AI assistants.</li>
          </ul>
        </Callout>
        <p>By using Memty or this website, you agree to these terms. If you don&apos;t agree, please don&apos;t use them. The software itself is also governed by its license, described below. If the two conflict for the software, the license wins.</p>
      </DocSection>

      <DocSection id="license" title="The software license">
        <p>The Memty package, browser extension, MCP server and this website&apos;s source code are released under the <a href={LICENSE_URL} target="_blank" rel="noreferrer">MIT License</a>. You may use, copy, modify, merge, publish, distribute, sublicense and sell copies, as long as you keep the copyright and license notice.</p>
        <p>Memty is free. There is no paid plan, account or subscription.</p>
      </DocSection>

      <DocSection id="alpha" title="Alpha software">
        <p>Memty is in alpha (version 0.x). The vault&apos;s storage format is stable and covered by tests, but commands, options and the local bridge may change between versions. Features may be changed or removed.</p>
        <p>Keep a backup of anything you can&apos;t afford to lose, including your vault file, and read the <a href={`${GITHUB_URL}/blob/main/memty/CHANGELOG.md`} target="_blank" rel="noreferrer">changelog</a> before upgrading.</p>
      </DocSection>

      <DocSection id="your-data" title="Your data and choices">
        <p>Your vault is stored on your own computer and belongs to you. The Memty project does not receive, store or license your facts.</p>
        <p>You are responsible for what you save and what you send. Memty&apos;s privacy gate masks private values and refuses secrets, but it is a safeguard, not a guarantee. Review each capsule before you send it, and only store information you have the right to store.</p>
        <p>See the <Link href="/privacy">privacy notice</Link> for exactly what data each part of Memty touches.</p>
      </DocSection>

      <DocSection id="third-parties" title="Third-party services">
        <p>Memty works alongside services it does not control, including ChatGPT, Claude, Gemini, Perplexity, Cursor, VS Code, Ollama, GitHub and PyPI. When you send content to them, their terms and privacy policies apply. Memty is not responsible for their availability, output or handling of your data.</p>
        <p>AI output can be wrong, incomplete or unsuitable. Check it before relying on it, and don&apos;t treat it as professional medical, legal, financial or safety advice.</p>
      </DocSection>

      <DocSection id="trademarks" title="Names and logos">
        <p>ChatGPT, OpenAI, Claude, Anthropic, Gemini, Google, Perplexity, Cursor, Ollama and other product names and logos shown on this site belong to their respective owners. They are used only to say which tools Memty works with. Memty is an independent open-source project and is not affiliated with, sponsored or endorsed by those companies.</p>
        <p>The MIT License covers Memty&apos;s code, not its name or logo. You may say your project uses or is based on Memty, but you may not present a modified copy as the official Memty or suggest it is endorsed by it.</p>
      </DocSection>

      <DocSection id="acceptable-use" title="Acceptable use">
        <p>Please don&apos;t use Memty or this website to:</p>
        <ul>
          <li>break the law or infringe anyone&apos;s rights, including storing personal data you have no right to process;</li>
          <li>attack, overload or try to break this website or anyone else&apos;s systems;</li>
          <li>hide malware in, or misrepresent, modified copies of Memty.</li>
        </ul>
        <p>Security research on your own installation is welcome. Report what you find privately through the <a href={`${GITHUB_URL}/security/advisories/new`} target="_blank" rel="noreferrer">GitHub security advisory form</a>.</p>
      </DocSection>

      <DocSection id="warranty" title="No warranty">
        <p>Memty, this website and the demo are provided <strong>&ldquo;as is&rdquo;</strong>, without warranty of any kind, express or implied, including warranties of merchantability, fitness for a particular purpose, title and non-infringement, as stated in the MIT License. We don&apos;t promise that Memty will be error-free, secure against every attack, or always available.</p>
      </DocSection>

      <DocSection id="liability" title="Limitation of liability">
        <p>To the fullest extent permitted by law, the authors and copyright holders are not liable for any claim, damages or other liability, whether in contract, tort or otherwise, arising from or in connection with Memty or its use, including loss of data. Some jurisdictions don&apos;t allow certain limits, so parts of this section may not apply to you. Nothing here limits rights you have under consumer law that can&apos;t be waived.</p>
      </DocSection>

      <DocSection id="changes" title="Changes and contact">
        <p>We may update these terms as Memty changes. The date at the top shows the latest version, and every revision is public in the project&apos;s <a href={`${GITHUB_URL}/commits/main/app/terms/page.tsx`} target="_blank" rel="noreferrer">Git history</a>. Using Memty after a change means you accept the updated terms.</p>
        <p>Questions: open an issue on <a href={`${GITHUB_URL}/issues`} target="_blank" rel="noreferrer">GitHub</a>.</p>
      </DocSection>
    </DocLayout>
  );
}
