import test from 'node:test';
import assert from 'node:assert/strict';

import {
  commandResponsePayload,
  createConversationController,
  messagePayload,
} from '../static/chat.mjs';

const work = (id = '11111111-1111-4111-8111-111111111111', revision = 2) => ({ id, revision });
const source = {
  kind: 'source', id: '22222222-2222-4222-8222-222222222222', version: 1,
  sha256: 'a'.repeat(64),
};
const target = {
  kind: 'environment', id: '33333333-3333-4333-8333-333333333333', version: 4,
  content_hash: 'b'.repeat(64),
};

test('ordinary messages preserve exact work revision and cannot become command requests', () => {
  assert.deepEqual(messagePayload(work(), '응', [source]), {
    work_revision: 2,
    content: '응',
    semantic_origin: 'clarification',
    referenced_entity_refs: [source],
  });
  for (const origin of ['command_request', 'approval', 'feedback']) {
    assert.throws(() => messagePayload(work(), '응', [], origin));
  }
  assert.throws(() => messagePayload(work(), '   '));
  assert.throws(() => messagePayload(work(), '내용', [{ ...source, actor: 'system' }]));
});

test('explicit chat command response carries every exact binding and no actor claim', () => {
  const payload = commandResponsePayload(work(), {
    commandId: '44444444-4444-4444-8444-444444444444',
    challengeId: '55555555-5555-4555-8555-555555555555',
    token: 'one-time-token',
    content: '적용 확인 01AB23CD',
    exactTargetRef: target,
  });
  assert.deepEqual(payload, {
    work_revision: 2,
    command_id: '44444444-4444-4444-8444-444444444444',
    challenge_id: '55555555-5555-4555-8555-555555555555',
    token: 'one-time-token',
    content: '적용 확인 01AB23CD',
    exact_target_ref: target,
  });
  assert.equal(Object.hasOwn(payload, 'actor'), false);
  assert.equal(Object.hasOwn(payload, 'authority'), false);
});

test('failed send keeps the draft and a successful send clears only that exact draft', async () => {
  const calls = [];
  let fail = true;
  const states = [];
  const controller = createConversationController({
    request: async (path, options = {}) => {
      calls.push([path, options]);
      if (!options.method) return { messages: [] };
      if (fail) throw new Error('offline');
      return { message: {
        id: '66666666-6666-4666-8666-666666666666', sequence: 1,
        content: options.body.content, semantic_origin: 'clarification',
        actor: { kind: 'human' }, referenced_entity_refs: [],
      } };
    },
    onChange: state => states.push(state),
  });

  await controller.setWork(work());
  controller.setDraft('내가 덧붙인 맥락');
  await assert.rejects(controller.send());
  assert.equal(controller.snapshot().draft, '내가 덧붙인 맥락');
  assert.match(controller.snapshot().error, /offline/);

  fail = false;
  await controller.send();
  assert.equal(controller.snapshot().draft, '');
  assert.equal(controller.snapshot().messages[0].content, '내가 덧붙인 맥락');
  assert.equal(calls.at(-1)[0], '/api/v1/works/11111111-1111-4111-8111-111111111111/messages');
  assert.equal(states.at(-1).busy, false);
});

test('late messages from a previous work never replace the selected work', async () => {
  const pending = new Map();
  const request = path => new Promise(resolve => pending.set(path, resolve));
  const controller = createConversationController({ request });
  const first = work('11111111-1111-4111-8111-111111111111');
  const second = work('77777777-7777-4777-8777-777777777777', 5);

  const firstLoad = controller.setWork(first);
  const secondLoad = controller.setWork(second);
  pending.get(`/api/v1/works/${second.id}/messages`)({ messages: [{
    id: '88888888-8888-4888-8888-888888888888', sequence: 1,
    content: '두 번째 업무', semantic_origin: 'clarification', actor: { kind: 'human' },
    referenced_entity_refs: [],
  }] });
  await secondLoad;
  pending.get(`/api/v1/works/${first.id}/messages`)({ messages: [{
    id: '99999999-9999-4999-8999-999999999999', sequence: 1,
    content: '늦은 첫 업무', semantic_origin: 'clarification', actor: { kind: 'human' },
    referenced_entity_refs: [],
  }] });
  await firstLoad;

  assert.equal(controller.snapshot().workId, second.id);
  assert.deepEqual(controller.snapshot().messages.map(item => item.content), ['두 번째 업무']);
});

test('drafts stay separated when moving between works in one app session', async () => {
  const controller = createConversationController({
    request: async () => ({ messages: [] }),
  });
  const first = work();
  const second = work('77777777-7777-4777-8777-777777777777', 1);

  await controller.setWork(first);
  controller.setDraft('첫 업무에서 아직 보내지 않음');
  await controller.setWork(second);
  controller.setDraft('두 번째 업무 초안');
  await controller.setWork(first);

  assert.equal(controller.snapshot().draft, '첫 업무에서 아직 보내지 않음');
});
