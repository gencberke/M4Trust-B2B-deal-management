import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Varsayılan node; DOM davranışı gereken `.test.tsx` dosyaları dosya başı
    // `// @vitest-environment jsdom` yorumuyla jsdom'a geçer (node testleri değişmez).
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    restoreMocks: true,
  },
});
