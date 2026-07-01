import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ProgressTracker } from "./ProgressTracker";

describe("ProgressTracker accessibility", () => {
  it("announces the idle state as a polite status", () => {
    render(<ProgressTracker messages={[]} />);
    expect(screen.getByRole("status")).toHaveTextContent("No active run");
  });

  it("announces progress messages without exposing decorative markers", () => {
    render(<ProgressTracker messages={["Scanning AWS resources", "Analysis complete"]} />);
    const status = screen.getByRole("status", { name: "Analysis progress" });
    expect(status).toHaveTextContent("Scanning AWS resources");
    expect(status).toHaveTextContent("Analysis complete");
  });
  it("renders multi-region progress details and clamps the percentage", () => {
    render(
      <ProgressTracker
        messages={["Scanning AWS resources across 2 regions"]}
        details={{
          region_mode: "selected_regions",
          total_region_count: 2,
          completed_region_count: 1,
          failed_region_count: 1,
          active_regions: ["us-east-1"],
          current_service: "EC2",
          warning_count: 1,
          overall_percentage: 120,
        }}
      />,
    );
    const status = screen.getByRole("status", { name: "Analysis progress" });
    expect(status).toHaveTextContent("Selected regions");
    expect(status).toHaveTextContent("Overall progress: 100%");
    expect(status).toHaveTextContent("Regions: 2/2");
    expect(status).toHaveTextContent("Failed: 1");
    expect(status).toHaveTextContent("Warnings: 1");
    expect(status).toHaveTextContent("Active: us-east-1");
    expect(status).toHaveTextContent("Service: EC2");
  });
});
