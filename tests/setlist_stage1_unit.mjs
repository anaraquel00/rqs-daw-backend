import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const engine = require('../src/lib/setlist-engine');
const {
  enforceSetlistPlanLimit,
  sanitizeUploadName,
} = require('../src/controllers/mix-generator');
const {
  RqsHttpError,
  readAuthenticatedProfileRole,
} = require('../src/lib/supabase-server');

const owned = (name) => `uploads/user-1/setlist/${name}.wav`;
const validBody = (overrides = {}) => ({
  tracks: [owned('track-01'), owned('track-02')],
  vignette: null,
  crossfades: [8],
  curve: 'equal-power',
  loudness: 'off',
  exportName: 'Kris Set 01',
  outputFormat: 'wav',
  ...overrides,
});

function expectCode(callback, code) {
  assert.throws(callback, (error) => {
    assert.equal(error.code, code);
    assert.ok(error.statusCode >= 400);
    return true;
  });
}

async function expectAsyncCode(callback, statusCode, code) {
  await assert.rejects(callback, (error) => {
    assert.ok(error instanceof RqsHttpError);
    assert.equal(error.statusCode, statusCode);
    assert.equal(error.code, code);
    return true;
  });
}
const plan = engine.validateSetlistRequest(validBody());
assert.deepEqual(plan.tracks, [owned('track-01'), owned('track-02')]);
assert.equal(plan.vignette, null);
assert.equal(plan.exportName, 'Kris_Set_01');
assert.equal(plan.outputFormat, 'wav');

expectCode(() => engine.validateSetlistRequest(null), 'INVALID_REQUEST');
expectCode(() => engine.validateSetlistRequest([]), 'INVALID_REQUEST');
expectCode(() => engine.validateSetlistRequest(validBody({ unknown: true })), 'INVALID_REQUEST');
expectCode(() => engine.validateSetlistRequest(validBody({ tracks: [owned('one')] })), 'INVALID_TRACK_COUNT');
expectCode(
  () => engine.validateSetlistRequest(validBody({ tracks: Array.from({ length: engine.MAX_TRACKS + 1 }, (_, i) => owned(`t-${i}`)), crossfades: Array(engine.MAX_TRACKS).fill(1) })),
  'INVALID_TRACK_COUNT',
);
expectCode(() => engine.validateSetlistRequest(validBody({ tracks: [owned('same'), owned('same')] })), 'DUPLICATE_TRACK_KEY');
expectCode(() => engine.validateSetlistRequest(validBody({ tracks: ['', owned('two')] })), 'INVALID_TRACK_KEY');
expectCode(() => engine.validateSetlistRequest(validBody({ tracks: ['uploads/user-1/setlist/track.txt', owned('two')] })), 'INVALID_TRACK_KEY');
expectCode(() => engine.validateSetlistRequest(validBody({ vignette: owned('track-01') })), 'INVALID_VIGNETTE_KEY');
expectCode(() => engine.validateSetlistRequest(validBody({ crossfades: [] })), 'INVALID_CROSSFADE');
expectCode(() => engine.validateSetlistRequest(validBody({ crossfades: [0] })), 'INVALID_CROSSFADE');
expectCode(() => engine.validateSetlistRequest(validBody({ crossfades: [Number.NaN] })), 'INVALID_CROSSFADE');
expectCode(() => engine.validateSetlistRequest(validBody({ crossfades: [Number.POSITIVE_INFINITY] })), 'INVALID_CROSSFADE');
expectCode(() => engine.validateSetlistRequest(validBody({ crossfades: [engine.MAX_CROSSFADE_SECONDS + 0.5] })), 'INVALID_CROSSFADE');
expectCode(() => engine.validateSetlistRequest(validBody({ curve: 'arbitrary-ffmpeg' })), 'UNSUPPORTED_CURVE');
expectCode(() => engine.validateSetlistRequest(validBody({ loudness: 'perceived' })), 'UNSUPPORTED_LOUDNESS_MODE');
expectCode(() => engine.validateSetlistRequest(validBody({ outputFormat: 'mp3' })), 'UNSUPPORTED_OUTPUT_FORMAT');
expectCode(() => engine.validateSetlistRequest(validBody({ exportName: '../' })), 'INVALID_EXPORT_NAME');
expectCode(() => engine.validateSetlistRequest(validBody({ exportName: 'x'.repeat(81) })), 'INVALID_EXPORT_NAME');
expectCode(() => engine.validateObjectSize(0, 'Track'), 'INPUT_SIZE_UNKNOWN');
expectCode(() => engine.validateObjectSize(engine.MAX_INDIVIDUAL_INPUT_BYTES + 1, 'Track'), 'INPUT_TOO_LARGE');
expectCode(() => engine.validateTotalInputSize([engine.MAX_TOTAL_INPUT_BYTES, 1]), 'INPUT_TOO_LARGE');

