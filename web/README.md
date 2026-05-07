# Pecker Web

Next.js 16 frontend for the Pecker PRD review workbench.

## Dev

```bash
pnpm install
pnpm dev
```

Open `http://127.0.0.1:3000`.

The FastAPI backend should be running on `127.0.0.1:8000`:

```bash
cd ..
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

For local direct-to-backend debugging, set `NEXT_PUBLIC_SSE_BASE=http://127.0.0.1:8000` in `web/.env.local`. Production should use same-origin `/api/*` routing.

## Verify

```bash
pnpm exec tsc --noEmit
pnpm test
pnpm build
```

Current team-beta baseline: `pnpm test` has 91 Vitest cases, and production build is part of the release gate.
