"use client";

import { useState } from "react";

import { apiFetch } from "@/lib/api";
import type { Lead, LeadStatus } from "@/lib/types";

export function LeadActions({ lead, onUpdate }: { lead: Lead; onUpdate: (lead: Lead) => void }) {
  const [busy, setBusy] = useState<LeadStatus | null>(null);
  const options: { status: LeadStatus; label: string; className: string }[] =
    lead.status === "BOOKED" || lead.status === "LOST"
      ? [{ status: "NEW", label: "Reopen lead", className: "btn-secondary" }]
      : [
          { status: "CONTACTED", label: "Mark contacted", className: "btn-secondary" },
          { status: "BOOKED", label: "Mark booked", className: "btn-primary" },
          { status: "LOST", label: "Mark lost", className: "btn-danger" },
        ];

  async function update(status: LeadStatus) {
    setBusy(status);
    try {
      const updated = await apiFetch<Lead>(`/leads/${lead.id}/status`, {
        method: "POST",
        body: JSON.stringify({ status }),
      });
      onUpdate(updated);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-wrap gap-2">
      {options.map((option) => (
        <button
          key={option.status}
          disabled={busy !== null || lead.status === option.status}
          onClick={() => update(option.status)}
          className={`btn ${option.className} text-sm`}
        >
          {busy === option.status ? "Saving…" : option.label}
        </button>
      ))}
    </div>
  );
}