const probes2 = [
  { duration: 30, sampleRate: 44100, channels: 2, codec: 'pcm_s16le' },
  { duration: 40, sampleRate: 48000, channels: 1, codec: 'pcm_s24le' },
];
const durations = engine.validateProbedInputs(plan, probes2);
assert.equal(durations.outputDuration, 62);
assert.ok(durations.estimatedOutputBytes > 0);
expectCode(
  () => engine.validateProbedInputs(engine.validateSetlistRequest(validBody({ crossfades: [30] })), probes2),
  'INVALID_CROSSFADE',
);
expectCode(
  () => engine.validateProbedInputs(plan, [{ ...probes2[0], duration: engine.MAX_INDIVIDUAL_DURATION_SECONDS + 1 }, probes2[1]]),
  'INPUT_TOO_LONG',
);

const noVignetteFilters = engine.buildFilterPlan(plan, probes2, null);
assert.equal(noVignetteFilters.filters[0].filter, 'acrossfade');
assert.deepEqual(noVignetteFilters.filters[0].inputs, ['0:a', '1:a']);
assert.equal(noVignetteFilters.finalOutput, 'music_xfade_1');
assert.equal(noVignetteFilters.filters.some((filter) => filter.filter === 'amix'), false);

const threePlan = engine.validateSetlistRequest(validBody({
  tracks: [owned('track-01'), owned('track-02'), owned('track-03')],
  crossfades: [5, 6],
}));
const probes3 = [...probes2, { duration: 50, sampleRate: 48000, channels: 2, codec: 'pcm_s24le' }];
const threeFilters = engine.buildFilterPlan(threePlan, probes3, null);
assert.deepEqual(threeFilters.filters[0].inputs, ['0:a', '1:a']);
assert.deepEqual(threeFilters.filters[1].inputs, ['music_xfade_1', '2:a']);

const vignettePlan = engine.validateSetlistRequest(validBody({ vignette: owned('id-drop') }));
const vignetteFilters = engine.buildFilterPlan(
  vignettePlan,
  probes2,
  { duration: 8, sampleRate: 48000, channels: 2, codec: 'pcm_s16le' },
);
assert.equal(vignetteFilters.filters[1].filter, 'adelay');
assert.equal(vignetteFilters.filters[1].inputs, '2:a');
assert.equal(vignetteFilters.filters.at(-1).filter, 'amix');
assert.equal(vignetteFilters.filters.at(-1).options.duration, 'first');

const normalizedPlan = engine.validateSetlistRequest(validBody({ loudness: 'normalize' }));
assert.equal(engine.buildFilterPlan(normalizedPlan, probes2, null).filters.at(-1).filter, 'loudnorm');
assert.equal(sanitizeUploadName('../../Kris Set 01.WAV'), 'Kris_Set_01.wav');
expectCode(() => sanitizeUploadName('unsafe.exe'), 'INVALID_TRACK_KEY');

enforceSetlistPlanLimit(plan, 'free');
enforceSetlistPlanLimit(
  engine.validateSetlistRequest(validBody({
    tracks: [owned('track-01'), owned('track-02'), owned('track-03')],
    crossfades: [2, 2],
  })),
  'free',
);
expectCode(
  () => enforceSetlistPlanLimit(
    engine.validateSetlistRequest(validBody({
      tracks: [owned('track-01'), owned('track-02'), owned('track-03'), owned('track-04')],
      crossfades: [2, 2, 2],
    })),
    'free',
  ),
  'SETLIST_PLAN_LIMIT_EXCEEDED',
);
expectCode(() => enforceSetlistPlanLimit(plan, 'staff'), 'SETLIST_PROFILE_INVALID');

process.env.SUPABASE_URL = 'https://supabase.example.invalid';
process.env.SUPABASE_SECRET_KEY = 'test-server-api-key';
const profileRequest = { headers: { authorization: 'Bearer user-access-token' } };
let observedProfileCall = null;
globalThis.fetch = async (url, options) => {
  observedProfileCall = { url, options };
  return new Response(JSON.stringify([{ role: 'premium' }]), { status: 200 });
};
assert.equal(await readAuthenticatedProfileRole(profileRequest, 'user-1'), 'premium');
assert.match(observedProfileCall.url, /\/rest\/v1\/profiles\?/);
assert.match(observedProfileCall.url, /select=role/);
assert.equal(observedProfileCall.options.headers.Authorization, 'Bearer user-access-token');

for (const profiles of [[], [{ role: 'free' }, { role: 'premium' }], [{ role: 'staff' }]]) {
  globalThis.fetch = async () => new Response(JSON.stringify(profiles), { status: 200 });
  await expectAsyncCode(
    () => readAuthenticatedProfileRole(profileRequest, 'user-1'),
    403,
    'SETLIST_PROFILE_INVALID',
  );
}
globalThis.fetch = async () => { throw new Error('PRIVATE_NETWORK_DETAIL'); };
await expectAsyncCode(
  () => readAuthenticatedProfileRole(profileRequest, 'user-1'),
  502,
  'SETLIST_PROFILE_INVALID',
);
console.log('SETLIST_STAGE1_UNIT=PASS');
