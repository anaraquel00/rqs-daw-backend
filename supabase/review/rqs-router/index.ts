import { createClient } from "npm:@supabase/supabase-js@2";
import {
  createTrackingFingerprint,
  detectSource,
  redirectResponse,
  trackingDecision,
} from "./tracking.ts";

function jsonResponse(body: Record<string, unknown>, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
    },
  });
}

function getSlug(url: URL): string | null {
  const pathParts = url.pathname.split("/").filter(Boolean);
  const slug = pathParts[pathParts.length - 1];
  return !slug || slug === "rqs-router" ? null : slug;
}

function isAllowedTarget(targetUrl: string): boolean {
  try {
    const protocol = new URL(targetUrl).protocol;
    return protocol === "https:" || protocol === "http:";
  } catch {
    return false;
  }
}

export async function handleRequest(req: Request): Promise<Response> {
  const url = new URL(req.url);
  const slug = getSlug(url);

  if (!slug) {
    return jsonResponse({ status: "RQS Uplink Router Online" }, 200);
  }

  if (req.method !== "GET" && req.method !== "HEAD") {
    return new Response(null, {
      status: 405,
      headers: { Allow: "GET, HEAD" },
    });
  }

  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");

  if (!supabaseUrl || !serviceRoleKey) {
    console.error("[RQS UPLINK] configurationError", {
      slug,
      missingSupabaseUrl: !supabaseUrl,
      missingServiceRoleKey: !serviceRoleKey,
    });
    return jsonResponse({ error: "Router Configuration Error" }, 500);
  }

  const supabase = createClient(supabaseUrl, serviceRoleKey, {
    auth: { autoRefreshToken: false, persistSession: false },
  });

  console.log("[RQS UPLINK] request", { slug, method: req.method });

  const { data, error: lookupError } = await supabase
    .from("rqs_uplinks")
    .select("id, target_url")
    .eq("custom_slug", slug)
    .single();

  if (lookupError || !data) {
    console.error("[RQS UPLINK] lookupError", {
      slug,
      code: lookupError?.code,
      message: lookupError?.message ?? "UPLINK_NOT_FOUND",
    });
    return jsonResponse({ error: "Uplink Target Not Found" }, 404);
  }

  if (!isAllowedTarget(data.target_url)) {
    console.error("[RQS UPLINK] invalidTarget", { slug, id: data.id });
    return jsonResponse({ error: "Invalid Uplink Target" }, 500);
  }

  const decision = trackingDecision(req);
  if (!decision.track) {
    console.log("[RQS UPLINK] trackingSkipped", {
      slug,
      id: data.id,
      reason: decision.reason,
    });
    return redirectResponse(data.target_url);
  }

  const fingerprintResult = await createTrackingFingerprint(
    req,
    data.id,
    Deno.env.get("UPLINK_TRACKING_SALT"),
  );

  if (!("fingerprint" in fingerprintResult)) {
    console.error("[RQS UPLINK] trackingSkipped", {
      slug,
      id: data.id,
      reason: fingerprintResult.reason,
    });
    return redirectResponse(data.target_url);
  }

  const sourceCol = detectSource(req, url);
  console.log("[RQS UPLINK] trackingAttempt", {
    slug,
    id: data.id,
    source: sourceCol,
  });

  const { data: tracked, error: trackingError } = await supabase.rpc(
    "increment_uplink_clicks",
    {
      link_id: data.id,
      source_col: sourceCol,
      request_fingerprint: fingerprintResult.fingerprint,
    },
  );

  if (trackingError) {
    console.error("[RQS UPLINK] trackingError", {
      slug,
      id: data.id,
      source: sourceCol,
      code: trackingError.code,
      message: trackingError.message,
    });
  } else if (tracked === false) {
    console.log("[RQS UPLINK] trackingDeduplicated", {
      slug,
      id: data.id,
      source: sourceCol,
    });
  } else {
    console.log("[RQS UPLINK] trackingSuccess", {
      slug,
      id: data.id,
      source: sourceCol,
    });
  }

  return redirectResponse(data.target_url);
}

if (import.meta.main) {
  Deno.serve(handleRequest);
}
