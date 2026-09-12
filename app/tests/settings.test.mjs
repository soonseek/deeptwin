import test from 'node:test';
import assert from 'node:assert/strict';

import {
  catalogURL,
  connectionOptions,
  modelSelectionPayload,
  usagePolicyPayload,
} from '../static/settings.mjs';

const providers = [{
  id: 'codex', default_mode: 'subscription', modes: [
    { id: 'subscription', label: 'ChatGPT 구독', billing: 'subscription', auth_mode: 'chatgpt' },
    { id: 'api', label: '별도 API', billing: 'api', auth_mode: 'api_key' },
  ],
}, {
  id: 'claude', default_mode: 'api', modes: [
    { id: 'api', label: 'Claude API', billing: 'api', auth_mode: 'api_key' },
  ],
}];

test('provider modes preserve distinct billing paths and never invent Claude subscription', () => {
  const options = connectionOptions(providers);
  assert.deepEqual(options.map(item => [item.provider, item.mode]), [
    ['codex', 'subscription'], ['claude', 'api'], ['codex', 'api'],
  ]);
  assert.equal(options.some(item => item.provider === 'claude' && item.mode === 'subscription'), false);
  assert.equal(options.find(item => item.provider === 'codex' && item.mode === 'subscription').billing, 'subscription');
  assert.equal(options.find(item => item.provider === 'codex' && item.mode === 'api').billing, 'api');
});

test('catalog URL binds both provider and mode without accepting path injection', () => {
  assert.equal(catalogURL('codex', 'subscription'), '/api/model-catalogs/codex?mode=subscription');
  assert.equal(catalogURL('claude', 'api', { refresh: true }), '/api/model-catalogs/claude/refresh?mode=api');
  for (const [provider, mode] of [['claude', 'subscription'], ['../x', 'api'], ['codex', 'other']]) {
    assert.throws(() => catalogURL(provider, mode));
  }
});

test('model selection payload keeps the literal catalog path and optional thinking', () => {
  assert.deepEqual(modelSelectionPayload({
    provider: 'claude', mode: 'api', model: 'claude-account-model', effort: 'high',
    thinking: 'adaptive', catalog_id: 'catalog-123',
  }), {
    provider: 'claude', mode: 'api', model: 'claude-account-model', effort: 'high',
    thinking: 'adaptive', catalog_id: 'catalog-123',
  });
  assert.throws(() => modelSelectionPayload({
    provider: 'claude', mode: 'subscription', model: 'fake', effort: 'high', catalog_id: 'catalog-1',
  }));
});

test('usage policy remains finite and API mode requires an explicit positive money cap', () => {
  const subscription = usagePolicyPayload({
    provider_mode: 'subscription', max_model_calls: 64, max_tool_calls: 128,
    max_wall_seconds: 1200, max_output_bytes: 67108864,
  });
  assert.equal(subscription.currency, null);
  assert.equal(subscription.max_api_microunits, null);
  const api = usagePolicyPayload({
    provider_mode: 'api', max_model_calls: 64, max_tool_calls: 128,
    max_wall_seconds: 1200, max_output_bytes: 67108864,
    currency: 'USD', max_api_microunits: 5_000_000,
  });
  assert.equal(api.currency, 'USD');
  assert.equal(api.max_api_microunits, 5_000_000);
  for (const draft of [
    { ...api, max_api_microunits: 0 },
    { ...api, currency: null },
    { ...subscription, max_model_calls: Infinity },
    { ...subscription, max_wall_seconds: 0 },
  ]) assert.throws(() => usagePolicyPayload(draft));
});
