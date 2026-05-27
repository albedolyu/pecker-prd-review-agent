import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./"),
    },
  },
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
    // Playwright 测试用 .spec.ts 后缀,放在 tests/e2e/,
    // 明确排除避免 vitest 误当作单元测试
    exclude: ["tests/e2e/**", "node_modules/**", ".next/**"],
  },
});
