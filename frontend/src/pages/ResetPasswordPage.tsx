import { FormEvent, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { auth } from "../api/client";
import AuthCard from "../components/AuthCard";

export default function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const slug = (params.get("slug") || "").trim().toLowerCase();
  const signInTo = slug ? `/?slug=${encodeURIComponent(slug)}` : "/";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [pending, setPending] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSuccess("");
    if (!token) {
      setError("This reset link is missing a token.");
      return;
    }
    if (password.length < 10) {
      setError("Password must be at least 10 characters.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setPending(true);
    try {
      await auth.resetPassword(token, password);
      setSuccess("Password updated. You can sign in now.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reset failed");
    } finally {
      setPending(false);
    }
  }

  if (!token) {
    return (
      <AuthCard title="Reset password" subtitle="Choose a new password for your tenant account.">
        <div className="mt-6 space-y-4">
          <div className="banner-error">This reset link is missing a token.</div>
          <Link className="btn btn-primary flex h-10 w-full items-center justify-center" to="/forgot-password">
            Request a new reset link
          </Link>
        </div>
      </AuthCard>
    );
  }

  if (success) {
    return (
      <AuthCard title="Reset password" subtitle="Choose a new password for your tenant account.">
        <div className="mt-6 space-y-4">
          <div className="banner-ok">{success}</div>
          <Link data-testid="reset-sign-in" className="btn btn-primary flex h-10 w-full items-center justify-center" to={signInTo}>
            Sign in
          </Link>
        </div>
      </AuthCard>
    );
  }

  return (
    <AuthCard title="Reset password" subtitle="Choose a new password for your tenant account.">
      <form className="mt-6 space-y-4" data-testid="reset-password-form" onSubmit={onSubmit}>
        {error && <div className="banner-error">{error}</div>}
        {slug ? <p className="text-left text-[12px] text-on-variant">Tenant ID: {slug}</p> : null}
        <label className="block text-left">
          <span className="text-[12px] font-medium">New password</span>
          <span className="relative mt-1.5 block">
            <input
              data-testid="new-password"
              className="input-field pr-16"
              type={showPassword ? "text" : "password"}
              placeholder="10+ characters"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={10}
              required
              autoComplete="new-password"
            />
            <button
              className="absolute right-2 top-1/2 -translate-y-1/2 text-[11px] text-secondary"
              type="button"
              onClick={() => setShowPassword((v) => !v)}
            >
              {showPassword ? "Hide" : "Show"}
            </button>
          </span>
          <span className="mt-1 block text-[12px] text-on-variant">Minimum 10 characters</span>
        </label>
        <label className="block text-left">
          <span className="text-[12px] font-medium">Confirm password</span>
          <input
            data-testid="confirm-password"
            className="input-field mt-1.5"
            type={showPassword ? "text" : "password"}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            minLength={10}
            required
            autoComplete="new-password"
          />
        </label>
        <button className="btn btn-primary h-10 w-full" type="submit" disabled={pending}>
          {pending ? "Saving…" : "Update password"}
        </button>
        <Link className="block w-full text-center text-[12px] text-on-variant underline" to={signInTo}>
          Back to sign in
        </Link>
      </form>
    </AuthCard>
  );
}
