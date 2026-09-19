import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  testMatch: "*.spec.ts",
  use: { baseURL: "http://127.0.0.1:3000", headless: true },
  workers: 1,
  reporter: "list",
});
