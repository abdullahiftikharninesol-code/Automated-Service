"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { PageHeading } from "@/components/page-heading";
import { apiFetch } from "@/lib/api";
import type { Lead } from "@/lib/types";

export default function NewLeadPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true); setError("");
    const form = new FormData(event.currentTarget);
    const payload = Object.fromEntries([...form.entries()].filter(([, value]) => value !== ""));
    try {
      const lead = await apiFetch<Lead>("/leads", { method: "POST", body: JSON.stringify(payload) });
      router.push(`/leads/${lead.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save lead");
    } finally { setSaving(false); }
  }

  return (
    <>
      <PageHeading title="Add a lead" description="Capture a phone call, referral, walk-in, or other inquiry." />
      <form onSubmit={submit} className="card max-w-3xl p-5 md:p-7">
        {error && <div className="mb-5 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}
        <div className="grid gap-5 md:grid-cols-2">
          <Field label="Customer name" name="customer_name" required />
          <Field label="Phone" name="customer_phone" type="tel" />
          <Field label="Email" name="customer_email" type="email" />
          <label><span className="label">Source</span><select className="field" name="source" defaultValue="PHONE"><option>PHONE</option><option>MANUAL</option><option>EMAIL</option></select></label>
          <Field label="Product / service" name="service_type" placeholder="Leave blank for AI extraction" />
          <Field label="Location / ZIP" name="location" />
        </div>
        <label className="mt-5 block"><span className="label">Customer message / problem</span><textarea required minLength={2} rows={5} className="field" name="message" placeholder="Describe what the customer needs…" /></label>
        <p className="mt-3 text-xs text-slate-500">The AI assistant will classify urgency, summarize the request, and schedule follow-ups. Provide a phone number or email.</p>
        <button disabled={saving} className="btn btn-primary mt-6" type="submit">{saving ? "Processing…" : "Create lead"}</button>
      </form>
    </>
  );
}

function Field({ label, name, type = "text", required = false, placeholder }: { label: string; name: string; type?: string; required?: boolean; placeholder?: string }) {
  return <label><span className="label">{label}</span><input className="field" name={name} type={type} required={required} placeholder={placeholder} /></label>;
}
