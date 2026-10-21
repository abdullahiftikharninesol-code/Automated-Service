"use client";

import { FormEvent, useEffect, useState } from "react";

import { PageHeading } from "@/components/page-heading";
import { QualificationSetup } from "@/components/qualification-setup";
import { apiFetch } from "@/lib/api";
import { label } from "@/lib/format";
import type {
  BusinessType,
  Organization,
  OrganizationIntegration,
  User,
} from "@/lib/types";

const businessTypes: BusinessType[] = [
  "GENERAL",
  "HVAC",
  "ECOMMERCE",
  "CLOTHING",
  "DENTAL",
  "REAL_ESTATE",
  "AGENCY",
  "HOME_SERVICES",
];

export default function SettingsPage() {
  const [organization, setOrganization] = useState<Organization | null>(null);
  const [integration, setIntegration] = useState<OrganizationIntegration | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    apiFetch<User>("/auth/me")
      .then(async (user) => {
        const [organizationData, integrationData] = await Promise.all([
          apiFetch<Organization>(`/organizations/${user.organization_id}`),
          apiFetch<OrganizationIntegration>(
            `/organizations/${user.organization_id}/integration-info`,
          ),
        ]);
        setOrganization(organizationData);
        setIntegration(integrationData);
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("");
    setError("");
    if (!organization) return;
    const values = Object.fromEntries(new FormData(event.currentTarget));
    const payload = {
      ...values,
      duplicate_window_minutes: Number(values.duplicate_window_minutes),
      followup_new_lead_minutes: Number(values.followup_new_lead_minutes),
      followup_second_reminder_hours: Number(values.followup_second_reminder_hours),
      followup_contacted_hours: Number(values.followup_contacted_hours),
      followup_final_days: Number(values.followup_final_days),
    };
    try {
      setOrganization(
        await apiFetch<Organization>(`/organizations/${organization.id}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        }),
      );
      setMessage("Settings saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save settings");
    }
  }

  return (
    <>
      <PageHeading
        title="Settings"
        description="Organization details, inbound integrations, and lead reminder cadence."
      />
      {error && <div className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}
      {organization && (
        <form onSubmit={save} className="space-y-5">
          <section className="card max-w-3xl p-5 md:p-7">
            <h2 className="mb-5 font-extrabold">Organization</h2>
            <div className="grid gap-5 md:grid-cols-2">
              <Field label="Company name" name="name" defaultValue={organization.name} />
              <label>
                <span className="label">Business type</span>
                <select className="field" name="business_type" defaultValue={organization.business_type}>
                  {businessTypes.map((value) => <option key={value} value={value}>{label(value)}</option>)}
                </select>
              </label>
              <Field label="Industry label" name="industry" defaultValue={organization.industry} />
              <Field label="Timezone" name="timezone" defaultValue={organization.timezone} />
              <Field label="Duplicate window (minutes)" name="duplicate_window_minutes" type="number" defaultValue={organization.duplicate_window_minutes} />
            </div>
          </section>
          {integration && <IntegrationDetails integration={integration} />}
          <section className="card max-w-3xl p-5 md:p-7">
            <h2 className="mb-1 font-extrabold">Follow-up schedule</h2>
            <p className="mb-5 text-sm text-slate-500">Changes apply to newly scheduled reminders.</p>
            <div className="grid gap-5 md:grid-cols-2">
              <Field label="New lead attention (minutes)" name="followup_new_lead_minutes" type="number" defaultValue={organization.followup_new_lead_minutes} />
              <Field label="Second reminder (hours)" name="followup_second_reminder_hours" type="number" defaultValue={organization.followup_second_reminder_hours} />
              <Field label="Contacted follow-up (hours)" name="followup_contacted_hours" type="number" defaultValue={organization.followup_contacted_hours} />
              <Field label="Final reminder (days)" name="followup_final_days" type="number" defaultValue={organization.followup_final_days} />
            </div>
          </section>
          <div className="flex items-center gap-3">
            <button className="btn btn-primary">Save settings</button>
            {message && <span className="text-sm font-semibold text-emerald-700">{message}</span>}
          </div>
        </form>
      )}
      <div className="mt-8 space-y-5">
        <QualificationSetup />
      </div>
    </>
  );
}

export function IntegrationDetails({ integration }: { integration: OrganizationIntegration }) {
  return (
    <section className="card max-w-3xl p-5 md:p-7">
      <h2 className="mb-1 font-extrabold">Inbound integrations</h2>
      <p className="mb-5 text-sm text-slate-500">Use the webhook for site integrations or paste the iframe into any page.</p>
      <div className="space-y-4">
        <IntegrationValue label="Inbound webhook URL" value={integration.inbound_webhook_url} />
        <IntegrationValue label="Embed form URL" value={integration.embed_form_url} />
        <IntegrationValue label="Embed code" value={integration.embed_code} />
        <div>
          <span className="label">Email provider status</span>
          <p className={`text-sm font-bold ${integration.email_configured ? "text-emerald-700" : "text-amber-700"}`}>
            {label(integration.email_provider)} · {integration.email_configured ? "Configured" : "Needs configuration"}
          </p>
        </div>
        <div className="border-t border-slate-200 pt-4">
          <span className="label">WhatsApp Business Cloud API</span>
          <p className={`text-sm font-bold ${integration.whatsapp_configured ? "text-emerald-700" : "text-slate-500"}`}>
            {integration.whatsapp_configured ? "Active · Connected" : "Not connected"}
            {integration.whatsapp_display_phone_number ? ` (${integration.whatsapp_display_phone_number})` : ""}
          </p>
          {integration.whatsapp_webhook_url && (
            <div className="mt-3">
              <IntegrationValue label="Meta Webhook Callback URL" value={integration.whatsapp_webhook_url} />
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function IntegrationValue({ label: title, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="label">{title}</span>
      <div className="flex items-start gap-2">
        <code className="min-w-0 flex-1 overflow-x-auto rounded-lg bg-slate-100 p-3 text-xs">{value}</code>
        <button type="button" className="btn btn-secondary text-xs" onClick={() => navigator.clipboard.writeText(value)}>Copy</button>
      </div>
    </div>
  );
}

function Field({ label: title, name, defaultValue, type = "text" }: { label: string; name: string; defaultValue: string | number; type?: string }) {
  return <label><span className="label">{title}</span><input required min={type === "number" ? 1 : undefined} className="field" name={name} type={type} defaultValue={defaultValue} /></label>;
}
