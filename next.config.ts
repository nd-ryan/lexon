import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Silence Next.js warning about inferred workspace root when multiple lockfiles exist.
  // We want build tracing to be scoped to this repo directory.
  outputFileTracingRoot: process.cwd(),

  // Suppress ESLint warnings during `next build` (still enforced via `npm run lint`).
  eslint: {
    ignoreDuringBuilds: true,
  },

  async redirects() {
    return [
      {
        source: '/white-paper',
        destination: '/whitepaper.pdf',
        permanent: true,
      },
    ];
  },
};

export default nextConfig;
