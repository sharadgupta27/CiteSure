import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./helpers";

// The public research lane in a real browser, with no internet: the stack runs with the invented papers
//   PUBLIC_RESEARCH_ENABLED=true PUBLIC_SOURCES=sample PUBLIC_LLM_PROVIDER=fake docker compose up -d
// (CI does this). Against a stack without the lane the tests are skipped, not failed.

async function laneIsOffline(page: Page): Promise<boolean> {
  const token = await page.evaluate(() => localStorage.getItem("citesure.token")); // AuthContext's STORAGE_KEY
  const response = await page.request.get("/api/v1/public-research", {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok()) return false;
  const status = (await response.json()) as { enabled: boolean; sources: string[] };
  return status.enabled && status.sources.includes("sample");
}

test.describe("public research lane (offline sample papers)", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page, "employee@acme.example");
    test.skip(!(await laneIsOffline(page)), "start the stack with PUBLIC_RESEARCH_ENABLED=true PUBLIC_SOURCES=sample");
    await page.getByRole("link", { name: "New thread" }).click();
  });

  test("published research: preview the keywords, then a cited answer that says what was sent", async ({ page }) => {
    await page.getByLabel("Your question").fill("How does sparse attention reduce memory use for long sequences?");
    await page.getByLabel("Published research").check({ force: true });

    await page.getByRole("button", { name: "Preview what will be sent" }).click();
    const preview = page.getByTestId("preview");
    await expect(preview.getByText("Allowed: nothing sensitive was found in these keywords.")).toBeVisible();
    const keywords = await page.getByLabel("Public search keywords (you can edit them)").inputValue();
    expect(keywords.toLowerCase()).toContain("sparse");

    await page.getByRole("button", { name: "Ask", exact: true }).click();
    await expect(page.getByText("Every citation was checked against its source.")).toBeVisible();
    await expect(page.getByText(/\[Sample\] Sparse attention for long sequences/).first()).toBeVisible();
    await expect(page.getByText("Public", { exact: true }).first()).toBeVisible();
    await expect(page.getByTestId("egress")).toContainText("Public search: keywords sent to sample");
  });

  test("both: personal data in the question is blocked, and asking anyway sends nothing", async ({ page }) => {
    await page.getByLabel("Your question").fill("Research on remote work for jane.doe@acme.example please");
    await page.getByLabel("Both").check({ force: true });

    await page.getByRole("button", { name: "Preview what will be sent" }).click();
    await expect(page.getByTestId("preview").getByRole("alert")).toContainText("Blocked: it contains personal data");

    await page.getByRole("button", { name: "Ask", exact: true }).click();
    await expect(page.getByTestId("egress")).toContainText("Public search: nothing was sent");
  });
});
