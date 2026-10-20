import { defineConfig, devices } from "@playwright/test";

// Run against the Docker Compose stack:
//   docker compose up -d --build --wait && docker compose run --rm api python -m app.seed
//   cd e2e && npm ci && npx playwright install chromium && npx playwright test
export default defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false, // the tests share one seeded database; keep their order predictable
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
