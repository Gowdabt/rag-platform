import { expect, test, type Page } from "@playwright/test";

function requireSuperAdmin(): { email: string; password: string } {
  const email = (process.env.PLATFORM_SUPERADMIN_EMAIL || "").trim();
  const password = process.env.PLATFORM_SUPERADMIN_PASSWORD || "";
  if (!email || !password) {
    test.skip(true, "PLATFORM_SUPERADMIN_EMAIL and PLATFORM_SUPERADMIN_PASSWORD must be set");
  }
  return { email, password };
}

async function signInAsSuperAdmin(page: Page, email: string, password: string) {
  await page.goto("/");
  await page.getByPlaceholder("Leave empty for Super Admin").fill("");
  await page.getByPlaceholder("you@example.com").fill(email);
  await page.getByPlaceholder("Your password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("link", { name: "Tenants", exact: true })).toBeVisible({ timeout: 20_000 });
}

test("super admin creates a tenant and sees invite details in columns", async ({ page }) => {
  const { email, password } = requireSuperAdmin();
  await signInAsSuperAdmin(page, email, password);
  await page.getByRole("link", { name: "Tenants", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Tenants" })).toBeVisible();

  const stamp = Date.now().toString(36);
  const company = `E2E ${stamp}`;
  const slug = `e2e-${stamp}`;
  const adminEmail = `e2e-${stamp}@example.com`;

  await page.getByRole("button", { name: "+ Create Tenant" }).click();
  await expect(page.getByText("does not create a default password")).toBeVisible();
  await page.getByLabel("Company name").fill(company);
  await page.getByLabel("Tenant ID (slug)").fill(slug);
  await page.getByLabel("Admin name").fill("E2E Admin");
  await page.getByLabel("Admin email").fill(adminEmail);
  await page.getByRole("button", { name: "Create", exact: true }).click();

  const panel = page.getByTestId("tenant-invite-panel");
  await expect(panel).toBeVisible();
  await expect(panel.getByTestId("invite-slug")).toContainText(slug);
  await expect(panel.getByTestId("invite-email")).toContainText(adminEmail);
  await expect(panel.getByTestId("invite-url")).toContainText("/invite?token=");
  await expect(panel).toContainText("No default password is created");
  await expect(panel).toContainText("starter accounts");
  await expect(panel.getByTestId("seeded-user-tenant-admin")).toContainText(adminEmail);
  await expect(panel.getByTestId("seeded-user-member")).toContainText(`member@${slug}.demo`);
  await expect(panel.getByTestId("seeded-user-viewer")).toContainText(`viewer@${slug}.demo`);
  await expect(panel.getByTestId("invite-url-member")).toContainText("/invite?token=");
  await expect(panel.getByTestId("invite-url-viewer")).toContainText("/invite?token=");

  const row = page.locator(`[data-testid="tenant-row"][data-slug="${slug}"]`);
  await expect(row.getByTestId("tenant-company")).toHaveText(company);
  await expect(row.getByTestId("tenant-slug")).toHaveText(slug);
  await expect(row.getByTestId("tenant-admin")).toHaveText(adminEmail);
  await expect(row.getByTestId("tenant-status")).toContainText(/active/i);
  await expect(row.getByTestId("tenant-actions")).toContainText("View");
  await expect(row.getByTestId("tenant-company")).not.toHaveText(new RegExp(`${company}${slug}`));
});
