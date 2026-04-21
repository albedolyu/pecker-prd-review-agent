# 啄木鸟 v8 前端 · Next.js 16 standalone Docker 镜像
#
# 参考:https://nextjs.org/docs/app/api-reference/config/next-config-js/output
#
# 用法(docker-compose):
#   docker compose build web
#   docker compose up web
#
# 单独构建 + 跑:
#   cd web && docker build -t pecker-web . && docker run -p 3000:3000 pecker-web

# ============================================================
# Stage 1 · deps(缓存 node_modules)
# ============================================================
FROM node:20-slim AS deps
WORKDIR /app

RUN corepack enable && corepack prepare pnpm@latest --activate

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# ============================================================
# Stage 2 · builder(next build · 吐 standalone)
# ============================================================
FROM node:20-slim AS builder
WORKDIR /app

RUN corepack enable && corepack prepare pnpm@latest --activate

ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# build 时 Google Fonts 下载 · 网络受限时用 docker build --build-arg HTTPS_PROXY=http://...
ARG HTTPS_PROXY
ENV HTTPS_PROXY=${HTTPS_PROXY}

# API_BASE_URL: Next.js 15 的 rewrites 在 build 阶段求值并序列化到
# routes-manifest,runtime env 改不动。所以必须 build 阶段就设对。
# 默认 host.docker.internal 覆盖"容器 frontend + 宿主机 api"场景(内测主力用法);
# compose 环境下走 api:8000 可以传 --build-arg API_BASE_URL=http://api:8000 覆盖。
ARG API_BASE_URL=http://host.docker.internal:8000
ENV API_BASE_URL=${API_BASE_URL}

RUN pnpm build

# ============================================================
# Stage 3 · runner(体积 < 200 MB · 非 root)
# ============================================================
FROM node:20-slim AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN groupadd --system --gid 1001 nodejs \
 && useradd --system --uid 1001 --gid nodejs nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

CMD ["node", "server.js"]
