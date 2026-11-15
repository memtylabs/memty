import type { Metadata } from 'next';
import Workspace from '@/components/workspace/workspace';

export const metadata: Metadata = {
  title: 'Memty demo workspace: try persistent AI memory in your browser',
  description:
    'Save facts from a chat, switch assistants, paste your memory with ⚡ Memty and watch the privacy gate work. Runs entirely in your browser.',
};

export default function Page() {
  return (
    <div className="mt mt-app">
      <Workspace />
    </div>
  );
}
