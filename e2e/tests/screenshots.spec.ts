import { expect, test, type Page } from "@playwright/test";
import path from "node:path";
import { ask, signIn } from "./helpers";

// Not a test: captures the screenshots used in the Substack guide (substack/images/).
//   SCREENSHOTS=1 npx playwright test screenshots
test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1 to capture guide screenshots");
test.use({ viewport: { width: 1280, height: 800 }, actionTimeout: 20_000 });

const OUT = path.resolve(__dirname, "../../substack/images");
// Let entrance animations finish, or the text is captured half faded.
const shot = async (page: Page, name: string) => {
  await page.waitForTimeout(900);
  await page.screenshot({ path: path.join(OUT, `${name}.png`) });
};

test("capture the guide screenshots", async ({ page, browser }) => {
  test.setTimeout(420_000);

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

test("capture the screenshots of the merged features", async ({ page, browser }) => {
  test.setTimeout(240_000);
  const admin = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await signIn(admin, "admin@acme.example");
  await signIn(page, "employee@acme.example");

  // Published research: the scope bar, and the keywords that would leave the machine (nothing is sent by a preview).
  await page.getByRole("link", { name: "Ask" }).click();
  await page.getByRole("link", { name: "New thread" }).click();
  await page.getByLabel("Both").check({ force: true });
  await page.getByLabel("Your question").fill("What does recent research say about retrieval augmented generation evaluation?");
  await page.getByRole("button", { name: "Preview what will be sent" }).click();
  await expect(page.getByText(/Only keywords/).first()).toBeVisible();
  await shot(page, "12-research-scope-preview");

  // The PDF viewer: the quoted words outlined on the real page, reading progress in the toolbar.
  await admin.getByRole("link", { name: "Ask" }).click();
  await admin.getByRole("link", { name: "New thread" }).click();
  await expect(admin.getByRole("heading", { name: /Answers you can/ })).toBeVisible();
  await admin.waitForTimeout(600);
  await ask(admin, "How long is a visitor badge valid?");
  await expect(admin.getByText("Every citation was checked against its source.")).toBeVisible();
  await shot(admin, "13-answer-from-pdf");
  await admin.getByRole("button", { name: "Open source 1" }).first().click();
  const dialog = admin.getByRole("dialog", { name: "Source" });
  await expect(dialog.getByRole("img", { name: /Page \d/ }).first()).toBeVisible({ timeout: 30_000 });
  await admin.waitForTimeout(1500);
  await shot(admin, "14-pdf-viewer-citation");
  await admin.keyboard.press("Escape");

  // The learning layer.
  await admin.getByRole("link", { name: "Learn" }).click();
  await expect(admin.getByRole("heading", { name: "Learn" })).toBeVisible();
  await shot(admin, "15-learn-overview");
  await admin.getByRole("navigation", { name: "Learn sections" }).getByRole("link", { name: /Study sets/ }).click();
  await admin.getByText("Week one: joining Acme").first().click();
  await expect(admin.getByText("Visitor And Badge Policy").first()).toBeVisible();
  await shot(admin, "16-study-set");
  await admin.getByRole("navigation", { name: "Learn sections" }).getByRole("link", { name: /Plans/ }).click();
  await admin.getByText("Onboarding in two weeks").first().click();
  await expect(admin.getByText("Onboarding in two weeks").first()).toBeVisible();
  await admin.waitForTimeout(500);
  await shot(admin, "17-learning-plan");

  // Admin pages added by the merge: watched folders, dashboard, audit log.
  await admin.getByRole("link", { name: "Inbox" }).click();
  await expect(admin.getByRole("heading", { name: "Watched folders" })).toBeVisible();
  await admin.waitForTimeout(500);
  await shot(admin, "18-inbox-watched-folders");
  await admin.getByRole("link", { name: "Dashboard" }).click();
  await expect(admin.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await admin.waitForTimeout(800);
  await shot(admin, "19-admin-dashboard");
  await admin.getByRole("link", { name: "Audit log" }).click();
  await expect(admin.getByRole("heading", { name: "Audit log" })).toBeVisible();
  await admin.getByRole("button", { name: "Verify chain" }).click();
  await expect(admin.getByText(/chain is intact|intact|verified/i).first()).toBeVisible();
  await admin.waitForTimeout(400);
  await shot(admin, "20-audit-log");
});
