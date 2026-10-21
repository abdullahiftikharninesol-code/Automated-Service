import Link from "next/link";

import { formatDate } from "@/lib/format";
import type { Lead } from "@/lib/types";
import { QualificationBadge, SourceBadge, StatusBadge, UrgencyBadge } from "./status-badge";

export function LeadTable({ leads }: { leads: Lead[] }) {
  if (!leads.length) {
    return <div className="p-8 text-center text-sm text-slate-500">No leads match this view.</div>;
  }
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Customer</th><th>Product / service</th><th>Urgency</th><th>Source</th><th>Created</th><th>Last contact</th><th>Next follow-up</th><th>Status</th>
          </tr>
        </thead>
        <tbody>
          {leads.map((lead) => (
            <tr key={lead.id} className="hover:bg-slate-50/70">
              <td>
                <Link href={`/leads/${lead.id}`} className="font-bold text-[#116149] hover:underline">{lead.customer_name}</Link>
                <div className="mt-0.5 text-xs text-slate-500">{lead.customer_phone ?? lead.customer_email}</div>
              </td>
              <td><div>{lead.product_name ?? lead.category_or_service ?? lead.service_type ?? "Not identified"}</div><div className="mt-1 max-w-xs truncate text-xs text-slate-500">{lead.latest_inbound_message}</div></td>
              <td><UrgencyBadge urgency={lead.urgency} /></td>
              <td><SourceBadge source={lead.source} /></td>
              <td className="text-sm text-slate-600">{formatDate(lead.created_at)}</td>
              <td className="text-sm text-slate-600">{formatDate(lead.last_contacted_at)}</td>
              <td className="text-sm text-slate-600">{formatDate(lead.next_followup_at)}</td>
              <td>
                <div className="flex flex-col gap-1 items-start">
                  <StatusBadge status={lead.status} />
                  <QualificationBadge status={lead.qualification_status} />
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
