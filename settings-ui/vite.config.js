import { defineConfig } from "vite";
import { fileURLToPath } from "node:url";

const assistant = process.env.WATCHED_KETTLE_EDITION !== "pet-only";
// index.html allows the dev server's hot-reload socket; built pages load
// everything from the bundle, so the shipped policy drops it.
const DEV_SOCKET = " ws://127.0.0.1:5178";
const shippedPolicy = {
  name: "watched-kettle-shipped-csp",
  apply: "build",
  transformIndexHtml(html) {
    if (!html.includes(DEV_SOCKET)) {
      throw new Error("index.html no longer lists the dev socket");
    }
    return html.replace(DEV_SOCKET, "");
  },
};
export default defineConfig({
  base: "./",
  plugins: [shippedPolicy],
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
