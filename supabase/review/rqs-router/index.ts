import { createClient } from "npm:@supabase/supabase-js@2";

const SOURCE_MAP: Record<string, string> = {
  instagram: "source_instagram",
  tiktok: "source_tiktok",
  facebook: "source_facebook",
  youtube: "source_youtube",
  direct: "source_direct",
};

function detectSource(req: Request, url: URL): string {
  // 1. Explicit source (?src=instagram)
  const src = url.searchParams
    .get("src")
    ?.trim()
    .toLowerCase();

  if (src && SOURCE_MAP[src]) {
    return SOURCE_MAP[src];
  }

  // 2. Referer fallback
  const referer =
    req.headers.get("referer")?.toLowerCase() ?? "";

  if (referer.includes("instagram")) {
    return "source_instagram";
  }

  if (referer.includes("tiktok")) {
    return "source_tiktok";
  }

  if (
    referer.includes("facebook") ||
    referer.includes("fb.com")
  ) {
    return "source_facebook";
  }

  if (
    referer.includes("youtube") ||
    referer.includes("youtu.be")
  ) {
    return "source_youtube";
  }

  // 3. User-Agent fallback
  const userAgent =
    req.headers.get("user-agent")?.toLowerCase() ?? "";

  if (userAgent.includes("instagram")) {
    return "source_instagram";
  }

  if (userAgent.includes("tiktok")) {
    return "source_tiktok";
  }

  if (userAgent.includes("facebook")) {
    return "source_facebook";
  }

  if (userAgent.includes("youtube")) {
    return "source_youtube";
  }

  // 4. Unknown source
  return "source_direct";
}

Deno.serve(async (req: Request): Promise<Response> => {
  const url = new URL(req.url);

  const pathParts = url.pathname
    .split("/")
    .filter(Boolean);

  const slug =
    pathParts[pathParts.length - 1];

  // ---------------------------------------------------------
  // HEALTH CHECK
  // ---------------------------------------------------------

  if (!slug || slug === "rqs-router") {
    return new Response(
      JSON.stringify({
        status: "RQS Uplink Router Online",
      }),
      {
        status: 200,
        headers: {
          "Content-Type": "application/json",
        },
      },
    );
  }

  // ---------------------------------------------------------
  // ENVIRONMENT
  // ---------------------------------------------------------

  const supabaseUrl =
    Deno.env.get("SUPABASE_URL");

  const serviceRoleKey =
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");

  if (!supabaseUrl || !serviceRoleKey) {
    console.error(
      "[RQS UPLINK] configurationError",
      {
        slug,
        missingSupabaseUrl: !supabaseUrl,
        missingServiceRoleKey: !serviceRoleKey,
      },
    );

    return new Response(
      JSON.stringify({
        error: "Router Configuration Error",
      }),
      {
        status: 500,
        headers: {
          "Content-Type": "application/json",
        },
      },
    );
  }

  const supabase = createClient(
    supabaseUrl,
    serviceRoleKey,
  );

  console.log(
    "[RQS UPLINK] request",
    { slug },
  );

  // ---------------------------------------------------------
  // LOOKUP
  // ---------------------------------------------------------

  const {
    data,
    error: lookupError,
  } = await supabase
    .from("rqs_uplinks")
    .select("id, target_url")
    .eq("custom_slug", slug)
    .single();

  if (lookupError || !data) {
    console.error(
      "[RQS UPLINK] lookupError",
      {
        slug,
        message:
          lookupError?.message ??
          "UPLINK_NOT_FOUND",
      },
    );

    return new Response(
      JSON.stringify({
        error: "Uplink Target Not Found",
      }),
      {
        status: 404,
        headers: {
          "Content-Type": "application/json",
        },
      },
    );
  }

  // ---------------------------------------------------------
  // SOURCE DETECTION
  // ---------------------------------------------------------

  const sourceCol =
    detectSource(req, url);

  // ---------------------------------------------------------
  // TRACKING ATTEMPT
  // ---------------------------------------------------------

  console.log(
    "[RQS UPLINK] trackingAttempt",
    {
      slug,
      id: data.id,
      source: sourceCol,
    },
  );

  // ---------------------------------------------------------
  // ATOMIC TRACKING RPC
  // ---------------------------------------------------------

  const {
    error: trackingError,
  } = await supabase.rpc(
    "increment_uplink_clicks",
    {
      link_id: data.id,
      source_col: sourceCol,
    },
  );

  // ---------------------------------------------------------
  // TRACKING RESULT
  // ---------------------------------------------------------

  if (trackingError) {
    console.error(
      "[RQS UPLINK] trackingError",
      {
        slug,
        id: data.id,
        source: sourceCol,
        message: trackingError.message,
      },
    );
  } else {
    console.log(
      "[RQS UPLINK] trackingSuccess",
      {
        slug,
        id: data.id,
        source: sourceCol,
      },
    );
  }

  // ---------------------------------------------------------
  // REDIRECT MUST SURVIVE TRACKING FAILURE
  // ---------------------------------------------------------

  return Response.redirect(
    data.target_url,
    302,
  );
});