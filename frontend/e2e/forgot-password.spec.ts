import { expect, test, type APIRequestContext } from "@playwright/test";

const API = process.env.PLAYWRIGHT_API_URL || "http://127.0.0.1:8000";

function requireSuperAdmin(): { email: string; password: string } {
  const email = (process.env.PLATFORM_SUPERADMIN_EMAIL || "").trim();
  const password = process.env.PLATFORM_SUPERADMIN_PASSWORD || "";
  if (!email || !password) {
    test.skip(true, "PLATFORM_SUPERADMIN_EMAIL and PLATFORM_SUPERADMIN_PASSWORD must be set");
  }
  return { email, password };
}

async function createInvitedTenant(request: APIRequestContext) {
  const { email, password } = requireSuperAdmin();
  const login = await request.post(`${API}/api/v1/auth/login`, {
    data: { email, password },
  });
  expect(login.ok(), await login.text()).toBeTruthy();
  const { access_token } = await login.json();
  const stamp = Date.now().toString(36);
  const slug = `pwreset-${stamp}`;
  const adminEmail = `pwreset-${stamp}@example.com`;
  const created = await request.post(`${API}/api/v1/platform/tenants`, {
    headers: { Authorization: `Bearer ${access_token}` },
    data: {
      name: `PW Reset ${stamp}`,
      slug,
      admin_name: "Reset User",
      admin_email: adminEmail,
    },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const body = await created.json();
  expect(body.password_set).toBeFalsy();
  expect(body.reset_token).toBeFalsy();
  return { slug, adminEmail };
}

test("forgot password confirms email send and does not expose a reset token", async ({ page, request }) => {
  const { slug, adminEmail } = await createInvitedTenant(request);
  const mixedSlug = slug.replace(/^./, (c) => c.toUpperCase());

  await page.goto("/forgot-password");
  await page.getByPlaceholder("acme").fill(mixedSlug);
  await page.getByPlaceholder("you@example.com").fill(adminEmail);
  await page.getByRole("button", { name: "Send reset link" }).click();

  await expect(page.getByText("If an account exists")).toBeVisible();
  await expect(page.getByPlaceholder("acme")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Send reset link" })).toHaveCount(0);
  await expect(page.getByTestId("continue-to-reset")).toHaveCount(0);
  await expect(page.getByText(/token=/i)).toHaveCount(0);
});
