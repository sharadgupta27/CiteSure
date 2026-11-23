import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { PASSWORD } from "./helpers";

// Not a test: records the 2-minute product demo video (docs/media/citesure-demo.webm).
//   DEMO_VIDEO=1 BASE_URL=http://localhost:7860 npx playwright test demo-video
// Run it against a freshly seeded demo stack (the deploy/demo image or `docker compose up` + seed).
test.skip(!process.env.DEMO_VIDEO, "set DEMO_VIDEO=1 to record the demo video");

const SIZE = { width: 1280, height: 720 };
const OUT = path.resolve(__dirname, "../../docs/media");
test.use({ viewport: SIZE, video: { mode: "on", size: SIZE }, actionTimeout: 20_000 });

// A caption bar at the bottom of the screen, so the video explains itself without sound.
async function caption(page: Page, text: string, holdMs = 2600): Promise<void> {
  await page.evaluate((t) => {
    let bar = document.getElementById("demo-caption");
    if (!bar) {
      bar = document.createElement("div");
      bar.id = "demo-caption";
      Object.assign(bar.style, {
        position: "fixed", left: "50%", bottom: "28px", transform: "translateX(-50%)", zIndex: "2147483647",
        maxWidth: "80%", padding: "12px 22px", borderRadius: "12px", background: "rgba(15,23,42,0.92)",
        color: "#fff", font: "600 20px/1.35 system-ui, sans-serif", textAlign: "center", pointerEvents: "none",
        boxShadow: "0 8px 30px rgba(0,0,0,0.35)",
      });
      document.body.appendChild(bar);
    }
    bar.textContent = t;
  }, text);
  await page.waitForTimeout(holdMs);
}

async function login(page: Page, email: string): Promise<void> {
  await page.goto("/");
  await page.getByLabel("Email").pressSequentially(email, { delay: 35 });
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
}

async function askSlowly(page: Page, question: string): Promise<void> {
  await page.getByLabel("Your question").pressSequentially(question, { delay: 28 });
  await page.getByRole("button", { name: "Ask", exact: true }).click();
}

test("record the demo video", async ({ page }) => {
  test.setTimeout(300_000);

  await page.goto("/");
  await caption(page, "CiteSure: ask your company's documents, get answers you can verify", 3500);

  // 1. Employee: a cited, verified answer and the highlighted source.
  await caption(page, "An employee signs in", 1200);
  await login(page, "employee@acme.example");
  await askSlowly(page, "How many weeks of paid parental leave do primary caregivers get?");
  await caption(page, "Retrieve → generate claims → verify every citation…", 1200);
  await expect(page.getByText("Every citation was checked against its source.")).toBeVisible();
  await caption(page, "Every sentence carries a numbered citation, checked against its source", 3500);
  await page.getByRole("button", { name: "Open source 1" }).first().click();
  await expect(page.getByRole("dialog", { name: "Source" }).locator("mark")).toBeVisible();
  await caption(page, "One click opens the source with the quoted words highlighted", 3800);
  await page.keyboard.press("Escape");

  // 2. The same employee asks about a restricted document.
  await askSlowly(page, "What is the maximum severance in weeks?");
  await expect(page.getByTestId("refusal")).toBeVisible();
  await caption(page, "Severance is in an HR-only collection: the employee is refused, nothing leaks", 4200);

  // 3. HR gets the confidential answer.
  await page.getByRole("button", { name: "Sign out" }).click();
  await caption(page, "Now an HR member asks a severance question", 1500);
  await login(page, "hr@acme.example");
  await askSlowly(page, "How is severance pay calculated?");
  await expect(page.getByText(/Severance is 2 weeks of base pay/).first()).toBeVisible();
  await caption(page, "HR is in the right group, so the answer comes from the confidential document", 4200);

  // 4. Admin: documents, access rules, quality, audit.
  await page.getByRole("button", { name: "Sign out" }).click();
  await caption(page, "The admin owns documents, access rules and answer quality", 1500);
  await login(page, "admin@acme.example");
  await page.getByRole("link", { name: "Documents" }).click();
  await expect(page.getByText("Parental Leave Policy")).toBeVisible();
  await caption(page, "Documents are parsed, chunked and embedded in the background", 3000);

  await page.getByRole("link", { name: "Workspace" }).click();
  await expect(page.getByText("readable by: hr")).toBeVisible();
  await caption(page, "Access control is enforced inside retrieval, per collection and group", 3200);

  await page.getByRole("link", { name: "Quality" }).click();
  await page.getByLabel("Name (optional)").fill("demo: hybrid + rerank");
  await page.getByRole("button", { name: "Start run" }).click();
  await caption(page, "Quality: run the 40-question golden set against the live pipeline", 1500);
  await expect(page.getByRole("row").filter({ hasText: "demo: hybrid + rerank" }).getByText("done")).toBeVisible({ timeout: 90_000 });
  await caption(page, "Recall, MRR, citation precision and refusal accuracy for every run", 3500);

  await page.getByRole("link", { name: "Audit log" }).click();
  await expect(page.getByRole("heading", { name: "Audit log" })).toBeVisible();
  await page.getByRole("button", { name: "Verify chain" }).click();
  await expect(page.getByText(/chain is intact|intact|verified/i).first()).toBeVisible();
  await caption(page, "A tamper-evident, hash-chained audit log of who did what", 3500);

  await caption(page, "CiteSure: cited, verified, permission-aware. Source: github.com/sharadgupta27/CiteSure", 4000);

  const video = page.video();
  await page.close();
  if (video) {
    fs.mkdirSync(OUT, { recursive: true });
    await video.saveAs(path.join(OUT, "citesure-demo.webm"));
  }
});
