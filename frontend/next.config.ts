import type { NextConfig } from "next";

const buildDir=process.env.ROBOT_CARE_FRONTEND_DIST_DIR||'.next';
if(!['.next','.next-collection-demo'].includes(buildDir))throw new Error('Invalid frontend build directory.');
const nextConfig: NextConfig = {
  distDir: buildDir,
  typescript: {tsconfigPath:buildDir==='.next'?'tsconfig.json':'tsconfig.demo.json'},
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
