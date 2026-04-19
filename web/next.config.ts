import type { NextConfig } from "next";

/**
 * 啄木鸟 Next.js 前端配置
 *
 * 开发模式(pnpm dev :3000):
 * /api/* 请求通过 rewrite 代理到 FastAPI 后端(127.0.0.1:8000),
 * 避免 CORS 预检 + 原生透传 HttpOnly cookie + SSE 流。
 *
 * 生产模式:
 * - Docker 部署: next build → standalone server · nginx 反代(或 Next.js rewrite 内置转发)
 *   Docker compose 环境下 API_BASE_URL=http://api:8000(容器内 service 名)
 * - Vercel 部署: build 发布到 Vercel edge · API 侧需单独部署到公网(Railway/Fly/自机)
 *   Vercel 环境变量 API_BASE_URL 填后端公网地址 · 走 rewrite 转发
 */

// standalone output · Docker 镜像只拷 .next/standalone + .next/static + public · 体积小
// Vercel 自动识别无视此配置
const API_BASE = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_BASE}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
