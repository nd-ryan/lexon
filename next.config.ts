import type { NextConfig } from "next";

const nextConfig: NextConfig = {
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
