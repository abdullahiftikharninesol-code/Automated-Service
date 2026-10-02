"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { AuthField, AuthFrame } from "@/components/auth-frame";
import { apiFetch, saveToken } from "@/lib/api";

export default function RegisterPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setLoading(true); setError("");
    const values = Object.fromEntries(new FormData(event.currentTarget));
    try {
      const result = await apiFetch<{ access_token: string }>("/auth/register", { method: "POST", body: JSON.stringify(values) });
      saveToken(result.access_token); router.push("/");
    } catch (err) { setError(err instanceof Error ? err.message : "Could not create account"); }
    finally { setLoading(false); }
  }
  return <AuthFrame title="Create your workspace" subtitle="Start rescuing missed HVAC opportunities.">
    <form onSubmit={submit} className="space-y-4">
      {error && <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}
      <AuthField label="Company name" name="organization_name" /><AuthField label="Your name" name="name" />
      <AuthField label="Email" name="email" type="email" /><AuthField label="Password (8+ characters)" name="password" type="password" />
      <input type="hidden" name="timezone" value="America/New_York" />
      <button disabled={loading} className="btn btn-primary w-full">{loading ? "Creating…" : "Create account"}</button>
    </form>
    <p className="mt-5 text-center text-sm text-slate-500">Already have an account? <Link className="font-bold text-[#116149]" href="/login">Sign in</Link></p>
  </AuthFrame>;
}
