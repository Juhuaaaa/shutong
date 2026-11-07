import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, request, setUnauthorizedHandler } from "./client";

function respond(status: number, body: unknown) {
  return vi.fn().mockResolvedValue(new Response(body === undefined ? null : JSON.stringify(body), { status }));
}

afterEach(() => {
  vi.unstubAllGlobals();
  setUnauthorizedHandler(() => {});
});

describe("request", () => {
  it("returns parsed JSON", async () => {
    vi.stubGlobal("fetch", respond(200, { id: 1 }));
    expect(await request("GET", "/api/libraries/1")).toEqual({ id: 1 });
  });

  it("joins a list-shaped 422 detail into one message", async () => {
    vi.stubGlobal("fetch", respond(422, { detail: [{ msg: "地址要以 http:// 开头" }, { msg: "名字不能为空" }] }));
    await expect(request("POST", "/api/servers", { body: {} })).rejects.toMatchObject({
      status: 422,
      detail: "地址要以 http:// 开头；名字不能为空",
    });
  });

  it("calls the unauthorized handler on 401", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    vi.stubGlobal("fetch", respond(401, { detail: "未登录" }));
    await expect(request("GET", "/api/libraries")).rejects.toBeInstanceOf(ApiError);
    expect(handler).toHaveBeenCalledOnce();
  });

  it("serializes the query and skips undefined values", async () => {
    const fetchMock = respond(200, []);
    vi.stubGlobal("fetch", fetchMock);
    await request("GET", "/api/items", { query: { library_id: 1, status: undefined, q: "迷宫饭" } });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/items?library_id=1&q=%E8%BF%B7%E5%AE%AB%E9%A5%AD");
  });

  it("sends JSON bodies with credentials", async () => {
    const fetchMock = respond(200, { ok: true });
    vi.stubGlobal("fetch", fetchMock);
    await request("POST", "/api/auth/login", { body: { password: "x" } });
    const init = fetchMock.mock.calls[0][1];
    expect([init.method, init.credentials, init.body]).toEqual(["POST", "same-origin", '{"password":"x"}']);
  });

  it("turns a network failure into an ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(request("GET", "/api/libraries")).rejects.toMatchObject({ status: 0 });
  });
});
