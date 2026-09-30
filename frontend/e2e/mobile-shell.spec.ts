import { devices, expect, test } from "@playwright/test";

function requireSuperAdmin(): { email: string; password: string } {
  const email = (process.env.PLATFORM_SUPERADMIN_EMAIL || "").trim();
  const password = process.env.PLATFORM_SUPERADMIN_PASSWORD || "";
  if (!email || !password) {
    test.skip(true, "PLATFORM_SUPERADMIN_EMAIL and PLATFORM_SUPERADMIN_PASSWORD must be set");
  }
  return { email, password };
}

test.use({ ...devices["Pixel 5"] });

test("mobile shell keeps nav and tenant table usable", async ({ page }) => {
  const { email, password } = requireSuperAdmin();
  await page.goto("/");
  await page.getByPlaceholder("Leave empty for Super Admin").fill("");
  await page.getByPlaceholder("you@example.com").fill(email);
  await page.getByPlaceholder("Your password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("link", { name: "Tenants", exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();
  await page.getByRole("link", { name: "Tenants", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Tenants" })).toBeVisible();
  await expect(page.getByRole("button", { name: "+ Create Tenant" })).toBeVisible();
  const header = page.locator("header");
  await expect(header).toBeVisible();
});
