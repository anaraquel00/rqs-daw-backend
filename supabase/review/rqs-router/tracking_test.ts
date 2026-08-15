import {
  createTrackingFingerprint,
  detectSource,
  getClientAddress,
  redirectResponse,
  trackingDecision,
} from "./tracking.ts";

function assertEquals<T>(actual: T, expected: T): void {
  if (actual !== expected) {
    throw new Error(`Expected ${String(expected)}, got ${String(actual)}`);
  }
}

Deno.test("explicit source takes precedence", () => {
  const req = new Request("https://go.example/link", {
    headers: { referer: "https://facebook.com/" },
  });
  const url = new URL("https://go.example/link?src=instagram");
  assertEquals(detectSource(req, url), "source_instagram");
});

Deno.test("referer, user-agent and direct fallbacks are classified", () => {
  const fromTikTok = new Request("https://go.example/link", {
    headers: { referer: "https://www.tiktok.com/" },
  });
  assertEquals(
    detectSource(fromTikTok, new URL(fromTikTok.url)),
    "source_tiktok",
  );

  const fromYouTubeApp = new Request("https://go.example/link", {
    headers: { "user-agent": "YouTube/19 Mobile" },
  });
  assertEquals(
    detectSource(fromYouTubeApp, new URL(fromYouTubeApp.url)),
    "source_youtube",
  );

  const direct = new Request("https://go.example/link");
  assertEquals(detectSource(direct, new URL(direct.url)), "source_direct");

  const deceptiveReferer = new Request("https://go.example/link", {
    headers: {
      referer: "https://example.com/redirect?next=https://instagram.com/",
    },
  });
  assertEquals(
    detectSource(deceptiveReferer, new URL(deceptiveReferer.url)),
    "source_direct",
  );
});

Deno.test("HEAD, prefetch and automated clients do not count", () => {
  assertEquals(
    trackingDecision(new Request("https://go.example/link", { method: "HEAD" }))
      .track,
    false,
  );
  assertEquals(
    trackingDecision(
      new Request("https://go.example/link", {
        headers: { purpose: "prefetch" },
      }),
    ).track,
    false,
  );
  assertEquals(
    trackingDecision(
      new Request("https://go.example/link", {
        headers: { "user-agent": "facebookexternalhit/1.1" },
      }),
    ).track,
    false,
  );
  assertEquals(
    trackingDecision(new Request("https://go.example/link")).track,
    false,
  );
});

Deno.test("human GET is eligible for tracking", () => {
  const decision = trackingDecision(
    new Request("https://go.example/link", {
      headers: { "user-agent": "Mozilla/5.0" },
    }),
  );
  assertEquals(decision.track, true);
});

Deno.test("fingerprint is stable, salted and contains no raw address", async () => {
  const req = new Request("https://go.example/link", {
    headers: {
      "user-agent": "Mozilla/5.0",
      "cf-connecting-ip": "203.0.113.10",
    },
  });

  const salt = "test-salt-0123456789abcdef0123456789abcdef";
  const first = await createTrackingFingerprint(req, "link-id", salt);
  const second = await createTrackingFingerprint(req, "link-id", salt);

  if (!("fingerprint" in first) || !("fingerprint" in second)) {
    throw new Error("Expected a fingerprint");
  }

  assertEquals(first.fingerprint, second.fingerprint);
  assertEquals(first.fingerprint.length, 64);
  assertEquals(first.fingerprint.includes("203.0.113.10"), false);
});

Deno.test("fingerprint fails closed without salt or client address", async () => {
  const noAddress = new Request("https://go.example/link", {
    headers: { "user-agent": "Mozilla/5.0" },
  });
  const missingAddress = await createTrackingFingerprint(
    noAddress,
    "link-id",
    "test-salt-0123456789abcdef0123456789abcdef",
  );
  assertEquals("track" in missingAddress && missingAddress.track, false);

  const noSalt = new Request("https://go.example/link", {
    headers: { "cf-connecting-ip": "203.0.113.10" },
  });
  const missingSalt = await createTrackingFingerprint(
    noSalt,
    "link-id",
    undefined,
  );
  assertEquals("track" in missingSalt && missingSalt.track, false);

  const weakSalt = await createTrackingFingerprint(
    new Request("https://go.example/link", {
      headers: { "cf-connecting-ip": "203.0.113.10" },
    }),
    "link-id",
    "too-short",
  );
  assertEquals("track" in weakSalt && weakSalt.track, false);
});

Deno.test("client address accepts only the Supabase edge gateway CF header", () => {
  const gateway = new Request("https://go.example/link", {
    headers: {
      "cf-connecting-ip": "203.0.113.10",
      "x-real-ip": "203.0.113.11",
      "x-forwarded-for": "198.51.100.99",
    },
  });
  assertEquals(getClientAddress(gateway), "203.0.113.10");

  const untrustedOnly = new Request("https://go.example/link", {
    headers: {
      "x-real-ip": "203.0.113.11",
      "x-forwarded-for": "198.51.100.99",
    },
  });
  assertEquals(getClientAddress(untrustedOnly), null);
});

Deno.test("redirect response is temporary and cannot be cached", () => {
  const response = redirectResponse("https://example.com/target");
  assertEquals(response.status, 302);
  assertEquals(response.headers.get("location"), "https://example.com/target");
  assertEquals(response.headers.get("cache-control"), "no-store, private");
  assertEquals(response.headers.get("pragma"), "no-cache");
  assertEquals(response.headers.get("referrer-policy"), "no-referrer");
});
