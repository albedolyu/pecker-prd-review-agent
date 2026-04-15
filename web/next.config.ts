import type { NextConfig } from "next";

/**
 * 啄木鸟 Next.js 前端配置
 *
 * 开发模式(pnpm dev, :3000):
 * /api/* 请求通过 rewrite 代理到 FastAPI 后端(127.0.0.1:8000),
 * 避免 CORS 预检 + 原生透传 HttpOnly cookie(pecker_session)+ SSE 流。
 *
 * 生产模式: 由反向代理(nginx / caddy)处理,rewrite 主要给 dev。
 */
const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8000/api/:path*",
      },
    ];
  },
};

export default nextConfig;
