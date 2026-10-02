"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";

import { LeadTable } from "@/components/lead-table";
import { PageHeading } from "@/components/page-heading";
import { apiFetch } from "@/lib/api";
import type { Lead, LeadSource, LeadStatus, Urgency } from "@/lib/types";

interface LeadList { items: Lead[]; total: number }

export default function LeadsPage() {
  const [data, setData] = useState<LeadList>({ items: [], total: 0 });
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState({ status: "", urgency: "", source: "", sort: "newest" });
  const [error, setError] = useState("");

  const load = useCallback((search = query, values = filters) => {
    const params = new URLSearchParams({ sort: values.sort });
    if (search) params.set("search", search);
    if (values.status) params.set("status", values.status);
    if (values.urgency) params.set("urgency", values.urgency);
    if (values.source) params.set("source", values.source);
    apiFetch<LeadList>(`/leads?${params}`).then(setData).catch((err: Error) => setError(err.message));
  }, [filters, query]);

  useEffect(() => { load(); }, [load]);

  function search(event: FormEvent) {
    event.preventDefault();
    load();
  }

  function updateFilter(key: keyof typeof filters, value: string) {
    const next = { ...filters, [key]: value };
    setFilters(next);
    load(query, next);
  }

  return (
    <>
      <PageHeading
        title="Leads"
        description={`${data.total} total lead${data.total === 1 ? "" : "s"}`}
        action={<Link href="/leads/new" className="btn btn-primary text-sm">+ New lead</Link>}
      />
      <form onSubmit={search} className="card mb-5 grid gap-3 p-4 md:grid-cols-[2fr_repeat(4,1fr)_auto]">
        <input aria-label="Search leads" className="field" placeholder="Search name, phone, email…" value={query} onChange={(event) => setQuery(event.target.value)} />
        <select aria-label="Status" className="field" value={filters.status} onChange={(event) => updateFilter("status", event.target.value)}>
          <option value="">All statuses</option>{(["NEW", "CONTACTED", "BOOKED", "LOST"] satisfies LeadStatus[]).map((value) => <option key={value}>{value}</option>)}
        </select>
        <select aria-label="Urgency" className="field" value={filters.urgency} onChange={(event) => updateFilter("urgency", event.target.value)}>
          <option value="">All urgency</option>{(["LOW", "NORMAL", "HIGH", "EMERGENCY"] satisfies Urgency[]).map((value) => <option key={value}>{value}</option>)}
        </select>
        <select aria-label="Source" className="field" value={filters.source} onChange={(event) => updateFilter("source", event.target.value)}>
          <option value="">All sources</option>{(["WEBSITE", "WEBSITE_FORM", "WEBSITE_WEBHOOK", "EMAIL", "PHONE", "MANUAL", "WHATSAPP", "CHAT_WIDGET"] satisfies LeadSource[]).map((value) => <option key={value}>{value}</option>)}
        </select>
        <select aria-label="Sort" className="field" value={filters.sort} onChange={(event) => updateFilter("sort", event.target.value)}>
          <option value="newest">Newest first</option><option value="oldest">Oldest first</option>
        </select>
        <button className="btn btn-secondary" type="submit">Search</button>
      </form>
      {error && <div className="mb-5 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}
      <div className="card overflow-hidden"><LeadTable leads={data.items} /></div>
    </>
  );
}
