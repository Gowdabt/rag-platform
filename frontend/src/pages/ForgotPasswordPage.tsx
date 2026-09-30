import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { auth } from "../api/client";
import AuthCard from "../components/AuthCard";

export default function ForgotPasswordPage() {
  const [tenantSlug, setTenantSlug] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [pending, setPending] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSuccess("");
    const slug = tenantSlug.trim().toLowerCase();
    setPending(true);
    try {
      await auth.forgotPassword(slug, email.trim());
      setSuccess("If an account exists for that tenant and email, a password reset link has been sent.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send reset email");
    } finally {
      setPending(false);
    }
  }

  if (success) {
    return (
      <AuthCard title="Forgot password" subtitle="Check your email for the next step.">
        <div className="mt-6 space-y-4">
          <div className="banner-ok">{success}</div>
          <p className="text-[13px] text-on-variant">
            The message includes a single-use link that expires in 24 hours. If you do not see it, check spam or ask your Tenant Admin for help.
          </p>
          <Link className="block w-full text-center text-[12px] text-on-variant underline" to="/">
            Back to sign in
          </Link>
        </div>
      </AuthCard>
    );
  }

  return (
    <AuthCard title="Forgot password" subtitle="Enter your tenant ID and email. We’ll send a reset link if the account exists.">
      <form className="mt-6 space-y-4" onSubmit={onSubmit}>
        {error && <div className="banner-error">{error}</div>}
        <label className="block text-left">
          <span className="field-label">Tenant ID</span>
          <input
            className="input-field mt-1.5"
            placeholder="acme"
            value={tenantSlug}
            onChange={(e) => setTenantSlug(e.target.value)}
            autoComplete="organization"
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
            autoComplete="email"
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
