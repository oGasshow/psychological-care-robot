import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  devIndicators: false,  // 关闭构建指示器
  reactCompiler: true,
  async rewrites() {
    // One server-only upstream for the existing application and /robot-care.
    const upstream = process.env.BACKEND_URL;
    if (!upstream || !/^https?:\/\//.test(upstream)) {
      throw new Error('Set BACKEND_URL to the internal FastAPI HTTP(S) origin before build/start.');
    }
    return [{ source: '/api/:path*', destination: `${upstream.replace(/\/$/, '')}/api/:path*` }];
  },
};

export default nextConfig;
