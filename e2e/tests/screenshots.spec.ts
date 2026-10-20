import { expect, test, type Page } from "@playwright/test";
import path from "node:path";
import { ask, signIn } from "./helpers";

// Not a test: captures the screenshots used in the Substack guide (substack/images/).
//   SCREENSHOTS=1 npx playwright test screenshots
test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1 to capture guide screenshots");
test.use({ viewport: { width: 1280, height: 800 } });

const OUT = path.resolve(__dirname, "../../substack/images");
const shot = (page: Page, name: string) => page.screenshot({ path: path.join(OUT, `${name}.png`) });

test("capture the guide screenshots", async ({ page, browser }) => {
  test.setTimeout(180_000);

  await page.goto("/");
  await shot(page, "01-login");

  // Employee: a verified answer, the source viewer, and a refusal.
  await signIn(page, "employee@acme.example");
  await ask(page, "How many weeks of paid parental leave do primary caregivers get?");
  await expect(page.getByText("Every citation was checked against its source.")).toBeVisible();
  await shot(page, "02-answer-with-citations");

  await page.getByRole("button", { name: "Open source 1" }).first().click();
  await expect(page.getByRole("dialog", { name: "Source" }).locator("mark")).toBeVisible();
  await shot(page, "03-source-viewer-highlight");
  await page.keyboard.press("Escape");

  await ask(page, "What is the maximum severance in weeks?");
  await expect(page.getByTestId("refusal")).toBeVisible();
  await shot(page, "04-refusal-for-restricted-question");

  await page.getByRole("link", { name: "Documents" }).click();
  await expect(page.getByRole("tab", { name: /General/ })).toBeVisible();
  await shot(page, "05-employee-documents-no-confidential");

  // HR: the same kind of question is answered from the confidential collection.
  const hr = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  await signIn(hr, "hr@acme.example");
  await ask(hr, "How is severance pay calculated?");
  await expect(hr.getByText(/Severance is 2 weeks of base pay/).first()).toBeVisible();
  await shot(hr, "06-hr-answer-from-confidential");
  await hr.close();

  // Admin: documents, access control, evaluation.
  const admin = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await signIn(admin, "admin@acme.example");
  await admin.getByRole("link", { name: "Documents" }).click();
  await expect(admin.getByText("Parental Leave Policy")).toBeVisible();
  await shot(admin, "07-admin-documents");

  await admin.getByRole("link", { name: "Workspace" }).click();
  await expect(admin.getByText("readable by: hr")).toBeVisible();
  await shot(admin, "08-workspace-access-control");

  await admin.getByRole("link", { name: "Quality" }).click();
  for (const [label, mode, rerank] of [
    ["screenshot vector-only", "vector", false],
    ["screenshot hybrid+rerank", "hybrid", true],
  ] as const) {
    await admin.getByLabel("Name (optional)").fill(label);
    await admin.getByLabel("Retrieval").selectOption(mode);
    const box = admin.getByLabel("Rerank");
    if ((await box.isChecked()) !== rerank) await box.click();
    await admin.getByRole("button", { name: "Start run" }).click();
    await expect(admin.getByRole("row").filter({ hasText: label }).getByText("done")).toBeVisible({ timeout: 60_000 });
  }
  const options = await admin.getByLabel("Base run").locator("option").allTextContents();
  const base = options.find((o) => o.startsWith("screenshot vector-only"));
  const head = options.find((o) => o.startsWith("screenshot hybrid+rerank"));
  await admin.getByLabel("Base run").selectOption({ label: base! });
  await admin.getByLabel("Head run").selectOption({ label: head! });
  await expect(admin.getByText("Change")).toBeVisible();
  await admin.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await shot(admin, "09-quality-compare");

  // Thumbs-down feedback and the admin's queue.
  await page.getByRole("link", { name: "Ask" }).click();
  await ask(page, "What is the company's sabbatical policy?");
  await expect(page.getByTestId("refusal")).toBeVisible();
  await page.getByRole("button", { name: "Thumbs down" }).click();
  await page.getByLabel("Feedback comment").fill("We do offer a sabbatical after five years.");
  await shot(page, "10-feedback-comment");
  await page.getByRole("button", { name: "Send feedback" }).click();
  await admin.getByRole("link", { name: "Feedback" }).click();
  await expect(admin.getByText("We do offer a sabbatical after five years.").first()).toBeVisible();
  await shot(admin, "11-feedback-queue");
});
