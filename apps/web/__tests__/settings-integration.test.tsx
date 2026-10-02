import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { IntegrationDetails } from "@/app/(app)/settings/page";

describe("IntegrationDetails", () => {
  it("shows webhook, embed, and safe provider status information", () => {
    render(
      <IntegrationDetails
        integration={{
          inbound_webhook_url: "http://localhost:8000/public/inbound/webhook/org-1",
          embed_form_url: "http://localhost:3000/embed/inquiry/org-1",
          embed_code: '<iframe src="http://localhost:3000/embed/inquiry/org-1"></iframe>',
          email_provider: "resend",
          email_configured: true,
        }}
      />,
    );

    expect(screen.getByText("Inbound webhook URL")).toBeInTheDocument();
    expect(screen.getByText("http://localhost:8000/public/inbound/webhook/org-1")).toBeInTheDocument();
    expect(screen.getByText("Resend · Configured")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Copy" })).toHaveLength(3);
  });
});
