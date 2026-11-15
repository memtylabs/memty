import type { Metadata, Viewport } from 'next';
import './globals.css';
import './memty.css';

export const metadata: Metadata = {
  title: 'Memty: persistent memory for AI assistants and agents',
  description:
    'One private, local memory vault shared by ChatGPT, Claude, Gemini, Perplexity, Cursor and every MCP agent.',
  applicationName: 'Memty',
  icons: { icon: '/static/assets/MemtySplash.png' },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  themeColor: '#07070c',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en">
    <head>
      <link rel="preconnect" href="https://fonts.googleapis.com" />
      <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=DM+Mono:wght@400;500&family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700&family=Instrument+Serif:ital@0;1&display=swap" rel="stylesheet" />
    </head>
    <body>{children}</body>
  </html>;
}
