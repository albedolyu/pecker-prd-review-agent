# Pecker Web

Next.js 16 frontend for the Pecker PRD review workbench. This copy is sanitized
for the public repository: no `.env.local`, generated reports, build output, or
private workspaces are included.

## Dev

```bash
pnpm install --frozen-lockfile
pnpm dev
```

Open `http://127.0.0.1:3000/review?demo=1` for the backend-free demo flow.
The public copy defaults to demo-only mode. Set `NEXT_PUBLIC_PECKER_DEMO_ONLY=0`
only when you have a compatible backend and want to exercise auth/persistence.

If you wire it to a compatible local backend, set `NEXT_PUBLIC_SSE_BASE` in your
own uncommitted `.env.local`. Production should use same-origin `/api/*` routing.

## Verify

```bash
pnpm exec tsc --noEmit
pnpm test
pnpm build
```
