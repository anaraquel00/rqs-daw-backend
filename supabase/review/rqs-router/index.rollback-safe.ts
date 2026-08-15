import { createClient } from "npm:@supabase/supabase-js@2";

function jsonResponse(body: Record<string, unknown>, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
    },
  });
}

function redirectResponse(targetUrl: string): Response {
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

Deno.serve(async (req: Request): Promise<Response> => {
  const url = new URL(req.url);
  const pathParts = url.pathname.split("/").filter(Boolean);
  const slug = pathParts[pathParts.length - 1];

  if (!slug || slug === "rqs-router") {
    return jsonResponse(
      { status: "RQS Uplink Router Online", tracking: "disabled" },
      200,
    );
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
    console.error("[RQS UPLINK] rollbackConfigurationError", { slug });
    return jsonResponse({ error: "Router Configuration Error" }, 500);
  }

  const supabase = createClient(supabaseUrl, serviceRoleKey, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
  const { data, error } = await supabase
    .from("rqs_uplinks")
    .select("id, target_url")
    .eq("custom_slug", slug)
    .single();

  if (error || !data) {
    console.error("[RQS UPLINK] rollbackLookupError", {
      slug,
      code: error?.code,
      message: error?.message ?? "UPLINK_NOT_FOUND",
    });
    return jsonResponse({ error: "Uplink Target Not Found" }, 404);
  }

  try {
    const protocol = new URL(data.target_url).protocol;
    if (protocol !== "https:" && protocol !== "http:") throw new Error();
  } catch {
    console.error("[RQS UPLINK] rollbackInvalidTarget", { slug, id: data.id });
    return jsonResponse({ error: "Invalid Uplink Target" }, 500);
  }

  console.log("[RQS UPLINK] rollbackRedirect", { slug, id: data.id });
  return redirectResponse(data.target_url);
});
