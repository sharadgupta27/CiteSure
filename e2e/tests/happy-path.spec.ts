import { expect, test } from "@playwright/test";
import { ask, signIn } from "./helpers";

test.describe("an employee asks a question", () => {
  test("gets a verified answer, opens the source and sees the quoted words highlighted", async ({ page }) => {
    await signIn(page, "employee@acme.example");
    await ask(page, "How many weeks of paid parental leave do primary caregivers get?");

    // The answer streams in, then shows with numbered citations (the sentence also appears in the source list).
    await expect(page.getByText("Primary caregivers receive 16 weeks of fully paid leave.").first()).toBeVisible();
    await expect(page.getByText("Every citation was checked against its source.")).toBeVisible();

    // Clicking the citation opens the source with the quoted span highlighted.
    await page.getByRole("button", { name: "Open source 1" }).first().click();
    const viewer = page.getByRole("dialog", { name: "Source" });
    await expect(viewer.getByText("Parental Leave Policy").first()).toBeVisible();
    await expect(viewer.locator("mark")).toContainText("16 weeks of fully paid leave");
    await page.keyboard.press("Escape");
    await expect(viewer).toBeHidden();
  });

  test("is refused when the answer only exists in a collection they may not read", async ({ page }) => {
    await signIn(page, "employee@acme.example");
    await ask(page, "What is the maximum severance in weeks?");
    await expect(page.getByTestId("refusal")).toContainText("I don't have information on that");
    await expect(page.getByText("26 weeks")).toHaveCount(0);
    // Not even the title of the restricted document is offered as a "closest document".
    await expect(page.getByTestId("refusal")).not.toContainText("Severance And Layoff");
  });

  test("never sees the confidential collection anywhere in the UI", async ({ page }) => {
    await signIn(page, "employee@acme.example");
    await page.getByRole("link", { name: "Documents" }).click();
    await expect(page.getByRole("tab", { name: /General/ })).toBeVisible();
    await expect(page.getByRole("tab", { name: /People-Ops-Confidential/ })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Quality" })).toHaveCount(0); // admin-only pages are not even offered
  });

  test("a thumbs-down with a comment shows up in the admin's feedback queue", async ({ page, browser }) => {
    await signIn(page, "employee@acme.example");
    await ask(page, "What is the company's sabbatical policy?");
    await expect(page.getByTestId("refusal")).toBeVisible();
    await page.getByRole("button", { name: "Thumbs down" }).click();
    await page.getByLabel("Feedback comment").fill("We do offer a sabbatical after five years.");
    await page.getByRole("button", { name: "Send feedback" }).click();
    await expect(page.getByText("your feedback was saved")).toBeVisible();

    const adminContext = await browser.newContext();
    const adminPage = await adminContext.newPage();
    await signIn(adminPage, "admin@acme.example");
    await adminPage.getByRole("link", { name: "Feedback" }).click();
    await expect(adminPage.getByText("We do offer a sabbatical after five years.").first()).toBeVisible();
    await adminContext.close();
  });
});

test.describe("the HR user", () => {
  test("gets an answer cited to the confidential document", async ({ page }) => {
    await signIn(page, "hr@acme.example");
    await ask(page, "How is severance pay calculated?");
    await expect(page.getByText(/Severance is 2 weeks of base pay/).first()).toBeVisible();
    await page.getByRole("button", { name: "Open source 1" }).first().click();
    await expect(page.getByRole("dialog", { name: "Source" })).toContainText("Severance");
  });

  test("sees the confidential collection with its documents", async ({ page }) => {
    await signIn(page, "hr@acme.example");
    await page.getByRole("link", { name: "Documents" }).click();
    await page.getByRole("tab", { name: /People-Ops-Confidential/ }).click();
    await expect(page.getByText("Salary Bands (Confidential)")).toBeVisible();
  });
});

test.describe("the admin", () => {
  test("sees all documents ready and can run the evaluation suite", async ({ page }) => {
    await signIn(page, "admin@acme.example");
    await page.getByRole("link", { name: "Documents" }).click();
    await expect(page.getByText("Parental Leave Policy")).toBeVisible();
    await expect(page.locator("span", { hasText: /^ready$/ }).first()).toBeVisible();

    await page.getByRole("link", { name: "Quality" }).click();
    const runName = `e2e run ${Date.now()}`; // unique, so reruns against the same database do not collide
    await page.getByLabel("Name (optional)").fill(runName);
    await page.getByRole("button", { name: "Start run" }).click();
    const row = page.getByRole("row", { name: new RegExp(runName) });
    await expect(row).toBeVisible();
    await expect(row.getByText("done")).toBeVisible({ timeout: 45_000 });
  });

  test("manages access: groups and collections", async ({ page }) => {
    await signIn(page, "admin@acme.example");
    await page.getByRole("link", { name: "Workspace" }).click();
    await expect(page.getByText("People-Ops-Confidential")).toBeVisible();
    await expect(page.getByText("readable by: hr")).toBeVisible();
    await expect(page.getByText("hr@acme.example").first()).toBeVisible();
  });
});

test("an unknown person cannot get in", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Email").fill("nobody@example.com");
  await page.getByLabel("Password").fill("not-a-real-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toContainText("Wrong email or password");
});
