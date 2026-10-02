"use client";

import { useParams } from "next/navigation";

import { InquiryForm } from "@/components/inquiry-form";

export default function InquiryPage() {
  const { organizationId } = useParams<{ organizationId: string }>();
  return <InquiryForm organizationId={organizationId} />;
}
