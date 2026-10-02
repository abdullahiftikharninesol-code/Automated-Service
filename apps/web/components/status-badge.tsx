import type { LeadSource, LeadStatus, Urgency } from "@/lib/types";
import { label } from "@/lib/format";

const statusStyles: Record<LeadStatus, string> = {
  NEW: "bg-blue-50 text-blue-700 ring-blue-200",
  CONTACTED: "bg-amber-50 text-amber-800 ring-amber-200",
  BOOKED: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  LOST: "bg-stone-100 text-stone-600 ring-stone-200",
};

const urgencyStyles: Record<Urgency, string> = {
  LOW: "bg-slate-100 text-slate-600 ring-slate-200",
  NORMAL: "bg-sky-50 text-sky-700 ring-sky-200",
  HIGH: "bg-orange-50 text-orange-700 ring-orange-200",
  EMERGENCY: "bg-red-50 text-red-700 ring-red-200",
};

export function StatusBadge({ status }: { status: LeadStatus }) {
  return (
    <span className={`rounded-full px-2.5 py-1 text-xs font-bold ring-1 ring-inset ${statusStyles[status]}`}>
      {label(status)}
    </span>
  );
}

export function UrgencyBadge({ urgency }: { urgency: Urgency }) {
  return (
    <span className={`rounded-full px-2.5 py-1 text-xs font-bold ring-1 ring-inset ${urgencyStyles[urgency]}`}>
      {label(urgency)}
    </span>
  );
}

export function SourceBadge({ source }: { source: LeadSource }) {
  return (
    <span className="rounded-full bg-violet-50 px-2.5 py-1 text-xs font-bold text-violet-700 ring-1 ring-inset ring-violet-200">
      {label(source)}
    </span>
  );
}
