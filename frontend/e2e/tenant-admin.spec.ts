import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const API = process.env.PLAYWRIGHT_API_URL || "http://127.0.0.1:8000";

function requireSuperAdmin(): { email: string; password: string } {
  const email = (process.env.PLATFORM_SUPERADMIN_EMAIL || "").trim();
  const password = process.env.PLATFORM_SUPERADMIN_PASSWORD || "";
  if (!email || !password) {
    test.skip(true, "PLATFORM_SUPERADMIN_EMAIL and PLATFORM_SUPERADMIN_PASSWORD must be set");
  }
  return { email, password };
}

async function signIn(page: Page, email: string, password: string, slug = "") {
  await page.goto("/");
  await page.getByPlaceholder("Leave empty for Super Admin").fill(slug);
  await page.getByPlaceholder("you@example.com").fill(email);
  await page.getByPlaceholder("Your password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("super admin cannot open tenant document routes", async ({ page }) => {
  const { email, password } = requireSuperAdmin();
  await signIn(page, email, password);
  await expect(page.getByRole("link", { name: "Tenants", exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("link", { name: "Chat", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Documents", exact: true })).toHaveCount(0);
  await page.goto("/documents");
  await expect(page).toHaveURL(/\/platform/);
  await page.goto("/data");
  await expect(page).toHaveURL(/\/platform/);
});

test("tenant admin can open users roles data and chat", async ({ page, request }) => {
  const { slug, adminEmail, adminPassword } = await createTenantAdmin(request);
  await signIn(page, adminEmail, adminPassword, slug);
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("link", { name: "Users", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Roles", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Data", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Chat", exact: true })).toBeVisible();

  await page.getByRole("link", { name: "Users", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Users" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Invite user" })).toBeVisible();
  const usersHead = page.locator(".data-head.cols-6");
  await expect(usersHead).toContainText("Name");
  await expect(usersHead).toContainText("Email");
  await expect(usersHead).toContainText("Roles");
  await expect(usersHead).toContainText("Status");
  await expect(usersHead).toContainText("Last login");
  await expect(usersHead).toContainText("Actions");
  const headTracks = await usersHead.evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(" ").length);
  expect(headTracks).toBe(6);
  const userRow = page.locator('[data-testid="user-row"]').first();
  await expect(userRow).toBeVisible();
  const rowTracks = await userRow.evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(" ").length);
  expect(rowTracks).toBe(6);
  const headCols = await usersHead.evaluate((el) => getComputedStyle(el).gridTemplateColumns);
  const rowCols = await userRow.evaluate((el) => getComputedStyle(el).gridTemplateColumns);
  expect(rowCols).toBe(headCols);
  await expect(userRow.getByTestId("user-actions").getByRole("button", { name: "Edit" })).toBeVisible();
  await expect(userRow.getByTestId("user-actions").getByRole("button", { name: "Disable" })).toBeVisible();

  await page.getByRole("button", { name: "Invite user" }).click();
  await page.getByLabel("Name", { exact: true }).fill("Invited QA");
  await page.getByLabel("Email", { exact: true }).fill(`invited-qa-${Date.now()}@example.com`);
  await page.getByRole("button", { name: "Send invitation" }).click();
  await expect(page.getByText("Invitation sent")).toBeVisible();
  const invitedRow = page.locator('[data-testid="user-row"]').filter({ hasText: "Invited QA" });
  await expect(invitedRow.getByTestId("user-status")).toContainText(/invited/i);
  await expect(invitedRow.getByTestId("user-last-login")).toHaveText("—");
  await expect(invitedRow.getByTestId("user-copy-invite")).toBeVisible();
  await expect(invitedRow.getByTestId("user-actions").getByRole("button", { name: "Disable" })).toBeVisible();

  await page.getByRole("link", { name: "Roles", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Roles" })).toBeVisible();
  await expect(page.getByRole("list").getByText("Tenant Admin", { exact: true })).toBeVisible();
  await expect(page.getByText(/\d+ permissions/).first()).toBeVisible();

  await page.getByRole("link", { name: "Data", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Data" })).toBeVisible();
  await page.getByPlaceholder("New folder").fill("QA Folder");
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page.getByRole("button", { name: "QA Folder" })).toBeVisible();

  await page.getByRole("link", { name: "Chat", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Conversations" })).toBeVisible();
});

async function createTenantAdmin(request: APIRequestContext) {
  const { email, password } = requireSuperAdmin();
  const login = await request.post(`${API}/api/v1/auth/login`, { data: { email, password } });
  expect(login.ok(), await login.text()).toBeTruthy();
  const { access_token } = await login.json();
  const stamp = Date.now().toString(36);
  const slug = `qa-${stamp}`;
  const adminEmail = `qa-admin-${stamp}@example.com`;
  const adminPassword = "supersecret1";
  const created = await request.post(`${API}/api/v1/platform/tenants`, {
    headers: { Authorization: `Bearer ${access_token}` },
    data: {
      name: `QA ${stamp}`,
      slug,
      admin_name: "QA Admin",
      admin_email: adminEmail,
      admin_password: adminPassword,
    },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const body = await created.json();
  expect(body.password_set).toBeTruthy();
  return { slug, adminEmail, adminPassword };
}
