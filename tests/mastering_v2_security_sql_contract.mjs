import fs from 'node:fs';

const sql = fs.readFileSync(
  'supabase/review/mastering_v2_security_migration.sql',
  'utf8',
);

function assertIncludes(value, message) {
  if (!sql.includes(value)) throw new Error(message);
}

assertIncludes(
  'UNEXPECTED_PROFILE_UPDATE_POLICY',
  'Production UPDATE policy fail-closed preflight is missing.',
);
assertIncludes(
  'revoke insert, update, delete, truncate',
  'Browser profile write retirement is missing.',
);
assertIncludes(
  'from anon, authenticated, public',
  'Browser profile revoke matrix is missing.',
);
assertIncludes(
  'drop policy if exists "Permitir que usuários atualizem seus próprios perfis"',
  'Legacy own-profile UPDATE policy retirement is missing.',
);
assertIncludes(
  'grant select\non table public.profiles\nto authenticated',
  'Authenticated profile read preservation is missing.',
);
assertIncludes(
  'create table public.mastering_quota_reservations',
  'Reservation table missing.',
);
assertIncludes(
  'alter table public.mastering_quota_reservations enable row level security',
  'Reservation RLS missing.',
);
assertIncludes(
  'security invoker',
  'Quota functions must be SECURITY INVOKER.',
);
assertIncludes(
  "set search_path = ''",
  'Quota functions must pin an empty search_path.',
);
assertIncludes(
  'for update',
  'Atomic row locking is missing.',
);
assertIncludes(
  'MASTERING_QUOTA_EXCEEDED',
  'Quota exceeded guard is missing.',
);
assertIncludes(
  'from public, anon, authenticated, service_role',
  'Explicit function EXECUTE revoke matrix missing.',
);
assertIncludes(
  'to service_role',
  'service_role grant missing.',
);

if (/security\s+definer/i.test(sql)) {
  throw new Error('SECURITY DEFINER is not permitted in this migration.');
}

console.log('MASTERING_V2_SECURITY_SQL_CONTRACT: PASS');
