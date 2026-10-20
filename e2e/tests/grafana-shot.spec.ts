import { test } from "@playwright/test";
import path from "node:path";

// Not a test: captures the Grafana dashboard for the Substack guide.
//   docker compose -f docker-compose.yml -f ops/docker-compose.observability.yml up -d
//   SCREENSHOTS=1 npx playwright test grafana-shot
test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1 to capture guide screenshots");
test.use({ viewport: { width: 1400, height: 1500 } });

test("capture the Grafana dashboard", async ({ page }) => {
  test.setTimeout(90_000);
  await page.goto("http://localhost:3000/login");
  await page.getByLabel(/email or username/i).fill("admin");
  await page.getByLabel("Password", { exact: true }).fill("admin");
  await page.getByRole("button", { name: /log in/i }).click();
  const skip = page.getByRole("button", { name: /skip/i });
  if (await skip.isVisible({ timeout: 4000 }).catch(() => false)) await skip.click();
  await page.goto("http://localhost:3000/d/citesure-rag/citesure-rag-health?orgId=1&from=now-30m&to=now&kiosk");
  await page.waitForTimeout(8000);
  await page.screenshot({ path: path.resolve(__dirname, "../../substack/images/12-grafana-dashboard.png") });
});
