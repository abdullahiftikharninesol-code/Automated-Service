"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { LeadActions } from "@/components/lead-actions";
import { PageHeading } from "@/components/page-heading";
import { SourceBadge, StatusBadge, UrgencyBadge } from "@/components/status-badge";
import { apiFetch } from "@/lib/api";
import { formatDate, label } from "@/lib/format";
import type { InboundMessage, Lead, LeadEvent } from "@/lib/types";

export default function LeadDetailsPage() {
  const { id } = useParams<{ id: string }>();
  const [lead, setLead] = useState<Lead | null>(null);
  const [events, setEvents] = useState<LeadEvent[]>([]);
  const [messages, setMessages] = useState<InboundMessage[]>([]);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState("");
  const [drafting, setDrafting] = useState(false);

  const load = useCallback(() => {
    Promise.all([
      apiFetch<Lead>(`/leads/${id}`),
      apiFetch<LeadEvent[]>(`/leads/${id}/events`),
      apiFetch<InboundMessage[]>(`/leads/${id}/messages`),
    ])
      .then(([leadData, eventData, messageData]) => { setLead(leadData); setEvents(eventData); setMessages(messageData); })
      .catch((err: Error) => setError(err.message));
  }, [id]);
  useEffect(load, [load]);

  async function addNote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const note = new FormData(form).get("note");
    await apiFetch(`/leads/${id}/notes`, { method: "POST", body: JSON.stringify({ note }) });
    form.reset(); load();
  }

  async function generateDraft() {
    setDrafting(true);
    try {
      const response = await apiFetch<{ message: string }>(`/leads/${id}/generate-followup`, { method: "POST" });
      setDraft(response.message); load();
    } finally { setDrafting(false); }
  }

  if (error) return <div className="rounded-lg bg-red-50 p-4 text-red-700">{error}</div>;
  if (!lead) return <div className="text-sm text-slate-500">Loading lead…</div>;

  const preferred = [lead.preferred_date ?? lead.preferred_date_text, lead.preferred_time ?? lead.preferred_time_text].filter(Boolean).join(" · ") || "Not provided";
  return (
    <>
      <PageHeading
        title={lead.customer_name}
        description={`Received ${formatDate(lead.created_at)} via ${label(lead.source)}`}
        action={<div className="flex flex-wrap gap-2"><SourceBadge source={lead.source} /><StatusBadge status={lead.status} /><UrgencyBadge urgency={lead.urgency} /></div>}
      />
      <div className="mb-6"><LeadActions lead={lead} onUpdate={(updated) => { setLead(updated); load(); }} /></div>
      <div className="grid gap-5 lg:grid-cols-[1.35fr_.8fr]">
        <div className="space-y-5">
          <Section title="Customer details">
            <div className="grid gap-4 text-sm sm:grid-cols-2">
              <Detail label="Phone" value={lead.customer_phone} link={lead.customer_phone ? `tel:${lead.customer_phone}` : undefined} />
              <Detail label="Email" value={lead.customer_email} link={lead.customer_email ? `mailto:${lead.customer_email}` : undefined} />
              <Detail label="Location" value={lead.location} /><Detail label="Preferred" value={preferred} />
              {lead.customer_id && <Detail label="Customer ID" value={lead.customer_id.slice(0, 8) + "…"} />}
              {lead.primary_conversation_id && <Detail label="Conversation" value={lead.primary_conversation_id.slice(0, 8) + "…"} />}
            </div>
          </Section>
          <Section title="Customer messages">
            <div className="space-y-4">
              {messages.map((item) => <article key={item.id} className="rounded-lg border border-slate-200 bg-slate-50 p-4"><div className="mb-2 flex flex-wrap items-center justify-between gap-2"><SourceBadge source={item.channel} /><time className="text-xs text-slate-500">{formatDate(item.received_at)}</time></div><p className="whitespace-pre-wrap text-sm leading-6 text-slate-700">{item.message_text}</p></article>)}
              {!messages.length && <p className="whitespace-pre-wrap text-sm leading-6 text-slate-700">{lead.message}</p>}
            </div>
          </Section>
          <Section title="AI analysis">
            <div className="grid gap-4 text-sm sm:grid-cols-2"><Detail label="Intent" value={lead.intent ? label(lead.intent) : null} /><Detail label="Category / service" value={lead.category_or_service} /><Detail label="Product" value={lead.product_name} /><Detail label="Variant" value={lead.product_variant} /><Detail label="Quantity" value={lead.quantity?.toString()} /><Detail label="Urgency" value={label(lead.urgency)} /></div>
            <div className="mt-4 rounded-lg border border-emerald-100 bg-emerald-50/60 p-4 text-sm leading-6 text-slate-700">{lead.ai_summary ?? "No summary available."}</div>
          </Section>
          <Section title="Follow-up draft">
            <p className="mb-3 text-sm text-slate-500">Generate a message to review. Nothing is sent automatically.</p>
            <button onClick={generateDraft} disabled={drafting} className="btn btn-secondary text-sm">{drafting ? "Writing…" : "Generate follow-up message"}</button>
            {draft && <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-4"><p className="text-sm leading-6">{draft}</p><button onClick={() => navigator.clipboard.writeText(draft)} className="mt-3 text-xs font-bold text-[#116149]">Copy message</button></div>}
          </Section>
        </div>
        <div className="space-y-5">
          <Section title="Follow-up information">
            <div className="space-y-4 text-sm"><Detail label="Last contacted" value={formatDate(lead.last_contacted_at)} /><Detail label="Next follow-up" value={formatDate(lead.next_followup_at)} /></div>
          </Section>
          <Section title="Add note">
            <form onSubmit={addNote}><textarea name="note" required rows={3} className="field" placeholder="What happened on the call?" /><button className="btn btn-primary mt-3 text-sm">Save note</button></form>
          </Section>
          <Section title="Timeline">
            <div className="space-y-5">
              {events.map((item) => <div key={item.id} className="relative border-l-2 border-emerald-100 pl-4"><span className="absolute -left-[5px] top-1 size-2 rounded-full bg-[#116149]" /><p className="text-sm font-bold">{label(item.event_type)}</p><p className="text-xs text-slate-500">{formatDate(item.created_at)}</p>{typeof item.metadata.note === "string" && <p className="mt-1 text-sm text-slate-600">{item.metadata.note}</p>}</div>)}
            </div>
          </Section>
        </div>
      </div>
    </>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="card p-5"><h2 className="mb-4 font-extrabold">{title}</h2>{children}</section>;
}

function Detail({ label: title, value, link }: { label: string; value: string | null | undefined; link?: string }) {
  const shown = value || "Not provided";
  return <div><p className="mb-1 text-xs font-bold uppercase tracking-wide text-slate-400">{title}</p>{link ? <a href={link} className="font-semibold text-[#116149] hover:underline">{shown}</a> : <p className="font-semibold text-slate-700">{shown}</p>}</div>;
}
