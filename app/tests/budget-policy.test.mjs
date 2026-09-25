// T023: the owner's run-budget panel (budget-policy.mjs) over a fake request.
import test from 'node:test';
import assert from 'node:assert/strict';

import { COMMAND_SCHEMA, LIMITS, MESSAGES, budgetPayload } from '../static/budget-policy.mjs';

const limits = Object.fromEntries(LIMITS.map(([name, , initial]) => [name, String(initial)]));

test('a subscription budget is exact finite limits and never claims an API bill', () => {
  const payload = budgetPayload({ commandId: 'c', mode: 'subscription', limits });
  assert.equal(payload.schema_version, COMMAND_SCHEMA);
  assert.equal(payload.currency, null);
  assert.equal(payload.max_api_microunits, null);
  assert.deepEqual(Object.keys(payload).sort(), ['command_id', 'currency', 'max_api_microunits', 'max_candidates',
    'max_concurrency', 'max_loop_rounds', 'max_model_calls', 'max_node_visits', 'max_output_bytes', 'max_tool_calls',
    'max_wall_seconds', 'profile', 'provider_mode', 'schema_version']);
  for (const [name] of LIMITS) assert.ok(Number.isSafeInteger(payload[name]) && payload[name] >= 1);
});

test('an API budget needs its currency and cap; zero, fractions and unknown modes are refused', () => {
  const api = budgetPayload({ commandId: 'c', mode: 'api', limits, currency: 'USD', microunits: '2000000' });
  assert.equal(api.currency, 'USD');
  assert.equal(api.max_api_microunits, 2_000_000);
  assert.throws(() => budgetPayload({ commandId: 'c', mode: 'api', limits, currency: '', microunits: '1' }), { message: MESSAGES.invalid });
  assert.throws(() => budgetPayload({ commandId: 'c', mode: 'api', limits, currency: 'USD', microunits: '0' }));
  assert.throws(() => budgetPayload({ commandId: 'c', mode: 'subscription', limits: { ...limits, max_model_calls: '0' } }));
  assert.throws(() => budgetPayload({ commandId: 'c', mode: 'subscription', limits: { ...limits, max_tool_calls: '1.5' } }));
  assert.throws(() => budgetPayload({ commandId: 'c', mode: 'other', limits }));
});
