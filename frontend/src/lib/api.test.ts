import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthRequiredError, apiFetch, clearAuth, initializeAuth, resetAuthForTests, setAuth } from "./api";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  resetAuthForTests(false);
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("shared API auth lifecycle", () => {
  it("waits for auth initialization before protected requests and attaches Authorization", async () => {
    localStorage.setItem("token", "valid-token");
    const fetchMock = vi.fn(async () => jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    const pending = apiFetch<{ ok: boolean }>("/api/regions");
    expect(fetchMock).not.toHaveBeenCalled();
    initializeAuth();
    await expect(pending).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const calls = (fetchMock as unknown as { mock: { calls: Array<[unknown, RequestInit]> } }).mock.calls;
    const headers = calls[0][1].headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer valid-token");
  });

  it("does not call protected endpoints when boot completes without a token", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const pending = apiFetch("/api/aws/status");
    initializeAuth();
    await expect(pending).rejects.toBeInstanceOf(AuthRequiredError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("clears expired auth on one genuine 401 without a retry loop", async () => {
    setAuth({ token: "expired-token", user: { id: 1, email: "a@example.com" } });
    const fetchMock = vi.fn(async () => jsonResponse({ detail: "Unauthorized" }, 401));
    vi.stubGlobal("fetch", fetchMock);
    await expect(apiFetch("/api/regions")).rejects.toThrow("Unauthorized");
    expect(localStorage.getItem("token")).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await expect(apiFetch("/api/regions")).rejects.toBeInstanceOf(AuthRequiredError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("keeps public auth calls usable before auth restoration", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ token: "new", user: { id: 1, email: "a@example.com" } }));
    vi.stubGlobal("fetch", fetchMock);
    await apiFetch("/api/auth/login", { method: "POST", body: JSON.stringify({ email: "a@example.com", password: "password123" }) });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("clearAuth removes token state consistently", () => {
    setAuth({ token: "token", user: { id: 1, email: "a@example.com" } });
    clearAuth();
    expect(localStorage.getItem("token")).toBeNull();
  });
});
