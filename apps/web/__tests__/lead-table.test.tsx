import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LeadTable } from "@/components/lead-table";

describe("LeadTable", () => {
  it("shows a useful empty state", () => {
    render(<LeadTable leads={[]} />);
    expect(screen.getByText("No leads match this view.")).toBeInTheDocument();
  });
});
