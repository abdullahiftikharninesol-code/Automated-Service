import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SourceBadge, StatusBadge, UrgencyBadge } from "@/components/status-badge";

describe("lead badges", () => {
  it("renders status and urgency in friendly form", () => {
    render(<><StatusBadge status="CONTACTED" /><UrgencyBadge urgency="EMERGENCY" /></>);
    expect(screen.getByText("Contacted")).toBeInTheDocument();
    expect(screen.getByText("Emergency")).toBeInTheDocument();
  });

  it("renders a friendly inbound source badge", () => {
    render(<SourceBadge source="WEBSITE_WEBHOOK" />);
    expect(screen.getByText("Website webhook")).toBeInTheDocument();
  });
});
