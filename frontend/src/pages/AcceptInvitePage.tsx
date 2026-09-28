import { FormEvent, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { auth } from "../api/client";
import AuthCard from "../components/AuthCard";

export default function AcceptInvitePage() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const navigate = useNavigate();
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
      setError("This invite link is missing a token.");
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
      const result = await auth.acceptInvite(token, password);
      if (result?.access_token) {
        localStorage.setItem("access_token", result.access_token);
        if (result.refresh_token) localStorage.setItem("refresh_token", result.refresh_token);
        navigate("/");
        window.location.reload();
        return;
      }
      setSuccess("Invitation accepted. You can sign in now.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not accept invite");
    } finally {
      setPending(false);
    }
  }

  return (
    <AuthCard title="Accept invite" subtitle="Set a password to join your tenant.">
      <form className="mt-6 space-y-4" onSubmit={onSubmit}>
        {error && (
          <div className="banner-error">{error}</div>
        )}
        {success && (
          <div className="banner-ok">{success}</div>
        )}
        <label className="block text-left">
          <span className="text-[12px] font-medium">Password</span>
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
          <span className="mt-1 block text-[12px] text-on-variant">Minimum 10 characters</span>
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
          {pending ? "Saving…" : "Join tenant"}
        </button>
        <Link className="block w-full text-center text-[12px] text-on-variant underline" to="/">
          Already have an account? Sign in
        </Link>
      </form>
    </AuthCard>
  );
}
