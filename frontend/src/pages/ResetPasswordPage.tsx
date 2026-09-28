import { FormEvent, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { auth } from "../api/client";
import AuthCard from "../components/AuthCard";

export default function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
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

  return (
    <AuthCard title="Reset password" subtitle="Choose a new password for your tenant account.">
      <form className="mt-6 space-y-4" onSubmit={onSubmit}>
        {error && (
          <div className="banner-error">{error}</div>
        )}
        {success && (
          <div className="banner-ok">{success}</div>
        )}
        <label className="block text-left">
          <span className="text-[12px] font-medium">New password</span>
          <span className="relative mt-1.5 block">
            <input
              className="input-field pr-16"
              type={showPassword ? "text" : "password"}
              placeholder="10+ characters"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <button
              className="absolute right-2 top-1/2 -translate-y-1/2 text-[11px] text-secondary"
              type="button"
              onClick={() => setShowPassword((v) => !v)}
            >
              {showPassword ? "Hide" : "Show"}
            </button>
          </span>
        </label>
        <label className="block text-left">
          <span className="text-[12px] font-medium">Confirm password</span>
          <input
            className="input-field mt-1.5"
            type={showPassword ? "text" : "password"}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
        </label>
          <button className="btn btn-primary h-10 w-full" type="submit" disabled={pending || Boolean(success)}>
          {pending ? "Saving…" : "Update password"}
        </button>
        <Link className="block w-full text-center text-[12px] text-on-variant underline" to="/">
          Back to sign in
        </Link>
      </form>
    </AuthCard>
  );
}
