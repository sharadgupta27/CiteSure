import { expect, type Page } from "@playwright/test";

export const PASSWORD = process.env.SEED_PASSWORD ?? "citesure-demo";

export async function signIn(page: Page, email: string): Promise<void> {
  await page.goto("/");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
}

export async function ask(page: Page, question: string): Promise<void> {
  await page.getByLabel("Your question").fill(question);
  await page.getByRole("button", { name: "Ask", exact: true }).click();
}
