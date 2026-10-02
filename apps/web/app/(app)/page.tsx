"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { LeadActions } from "@/components/lead-actions";
import { LeadTable } from "@/components/lead-table";
import { PageHeading } from "@/components/page-heading";
import { SourceBadge, StatusBadge, UrgencyBadge } from "@/components/status-badge";
import { apiFetch } from "@/lib/api";
import { formatDate, timeAgo } from "@/lib/format";
import type { DashboardData, Lead } from "@/lib/types";

const cards: { key: keyof DashboardData["counts"]; label: string; tone: string }[] = [
  { key: "new", label: "New leads", tone: "text-blue-700" },
  { key: "needs_attention", label: "Needs attention", tone: "text-orange-700" },
  { key: "contacted", label: "Contacted", tone: "text-amber-700" },
  { key: "booked", label: "Booked", tone: "text-emerald-700" },
  { key: "lost", label: "Lost", tone: "text-slate-600" },
];

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    apiFetch<DashboardData>("/dashboard").then(setData).catch((err: Error) => setError(err.message));
  }, []);
  useEffect(load, [load]);

  function replaceLead(updated: Lead) {
    setData((current) =>
      current
        ? {
            ...current,
            needs_attention: current.needs_attention.filter((lead) => lead.id !== updated.id),
            recent_leads: current.recent_leads.map((lead) =>
              lead.id === updated.id ? updated : lead,
            ),
          }
        : current,
    );
    load();
  }

  return (
    <>
      <PageHeading
        title="Who needs your attention?"
        description="Follow up with the right customers before opportunities go cold."
        action={<Link href="/leads/new" className="btn btn-primary text-sm">+ Add lead</Link>}
      />
      {error && <div className="mb-5 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}
      <div className="mb-8 grid grid-cols-2 gap-3 lg:grid-cols-5">
        {cards.map((card) => (
          <div key={card.key} className="card p-4">
            <p className="text-xs font-bold uppercase tracking-wide text-slate-500">{card.label}</p>
            <p className={`mt-2 text-3xl font-extrabold ${card.tone}`}>{data?.counts[card.key] ?? "—"}</p>
          </div>
        ))}
      </div>

      <section className="mb-8 overflow-hidden rounded-2xl border border-orange-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-orange-100 bg-orange-50/60 px-5 py-4">
          <div>
            <h2 className="font-extrabold">Needs attention</h2>
            <p className="text-xs text-slate-500">Urgent leads and overdue follow-ups</p>
          </div>
          <span className="grid size-8 place-items-center rounded-full bg-orange-100 text-sm font-black text-orange-700">{data?.needs_attention.length ?? 0}</span>
        </div>
        <div className="divide-y divide-slate-100">
          {data && data.needs_attention.length === 0 && (
            <div className="p-10 text-center">
              <div className="text-2xl">✓</div>
              <p className="mt-2 font-bold">All caught up.</p>
              <p className="text-sm text-slate-500">No leads need attention right now.</p>
            </div>
          )}
          {data?.needs_attention.map((lead) => (
            <article key={lead.id} className="p-5">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <Link href={`/leads/${lead.id}`} className="text-lg font-extrabold hover:text-[#116149]">{lead.customer_name}</Link>
                    <StatusBadge status={lead.status} />
                    <UrgencyBadge urgency={lead.urgency} />
                    <SourceBadge source={lead.source} />
                  </div>
                  <p className="font-semibold">{lead.product_name ?? lead.category_or_service ?? lead.service_type ?? "Customer inquiry"}</p>
                  <p className="mt-1 max-w-2xl truncate text-sm text-slate-600">{lead.latest_inbound_message}</p>
                  <p className="mt-1 text-sm text-slate-500">
                    Received {timeAgo(lead.created_at)} · Next action {formatDate(lead.next_followup_at)}
                  </p>
                  <p className="mt-1 text-sm text-slate-600">{lead.customer_phone} {lead.customer_email && `· ${lead.customer_email}`}</p>
                </div>
                <div className="flex flex-col items-end gap-2">
                  <LeadActions lead={lead} onUpdate={replaceLead} />
                  <Link href={`/leads/${lead.id}`} className="text-sm font-bold text-[#116149] hover:underline">View lead →</Link>
                </div>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="card overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <h2 className="font-extrabold">Recent leads</h2>
          <Link href="/leads" className="text-sm font-bold text-[#116149] hover:underline">View all</Link>
        </div>
        <LeadTable leads={data?.recent_leads ?? []} />
      </section>
    </>
  );
}
