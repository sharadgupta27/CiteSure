import { ApiError, api, setAuthToken, setUnauthorizedHandler, unwrap } from "./client";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
  setAuthToken(null);
  setUnauthorizedHandler(null);
});

describe("api client", () => {
  it("adds the bearer token to every request once signed in", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json([]));
    vi.stubGlobal("fetch", fetchMock);
    setAuthToken("secret-token");
    await api.GET("/workspaces");
    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(request.headers.get("Authorization")).toBe("Bearer secret-token");
    expect(new URL(request.url).pathname).toBe("/api/v1/workspaces");
  });

  it("sends no Authorization header when signed out", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ code: "unauthorized", detail: "Missing bearer token" }, 401));
    vi.stubGlobal("fetch", fetchMock);
    await api.GET("/workspaces");
    expect((fetchMock.mock.calls[0]?.[0] as Request).headers.get("Authorization")).toBeNull();
  });

  it("calls the unauthorized handler when the token is rejected", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ code: "unauthorized", detail: "Invalid or expired token" }, 401)));
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    setAuthToken("expired");
    await api.GET("/workspaces");
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("does not treat a failed login as an expired session", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ code: "unauthorized", detail: "Wrong email or password" }, 401)));
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    await api.POST("/auth/login", { body: { email: "a@b.co", password: "x" } });
    expect(handler).not.toHaveBeenCalled();
  });
});

describe("unwrap", () => {
  it("returns the data of a successful call", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json([{ id: "w1", name: "Acme", role: "admin", created_at: "x" }])));
    const data = unwrap(await api.GET("/workspaces"));
    expect(data[0]?.name).toBe("Acme");
  });

  it("throws an ApiError carrying the server's code and message", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ code: "conflict", detail: "This file was already uploaded" }, 409)));
    const call = async () => unwrap(await api.GET("/workspaces"));
    await expect(call()).rejects.toBeInstanceOf(ApiError);
    await expect(call()).rejects.toMatchObject({ status: 409, code: "conflict", message: "This file was already uploaded" });
  });
});
