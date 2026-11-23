import { expect, test } from "@playwright/test";
import { ask, signIn } from "./helpers";

test("download original: the browser saves the file through a short-lived signed link", async ({ page }) => {
  await signIn(page, "employee@acme.example");
  await ask(page, "How many weeks of paid parental leave do primary caregivers get?");
  await expect(page.getByText("Every citation was checked against its source.")).toBeVisible();
  await page.getByRole("button", { name: "Open source 1" }).first().click();

  const linkRequest = page.waitForRequest((r) => r.method() === "POST" && r.url().endsWith("/download-link"));
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download original" }).click();

  expect((await linkRequest).url()).toMatch(/\/api\/v1\/documents\/[0-9a-f-]+\/download-link$/);
  const file = await download;
  expect(file.url()).toMatch(/\/api\/v1\/files\/[\w-]+\.[\w-]+\.[\w-]+$/); // the signed token, not the login token
  expect(file.suggestedFilename()).toMatch(/\.(md|pdf|docx|html)$/);
  expect(await file.failure()).toBeNull();
});
