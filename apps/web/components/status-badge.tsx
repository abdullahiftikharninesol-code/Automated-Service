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
  const isWhatsApp = source === "WHATSAPP";
  const badgeClass = isWhatsApp
    ? "bg-emerald-50 text-emerald-800 ring-emerald-300 font-extrabold"
    : "bg-violet-50 text-violet-700 ring-violet-200";

  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs ring-1 ring-inset ${badgeClass}`}>
      {isWhatsApp && <span>💬</span>}
      {label(source)}
    </span>
  );
}

export function QualificationBadge({ status }: { status?: string | null }) {
  if (!status || status === "NOT_STARTED") return null;
  const isComplete = status === "COMPLETE";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-bold ring-1 ring-inset ${
        isComplete
          ? "bg-teal-50 text-teal-800 ring-teal-300"
          : "bg-amber-50 text-amber-800 ring-amber-300"
      }`}
    >
      {isComplete ? "✓ Qualified" : "⏳ Incomplete"}
    </span>
  );
}

