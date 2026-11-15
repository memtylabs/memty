import type { NextConfig } from 'next';

/**
 * Set PAGES_BASE_PATH (for example "/memty") to build the static GitHub Pages
 * site: a static export served from a sub-path. Without it, this is the
 * normal server build used by `npm run dev` and `npm start`.
 */
const pagesBasePath = process.env.PAGES_BASE_PATH;
const isPagesBuild = pagesBasePath !== undefined;

const nextConfig: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  outputFileTracingRoot: process.cwd(),
  env: { NEXT_PUBLIC_BASE_PATH: pagesBasePath ?? '' },
  ...(isPagesBuild
    ? {
        output: 'export',
        basePath: pagesBasePath || undefined,
        trailingSlash: true,
        images: { unoptimized: true },
      }
    : {
        async headers() {
          return [{
            source: '/:path*',
            headers: [
              { key: 'X-Content-Type-Options', value: 'nosniff' },
              { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
              { key: 'X-Frame-Options', value: 'SAMEORIGIN' },
            ],
          }];
        },
      }),
};

export default nextConfig;
