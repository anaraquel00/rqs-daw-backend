-- =========================================================
-- RQS UPLINK TRACKING - ROLLBACK
-- REVIEW ONLY
-- =========================================================

begin;

revoke execute
on function public.increment_uplink_clicks(uuid, text)
from public, anon, authenticated, service_role;

drop function if exists
public.increment_uplink_clicks(uuid, text);

-- A função antiga NÃO deve ser reconstruída manualmente aqui.
-- Restaurar a definição + ACL exatas capturadas no backup
-- anterior à migração.

commit;