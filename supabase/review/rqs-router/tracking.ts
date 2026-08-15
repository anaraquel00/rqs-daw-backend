export const SOURCE_MAP = {
  instagram: "source_instagram",
  tiktok: "source_tiktok",
  facebook: "source_facebook",
  youtube: "source_youtube",
  direct: "source_direct",
} as const;

export type SourceColumn = (typeof SOURCE_MAP)[keyof typeof SOURCE_MAP];

export type TrackingDecision =
  | { track: true }
  | {
    track: false;
    reason:
      | "method"
      | "prefetch"
      | "automated-client"
      | "missing-user-agent"
      | "missing-client-address"
      | "missing-fingerprint-salt"
      | "weak-fingerprint-salt";
  };

export type TrackingSkipDecision = Exclude<
  TrackingDecision,
  { track: true }
>;

const AUTOMATED_CLIENT_PATTERN = new RegExp(
  [
    "bot",
    "crawler",
    "spider",
    "preview",
    "facebookexternalhit",
    "facebot",
    "twitterbot",
    "linkedinbot",
    "slackbot",
    "discordbot",
    "telegrambot",
    "skypeuripreview",
  ].join("|"),
  "i",
);

function isDomainOrSubdomain(hostname: string, domain: string): boolean {
  return hostname === domain || hostname.endsWith(`.${domain}`);
}

function getRefererHostname(req: Request): string {
  const referer = req.headers.get("referer");
  if (!referer) return "";

  try {
    return new URL(referer).hostname.toLowerCase().replace(/\.$/, "");
  } catch {
    return "";
  }
}

export function detectSource(req: Request, url: URL): SourceColumn {
  // `src` is a campaign attribution hint, not trusted proof of origin.
  const explicitSource = url.searchParams.get("src")?.trim().toLowerCase();
  if (
    explicitSource &&
    Object.prototype.hasOwnProperty.call(SOURCE_MAP, explicitSource)
  ) {
    return SOURCE_MAP[explicitSource as keyof typeof SOURCE_MAP];
  }

  const refererHostname = getRefererHostname(req);
  if (isDomainOrSubdomain(refererHostname, "instagram.com")) {
    return "source_instagram";
  }
  if (isDomainOrSubdomain(refererHostname, "tiktok.com")) {
    return "source_tiktok";
  }
  if (
    isDomainOrSubdomain(refererHostname, "facebook.com") ||
    isDomainOrSubdomain(refererHostname, "fb.com")
  ) {
    return "source_facebook";
  }
  if (
    isDomainOrSubdomain(refererHostname, "youtube.com") ||
    isDomainOrSubdomain(refererHostname, "youtu.be")
  ) {
    return "source_youtube";
  }

  const userAgent = req.headers.get("user-agent")?.toLowerCase() ?? "";
  if (userAgent.includes("instagram")) return "source_instagram";
  if (userAgent.includes("tiktok")) return "source_tiktok";
  if (userAgent.includes("facebook")) return "source_facebook";
  if (userAgent.includes("youtube")) return "source_youtube";

  return "source_direct";
}

export function trackingDecision(req: Request): TrackingDecision {
  if (req.method !== "GET") {
    return { track: false, reason: "method" };
  }

  const purpose = [
    req.headers.get("purpose"),
    req.headers.get("sec-purpose"),
    req.headers.get("x-purpose"),
    req.headers.get("x-moz"),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();

  if (purpose.includes("prefetch") || purpose.includes("prerender")) {
    return { track: false, reason: "prefetch" };
  }

  const userAgent = req.headers.get("user-agent")?.trim() ?? "";
  if (!userAgent) {
    return { track: false, reason: "missing-user-agent" };
  }

  if (AUTOMATED_CLIENT_PATTERN.test(userAgent)) {
    return { track: false, reason: "automated-client" };
  }

  return { track: true };
}

export function getClientAddress(req: Request): string | null {
  // Trust only headers supplied by the platform gateway. Do not use a raw
  // X-Forwarded-For fallback because a public caller may be able to inject or
  // prepend values and bypass deduplication.
  for (const header of ["cf-connecting-ip", "x-real-ip"]) {
    const value = req.headers.get(header)?.trim();
    if (
      value &&
      value.length <= 128 &&
      !/[\u0000-\u001f\u007f]/.test(value)
    ) {
      return value;
    }
  }

  return null;
}

export async function createTrackingFingerprint(
  req: Request,
  linkId: string,
  salt: string | undefined,
): Promise<{ fingerprint: string } | TrackingSkipDecision> {
  if (!salt) {
    return { track: false, reason: "missing-fingerprint-salt" };
  }
  if (salt.length < 32) {
    return { track: false, reason: "weak-fingerprint-salt" };
  }

  const clientAddress = getClientAddress(req);
  if (!clientAddress) {
    return { track: false, reason: "missing-client-address" };
  }

  const userAgent = (req.headers.get("user-agent") ?? "unknown").slice(0, 512);
  const input = new TextEncoder().encode(
    `${salt}\u0000${linkId}\u0000${clientAddress}\u0000${userAgent}`,
  );
  const digest = await crypto.subtle.digest("SHA-256", input);
  const fingerprint = Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");

  return { fingerprint };
}

export function redirectResponse(targetUrl: string): Response {
  return new Response(null, {
    status: 302,
    headers: {
      Location: targetUrl,
      "Cache-Control": "no-store, private",
      Pragma: "no-cache",
      "Referrer-Policy": "no-referrer",
    },
  });
}
