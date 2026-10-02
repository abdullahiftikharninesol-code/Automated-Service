"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { AuthField, AuthFrame } from "@/components/auth-frame";
import { apiFetch, saveToken } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setLoading(true); setError("");
    const values = Object.fromEntries(new FormData(event.currentTarget));
    try {
      const result = await apiFetch<{ access_token: string }>("/auth/login", { method: "POST", body: JSON.stringify(values) });
      saveToken(result.access_token); router.push("/");
    } catch (err) { setError(err instanceof Error ? err.message : "Could not sign in"); }
    finally { setLoading(false); }
  }

  return <AuthFrame title="Welcome back" subtitle="See which leads need your attention.">
    <form onSubmit={submit} className="space-y-4">
      {error && <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}
      <AuthField label="Email" name="email" type="email" defaultValue="owner@example.com" />
      <AuthField label="Password" name="password" type="password" defaultValue="DemoPassword123!" />
      <button disabled={loading} className="btn btn-primary w-full">{loading ? "Signing in…" : "Sign in"}</button>
    </form>
    <p className="mt-5 text-center text-sm text-slate-500">New here? <Link className="font-bold text-[#116149]" href="/register">Create an account</Link></p>
  </AuthFrame>;
}
