"use client";

import { useParams } from "next/navigation";

import { InquiryForm } from "@/components/inquiry-form";

export default function EmbeddedInquiryPage() {
  const { organizationId } = useParams<{ organizationId: string }>();
  return <InquiryForm organizationId={organizationId} />;
}
