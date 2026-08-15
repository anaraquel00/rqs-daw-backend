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
      | "missing-client-address"
      | "missing-fingerprint-salt";
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

export function detectSource(req: Request, url: URL): SourceColumn {
  // `src` is a campaign attribution hint, not trusted proof of origin.
  const explicitSource = url.searchParams.get("src")?.trim().toLowerCase();
  if (
    explicitSource &&
    Object.prototype.hasOwnProperty.call(SOURCE_MAP, explicitSource)
  ) {
    return SOURCE_MAP[explicitSource as keyof typeof SOURCE_MAP];
  }

  const referer = req.headers.get("referer")?.toLowerCase() ?? "";
  if (referer.includes("instagram")) return "source_instagram";
  if (referer.includes("tiktok")) return "source_tiktok";
  if (referer.includes("facebook") || referer.includes("fb.com")) {
    return "source_facebook";
  }
  if (referer.includes("youtube") || referer.includes("youtu.be")) {
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

  const userAgent = req.headers.get("user-agent") ?? "";
  if (AUTOMATED_CLIENT_PATTERN.test(userAgent)) {
    return { track: false, reason: "automated-client" };
  }

  return { track: true };
}

export function getClientAddress(req: Request): string | null {
  const directAddress = req.headers.get("cf-connecting-ip") ??
    req.headers.get("x-real-ip");

  if (directAddress?.trim()) return directAddress.trim();

  const forwardedFor = req.headers.get("x-forwarded-for");
  const firstAddress = forwardedFor?.split(",")[0]?.trim();
  return firstAddress || null;
}

export async function createTrackingFingerprint(
  req: Request,
  linkId: string,
  salt: string | undefined,
): Promise<{ fingerprint: string } | TrackingSkipDecision> {
  if (!salt) {
    return { track: false, reason: "missing-fingerprint-salt" };
  }

  const clientAddress = getClientAddress(req);
  if (!clientAddress) {
    return { track: false, reason: "missing-client-address" };
  }

  const userAgent = req.headers.get("user-agent") ?? "unknown";
  const input = new TextEncoder().encode(
    `${salt}\u0000${linkId}\u0000${clientAddress}\u0000${userAgent}`,
  );
  const digest = await crypto.subtle.digest("SHA-256", input);
  const fingerprint = Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");

  return { fingerprint };
}
