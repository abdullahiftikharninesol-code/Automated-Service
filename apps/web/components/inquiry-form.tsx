"use client";

import { FormEvent, useEffect, useState } from "react";

import { publicFetch } from "@/lib/api";

interface PublicOrganization {
  id: string;
  name: string;
  industry: string;
  business_type: string;
}

export function InquiryForm({ organizationId }: { organizationId: string }) {
  const [organization, setOrganization] = useState<PublicOrganization | null>(null);
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    publicFetch<PublicOrganization>(`/public/organizations/${organizationId}`)
      .then(setOrganization)
      .catch((err: Error) => setError(err.message));
  }, [organizationId]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSending(true);
    setError("");
    const values = Object.fromEntries(
      [...new FormData(event.currentTarget).entries()].filter(([, value]) => value !== ""),
    );
    if (!values.email && !values.phone) {
      setError("Please provide an email address or phone number.");
      setSending(false);
      return;
    }
    try {
      await publicFetch(`/public/inbound/form/${organizationId}`, {
        method: "POST",
        body: JSON.stringify(values),
      });
      setSubmitted(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not submit your inquiry");
    } finally {
      setSending(false);
    }
  }

  const initials =
    organization?.name
      .split(/\s+/)
      .slice(0, 2)
      .map((word) => word[0])
      .join("")
      .toUpperCase() ?? "ML";

  return (
    <main className="min-h-screen bg-[#f1f5f3] py-8 md:py-14">
      <div className="mx-auto max-w-2xl px-4">
        <div className="mb-7 text-center">
          <div className="mx-auto mb-3 grid size-11 place-items-center rounded-xl bg-[#116149] font-black text-white">{initials}</div>
          <p className="text-sm font-bold text-[#116149]">{organization?.name ?? "Customer inquiry"}</p>
          <h1 className="mt-2 text-3xl font-extrabold tracking-tight">How can we help?</h1>
          <p className="mt-2 text-sm text-slate-500">Tell us what you need and our team will follow up shortly.</p>
        </div>
        {submitted ? (
          <div className="card p-10 text-center">
            <div className="mx-auto grid size-12 place-items-center rounded-full bg-emerald-100 text-xl text-emerald-700">✓</div>
            <h2 className="mt-4 text-xl font-extrabold">Request received</h2>
            <p className="mt-2 text-sm leading-6 text-slate-500">Thanks for contacting {organization?.name}. The team has received your inquiry and will be in touch.</p>
          </div>
        ) : (
          <form onSubmit={submit} className="card p-5 md:p-8">
            {error && <div className="mb-5 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}
            <div className="grid gap-5 md:grid-cols-2">
              <Field label="Name" name="name" required />
              <Field label="Email" name="email" type="email" />
              <Field label="Phone" name="phone" type="tel" />
              <Field label="Product / service" name="product_or_service" placeholder="What are you interested in?" />
              <Field label="Location" name="location" />
              <Field label="Preferred date" name="preferred_date" type="date" />
              <Field label="Preferred time" name="preferred_time" type="time" />
            </div>
            <label className="mt-5 block">
              <span className="label">Message</span>
              <textarea className="field" rows={5} minLength={2} required name="message" placeholder="Tell us how we can help…" />
            </label>
            <button className="btn btn-primary mt-6 w-full" disabled={sending}>
              {sending ? "Sending inquiry…" : "Send inquiry"}
            </button>
            <p className="mt-3 text-center text-xs text-slate-400">Provide at least an email address or phone number. Your information is shared only with {organization?.name ?? "this business"}.</p>
          </form>
        )}
      </div>
    </main>
  );
}

function Field({ label, name, type = "text", required = false, placeholder }: { label: string; name: string; type?: string; required?: boolean; placeholder?: string }) {
  return <label><span className="label">{label}</span><input className="field" name={name} type={type} required={required} placeholder={placeholder} /></label>;
}
