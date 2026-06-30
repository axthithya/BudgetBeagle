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
});
