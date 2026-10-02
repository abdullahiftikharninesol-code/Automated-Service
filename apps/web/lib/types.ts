export type LeadStatus = "NEW" | "CONTACTED" | "BOOKED" | "LOST";
export type Urgency = "LOW" | "NORMAL" | "HIGH" | "EMERGENCY";
export type LeadSource =
  | "WEBSITE"
  | "WEBSITE_FORM"
  | "WEBSITE_WEBHOOK"
  | "EMAIL"
  | "WHATSAPP"
  | "PHONE"
  | "MANUAL"
  | "CHAT_WIDGET";
export type InboundChannel = Exclude<LeadSource, "WEBSITE">;
export type BusinessType =
  | "GENERAL"
  | "HVAC"
  | "ECOMMERCE"
  | "CLOTHING"
  | "DENTAL"
  | "REAL_ESTATE"
  | "AGENCY"
  | "HOME_SERVICES";

export interface User {
  id: string;
  organization_id: string;
  name: string;
  email: string;
  role: "OWNER" | "MEMBER";
}

export interface Lead {
  id: string;
  organization_id: string;
  customer_name: string;
  customer_email: string | null;
  customer_phone: string | null;
  intent: string | null;
  category_or_service: string | null;
  service_type: string | null;
  product_name: string | null;
  product_variant: string | null;
  quantity: number | null;
  ai_additional_fields: Record<string, unknown>;
  message: string;
  location: string | null;
  urgency: Urgency;
  preferred_date: string | null;
  preferred_time: string | null;
  preferred_date_text: string | null;
  preferred_time_text: string | null;
  source: LeadSource;
  status: LeadStatus;
  ai_summary: string | null;
  latest_inbound_message: string;
  created_at: string;
  updated_at: string;
  last_contacted_at: string | null;
  next_followup_at: string | null;
  booked_at: string | null;
  lost_at: string | null;
}

export interface LeadEvent {
  id: string;
  lead_id: string;
  event_type: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface Organization {
  id: string;
  name: string;
  industry: string;
  business_type: BusinessType;
  timezone: string;
  duplicate_window_minutes: number;
  followup_new_lead_minutes: number;
  followup_second_reminder_hours: number;
  followup_contacted_hours: number;
  followup_final_days: number;
}

export interface InboundMessage {
  id: string;
  organization_id: string;
  lead_id: string;
  channel: InboundChannel;
  external_message_id: string | null;
  customer_name: string;
  customer_email: string | null;
  customer_phone: string | null;
  message_text: string;
  metadata: Record<string, unknown>;
  received_at: string;
  processed_at: string | null;
  created_at: string;
}

export interface OrganizationIntegration {
  inbound_webhook_url: string;
  embed_form_url: string;
  embed_code: string;
  email_provider: string;
  email_configured: boolean;
}

export interface DashboardData {
  counts: Record<"new" | "needs_attention" | "contacted" | "booked" | "lost", number>;
  needs_attention: Lead[];
  recent_leads: Lead[];
}
