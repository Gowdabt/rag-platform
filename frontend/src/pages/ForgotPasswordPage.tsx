import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { auth } from "../api/client";
import AuthCard from "../components/AuthCard";

export default function ForgotPasswordPage() {
  const [tenantSlug, setTenantSlug] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [resetToken, setResetToken] = useState("");
  const [pending, setPending] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSuccess("");
    setResetToken("");
    setPending(true);
    try {
      const result = await auth.forgotPassword(tenantSlug.trim(), email.trim());
      setSuccess("If an account exists for that tenant and email, we sent a reset link.");
      const token = result?.reset_token || result?.token;
      if (typeof token === "string" && token) setResetToken(token);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send reset email");
    } finally {
      setPending(false);
    }
  }

  return (
    <AuthCard title="Forgot password" subtitle="Enter your tenant ID and email. We’ll send a reset link if the account exists.">
      <form className="mt-6 space-y-4" onSubmit={onSubmit}>
        {error && (
          <div className="banner-error">{error}</div>
        )}
        {success && (
          <div className="banner-ok">{success}</div>
        )}
        {resetToken && (
          <div className="rounded-lg bg-surface-low px-3 py-2.5 text-[12px]">
            Dev reset token:{" "}
            <code className="break-all font-mono text-[11px]">{resetToken}</code>
            <div className="mt-1">
              <Link className="text-secondary underline" to={`/reset?token=${encodeURIComponent(resetToken)}`}>
                Continue to reset
              </Link>
            </div>
          </div>
        )}
        <label className="block text-left">
          <span className="field-label">Tenant ID</span>
          <input
            className="input-field mt-1.5"
            placeholder="acme"
            value={tenantSlug}
            onChange={(e) => setTenantSlug(e.target.value)}
            required
          />
        </label>
        <label className="block text-left">
          <span className="field-label">Email</span>
          <input
            className="input-field mt-1.5"
            placeholder="you@example.com"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </label>
          <button className="btn btn-primary h-10 w-full" type="submit" disabled={pending}>
          {pending ? "Sending…" : "Send reset link"}
        </button>
        <Link className="block w-full text-center text-[12px] text-on-variant underline" to="/">
          Back to sign in
        </Link>
      </form>
    </AuthCard>
  );
}
