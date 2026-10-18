import { defineConfig } from "vite";
import { fileURLToPath } from "node:url";

const assistant = process.env.WATCHED_KETTLE_EDITION !== "pet-only";
export default defineConfig({
  base: "./",
  define: { __ASSISTANT__: JSON.stringify(assistant) },
  resolve: {
    alias: {
      "@assistant": fileURLToPath(
        new URL(
          assistant
            ? "./src/AssistantPages.tsx"
            : "./src/AssistantUnavailable.tsx",
          import.meta.url,
        ),
      ),
    },
  },
  build: {
    sourcemap: false,
    commonjsOptions: { include: [/node_modules/, /localization\.cjs$/] },
  },
  // The bundled Pretendard fonts live in the repository-level assets folder.
  server: { fs: { allow: [".."] } },
});
