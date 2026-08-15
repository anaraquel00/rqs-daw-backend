import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

serve(async (req) => {
  const url = new URL(req.url);
  const pathParts = url.pathname.split('/').filter(Boolean);
  const slug = pathParts[pathParts.length - 1];

  if (!slug || slug === 'rqs-router') {
    return new Response(JSON.stringify({ status: "RQS Uplink Router Online" }), {
      headers: { "Content-Type": "application/json" },
      status: 200,
    });
  }

  const supabaseUrl = Deno.env.get('SUPABASE_URL')!;
  const supabaseKey = Deno.env.get('SUPABASE_ANON_KEY')!;
  const supabase = createClient(supabaseUrl, supabaseKey);

  const { data, error } = await supabase
    .from('rqs_uplinks')
    .select('id, target_url, clicks')
    .eq('custom_slug', slug)
    .single();

  if (error || !data) {
    return new Response(JSON.stringify({ error: "Uplink Target Not Found" }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  }

  await supabase
    .from('rqs_uplinks')
    .update({ clicks: (data.clicks || 0) + 1 })
    .eq('id', data.id);

  return Response.redirect(data.target_url, 302);
});