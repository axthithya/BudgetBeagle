import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetAuthForTests } from "../lib/api";
import Dashboard from "./Dashboard";

type RegionsResponse = {
  regions: string[];
  status?: string;
  error?: { message?: string; permission?: string } | null;
};

let regionsResponse: RegionsResponse;
let analyzePayloads: unknown[];
let regionRequestCount: number;

class MockWebSocket {
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) {}
  close() {}
}

function renderDashboard() {
  render(
    <MemoryRouter>
      <Dashboard />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  resetAuthForTests(true);
  localStorage.setItem("token", "test-token");
  analyzePayloads = [];
  regionRequestCount = 0;
  regionsResponse = {
    status: "available",
    regions: ["us-west-2", "bad region", "ap-south-1", "us-east-1"],
  };
  vi.stubGlobal("WebSocket", MockWebSocket);
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost:8000");
    if (url.pathname === "/api/regions") {
      regionRequestCount += 1;
      return jsonResponse(regionsResponse);
    }
    if (url.pathname === "/api/aws/status") {
      return jsonResponse({
        connected: true,
        connection_status: "connected",
        account_id_masked: "****-****-2560",
        identity_type: "user",
        identity_name: "phase2",
        default_region: "us-east-1",
        required_permissions: { available: [], missing: [] },
        optional_permissions: { available: [], missing: [] },
      });
    }
    if (url.pathname === "/api/resource-groups") {
      return jsonResponse({ resource_groups: [] });
    }
    if (url.pathname === "/api/analyze") {
      analyzePayloads.push(JSON.parse(String(init?.body ?? "{}")));
      return jsonResponse({ analysis_id: 99, status: "queued", websocket_url: "/ws/progress/99" });
    }
    return jsonResponse({});
  }));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Dashboard multi-region controls", () => {
  it("keeps the legacy single-region request payload", async () => {
    const user = userEvent.setup();
    renderDashboard();

    await screen.findByRole("heading", { name: "Run Analysis" });
    await user.click(screen.getByRole("button", { name: "Run Analysis" }));

    await waitFor(() => expect(analyzePayloads).toHaveLength(1));
    expect(analyzePayloads[0]).toEqual({ region: "ap-south-1", resource_group: null });
  });

  it("filters selectable regions and posts selected_regions payloads", async () => {
    const user = userEvent.setup();
    renderDashboard();

    await screen.findByRole("heading", { name: "Run Analysis" });
    const selectedMode = screen.getByRole("radio", { name: "Selected regions" });
    selectedMode.focus();
    await user.keyboard("{Enter}");

    await screen.findByRole("heading", { name: "Selected regions" });
    expect(screen.getByText("1 selected")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Select all" }));
    expect(screen.getByText("3 selected")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear all" }));
    expect(screen.getByRole("button", { name: "Run Analysis" })).toBeDisabled();

    await user.type(screen.getByRole("textbox", { name: "Filter regions" }), "west");
    expect(screen.queryByText("ap-south-1")).not.toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: "us-west-2" }));
    expect(screen.getByText("1 selected")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Run Analysis" }));
    await waitFor(() => expect(analyzePayloads).toHaveLength(1));
    expect(analyzePayloads[0]).toEqual({
      region: "us-west-2",
      resource_group: null,
      region_mode: "selected_regions",
      requested_regions: ["us-west-2"],
    });
  });

  it("posts all_enabled_regions payloads after discovery succeeds", async () => {
    const user = userEvent.setup();
    renderDashboard();

    await screen.findByRole("heading", { name: "Run Analysis" });
    await user.click(screen.getByRole("radio", { name: "All enabled regions" }));
    expect(screen.getByText("3 regions resolved by AWS region discovery")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Run Analysis" }));

    await waitFor(() => expect(analyzePayloads).toHaveLength(1));
    expect(analyzePayloads[0]).toEqual({
      region: "ap-south-1",
      resource_group: null,
      region_mode: "all_enabled_regions",
      requested_regions: [],
    });
  });

  it("shows loading, empty, permission-denied, and retry states", async () => {
    regionsResponse = {
      status: "permission_denied",
      regions: [],
      error: { message: "Missing region discovery permission.", permission: "ec2:DescribeRegions" },
    };
    const user = userEvent.setup();
    renderDashboard();

    await screen.findByRole("heading", { name: "Run Analysis" });
    await user.click(screen.getByRole("radio", { name: "All enabled regions" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Region discovery permission denied");
    expect(screen.getByRole("alert")).toHaveTextContent("ec2:DescribeRegions");
    expect(screen.getByRole("button", { name: "Run Analysis" })).toBeDisabled();

    regionsResponse = { status: "empty", regions: [], error: { message: "No regions." } };
    await user.click(within(screen.getByRole("alert")).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(regionRequestCount).toBe(2));
    expect(screen.getByRole("alert")).toHaveTextContent("No enabled regions returned");

    regionsResponse = { status: "available", regions: ["us-east-1"] };
    await user.click(within(screen.getByRole("alert")).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(regionRequestCount).toBe(3));
    expect(screen.getByText("1 regions resolved by AWS region discovery")).toBeInTheDocument();
  });
});

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
