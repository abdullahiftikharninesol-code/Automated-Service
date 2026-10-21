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
  | "CHAT_WIDGET"
  | "INSTAGRAM"
  | "FACEBOOK";
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

export type ConversationStatus = "OPEN" | "CLOSED" | "ARCHIVED";
export type WaitingOn = "OWNER" | "CUSTOMER" | "SYSTEM" | "NONE";
export type MessageDirection = "INBOUND" | "OUTBOUND";
export type MessageSenderType = "CUSTOMER" | "OWNER" | "SYSTEM" | "AI";
export type MessageDeliveryStatus = "PENDING" | "SENT" | "DELIVERED" | "READ" | "FAILED";

export type QualificationStatus = "NOT_STARTED" | "IN_PROGRESS" | "COMPLETE";
export type QualificationFieldType =
  | "TEXT"
  | "NUMBER"
  | "BOOLEAN"
  | "DATE"
  | "DATETIME"
  | "CHOICE"
  | "MULTI_CHOICE"
  | "PHONE"
  | "EMAIL"
  | "LOCATION";

export interface QualificationField {
  id: string;
  organization_id: string;
  key: string;
  label: string;
  description: string | null;
  field_type: QualificationFieldType;
  required: boolean;
  enabled: boolean;
  sort_order: number;
  question_text: string | null;
  options?: string[] | null;
  example_values?: unknown[] | null;
  created_at: string;
  updated_at: string;
}

export interface User {
  id: string;
  organization_id: string;
  name: string;
  email: string;
  role: "OWNER" | "MEMBER";
}

export interface Customer {
  id: string;
  organization_id: string;
  name: string | null;
  email: string | null;
  email_normalized: string | null;
  phone: string | null;
  phone_normalized: string | null;
  metadata: Record<string, unknown>;
  last_contact_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Conversation {
  id: string;
  organization_id: string;
  customer_id: string | null;
  lead_id: string | null;
  channel: InboundChannel;
  status: ConversationStatus;
  waiting_on: WaitingOn;
  subject: string | null;
  external_thread_id: string | null;
  last_message_at: string | null;
  last_inbound_at: string | null;
  last_outbound_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConversationMessage {
  id: string;
  organization_id: string;
  conversation_id: string;
  direction: MessageDirection;
  channel: InboundChannel;
  sender_type: MessageSenderType;
  body: string;
  external_message_id: string | null;
  delivery_status: MessageDeliveryStatus | null;
  metadata: Record<string, unknown>;
  sent_at: string;
  created_at: string;
}

export interface Lead {
  id: string;
  organization_id: string;
  customer_name: string;
  customer_email: string | null;
  customer_phone: string | null;
  customer_phone_normalized?: string | null;
  customer_id?: string | null;
  primary_conversation_id?: string | null;
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
  qualifications?: Record<string, unknown> | null;
  qualification_status?: QualificationStatus | null;
  qualification_completed_at?: string | null;
  qualification_metadata?: Record<string, unknown> | null;
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
  default_phone_region?: string | null;
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
  customer_phone_normalized?: string | null;
  message_text: string;
  metadata: Record<string, unknown>;
  received_at: string;
  processed_at: string | null;
  created_at: string;
}

export interface ConversationDetail extends Conversation {
  customer: Customer | null;
  messages: ConversationMessage[];
}

export interface OrganizationIntegration {
  inbound_webhook_url: string;
  embed_form_url: string;
  embed_code: string;
  email_provider: string;
  email_configured: boolean;
  webhook_secret_configured?: boolean;
  whatsapp_enabled?: boolean;
  whatsapp_configured?: boolean;
  whatsapp_phone_number_id?: string | null;
  whatsapp_display_phone_number?: string | null;
  whatsapp_webhook_url?: string;
}

export interface DashboardData {
  counts: Record<"new" | "needs_attention" | "contacted" | "booked" | "lost", number>;
  needs_attention: Lead[];
  recent_leads: Lead[];
}
