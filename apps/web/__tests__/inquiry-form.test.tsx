import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { InquiryForm } from "@/components/inquiry-form";

describe("InquiryForm", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("submits the public embed form through the shared inbound endpoint", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: "org-1",
            name: "UrbanWear",
            industry: "Retail",
            business_type: "CLOTHING",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ success: true, lead_id: "lead-1", status: "NEW" }),
          { status: 201, headers: { "Content-Type": "application/json" } },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<InquiryForm organizationId="org-1" />);
    expect(await screen.findByText("UrbanWear")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Sara" } });
    fireEvent.change(screen.getByLabelText("Phone"), {
      target: { value: "+923001234567" },
    });
    fireEvent.change(screen.getByLabelText("Message"), {
      target: { value: "Do you have the black dress in medium?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send inquiry" }));

    expect(await screen.findByText("Request received")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1][0]).toContain("/public/inbound/form/org-1");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toMatchObject({
      name: "Sara",
      phone: "+923001234567",
    });
  });
});
