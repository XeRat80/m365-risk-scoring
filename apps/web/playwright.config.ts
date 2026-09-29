import {defineConfig} from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  use: {baseURL: "http://127.0.0.1:3000", trace: "retain-on-failure"},
  webServer: process.env.CI ? undefined : {command: "pnpm dev", url: "http://127.0.0.1:3000", reuseExistingServer: true},
});
