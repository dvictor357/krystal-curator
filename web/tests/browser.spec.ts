import { test, expect } from "@playwright/test";
for (const width of [1440, 768, 390])
  test(`landing and demo at ${width}px`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "See both sides of the pool." }),
    ).toBeVisible();
    expect(await page.evaluate(() => window.innerWidth)).toBe(width);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `test-results/landing-${width}.png`,
      fullPage: true,
    });
    await page.goto("/demo");
    await expect(
      page.getByRole("heading", { name: "Pool screener." }),
    ).toBeVisible();
    await expect(page.locator(".pool-table tbody tr").first()).toBeVisible();
    await expect(page.locator(".pair-mark").first()).toBeVisible();
    await expect(page.locator(".pair-slash").first()).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `test-results/demo-${width}.png`,
      fullPage: true,
    });
    await page
      .getByRole("button", { name: /Details for/ })
      .first()
      .click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page
      .getByRole("button", { name: "Save to watchlist", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Saved to watchlist", exact: true }),
    ).toBeVisible();
    await page.screenshot({
      path: `test-results/detail-${width}.png`,
      fullPage: true,
    });
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).not.toBeVisible();
    await page
      .getByRole("button", { name: /Watchlist/ })
      .first()
      .click();
    await expect(page.locator(".pool-table tbody tr")).toHaveCount(1);
    await page.getByLabel("Search pools").fill("no-such-pool");
    await expect(
      page.getByText("No saved pairs match this view."),
    ).toBeVisible();
    await page.getByRole("button", { name: "Settings", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Workspace defaults." }),
    ).toBeVisible();
    await page.screenshot({
      path: `test-results/settings-${width}.png`,
      fullPage: true,
    });
    expect(errors).toEqual([]);
  });
test("account registration, persistence, logout, protected route and CSRF", async ({
  page,
  request,
}) => {
  test.skip(
    process.env.CURATOR_BROWSER_ACCOUNTS !== "1",
    "Requires migrated disposable PostgreSQL and Python API",
  );
  const email = `browser-${Date.now()}@example.com`;
  await page.goto("/login");
  await page
    .getByRole("button", { name: "New here? Create an account" })
    .click();
  await page.getByLabel("Email address").fill(email);
  await page
    .getByLabel("Password", { exact: true })
    .fill("browser-check-passphrase-42");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await page.waitForURL("/app");
  await page.goto("/app/settings");
  await expect(
    page.getByRole("heading", { name: "Workspace defaults." }),
  ).toBeVisible();
  await page.getByLabel("Simulation size (USD)").fill("25000");
  await page.getByRole("button", { name: "Save preferences" }).click();
  await expect(page.getByText("Preferences saved.")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Simulation size (USD)")).toHaveValue("25000");
  expect(
    (
      await request.post("/api/account", {
        headers: { Origin: "https://untrusted.example" },
        data: { action: "settings" },
      })
    ).status(),
  ).toBe(403);
  await page.getByRole("button", { name: /Sign out/ }).click();
  await page.waitForURL("/login");
  await page.goto("/app/settings");
  await page.waitForURL("/login");
});
