import { handleRequest } from "./index.ts";

function assertEquals<T>(actual: T, expected: T): void {
  if (actual !== expected) {
    throw new Error(`Expected ${String(expected)}, got ${String(actual)}`);
  }
}

function assert(condition: boolean, message: string): void {
  if (!condition) throw new Error(message);
}

type FetchCall = {
  method: string;
  url: string;
  body: string | null;
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

Deno.test("router lookup, tracking, failure fallback and HEAD contract", async () => {
  const originalFetch = globalThis.fetch;
  const previousEnv = new Map<string, string | undefined>();
  const env = {
    SUPABASE_URL: "https://project.supabase.co",
    SUPABASE_SERVICE_ROLE_KEY: ["test", "service", "role", "key"].join("-"),
    UPLINK_TRACKING_SALT: "test-salt-0123456789abcdef0123456789abcdef",
  };

  for (const [key, value] of Object.entries(env)) {
    previousEnv.set(key, Deno.env.get(key));
    Deno.env.set(key, value);
  }

  const calls: FetchCall[] = [];
  let rpcShouldFail = false;

  globalThis.fetch = async (
    input: RequestInfo | URL,
    init?: RequestInit,
  ): Promise<Response> => {
    const request = new Request(input, init);
    const body = request.body ? await request.text() : null;
    calls.push({ method: request.method, url: request.url, body });
    const requestUrl = new URL(request.url);

    if (requestUrl.pathname === "/rest/v1/rqs_uplinks") {
      return json({
        id: "6638dcbb-5454-4b08-a634-4ca5e735b8c9",
        target_url: "https://open.spotify.com/track/test",
      });
    }

    if (requestUrl.pathname === "/rest/v1/rpc/increment_uplink_clicks") {
      if (rpcShouldFail) {
        return json({ code: "P0001", message: "CLICK_QUOTA_EXCEEDED" }, 400);
      }
      return json(true);
    }

    return json({ message: "unexpected request" }, 500);
  };

  try {
    const request = new Request(
      "https://go.raquelsynths.com/flower-newworld?src=instagram",
      {
        headers: {
          "user-agent": "Mozilla/5.0 Instagram 300",
          "cf-connecting-ip": "203.0.113.10",
        },
      },
    );
    const response = await handleRequest(request);

    assertEquals(response.status, 302);
    assertEquals(
      response.headers.get("location"),
      "https://open.spotify.com/track/test",
    );
    assertEquals(response.headers.get("cache-control"), "no-store, private");
    assertEquals(calls.length, 2);

    const rpcCall = calls.find((call) =>
      new URL(call.url).pathname === "/rest/v1/rpc/increment_uplink_clicks"
    );
    assert(Boolean(rpcCall?.body), "Expected one RPC request body");
    const rpcBody = JSON.parse(rpcCall!.body!);
    assertEquals(
      rpcBody.link_id,
      "6638dcbb-5454-4b08-a634-4ca5e735b8c9",
    );
    assertEquals(rpcBody.source_col, "source_instagram");
    assert(
      /^[0-9a-f]{64}$/.test(rpcBody.request_fingerprint),
      "Expected a salted SHA-256 request fingerprint",
    );

    calls.length = 0;
    const headResponse = await handleRequest(
      new Request("https://go.raquelsynths.com/flower-newworld", {
        method: "HEAD",
        headers: { "user-agent": "Mozilla/5.0" },
      }),
    );
    assertEquals(headResponse.status, 302);
    assertEquals(calls.length, 1);
    assertEquals(calls[0].method, "GET");

    calls.length = 0;
    rpcShouldFail = true;
    const failedTrackingResponse = await handleRequest(request);
    assertEquals(failedTrackingResponse.status, 302);
    assertEquals(
      failedTrackingResponse.headers.get("location"),
      "https://open.spotify.com/track/test",
    );
    assertEquals(calls.length, 2);
  } finally {
    globalThis.fetch = originalFetch;
    for (const [key, value] of previousEnv) {
      if (value === undefined) Deno.env.delete(key);
      else Deno.env.set(key, value);
    }
  }
});
