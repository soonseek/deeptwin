"""A deterministic JSONL peer used only by transport integration tests."""

import argparse
import json
import sys
import threading
import time


parser = argparse.ArgumentParser()
parser.add_argument('--account', choices=('none', 'chatgpt', 'apiKey'), default='none')
parser.add_argument('--login', choices=('pending', 'complete', 'failure'), default='pending')
parser.add_argument('--auth-url', default='https://auth.openai.com/authorize?state=fixture-login')
parser.add_argument('--limits', choices=('unknown', 'known'), default='known')
options = parser.parse_args()
write_lock = threading.Lock()


def send(value):
    with write_lock:
        try:
            sys.stdout.write(json.dumps(value, ensure_ascii=False) + '\n')
            sys.stdout.flush()
        except BrokenPipeError:
            pass


def account_value(kind):
    if kind == 'chatgpt':
        return {'type': 'chatgpt', 'email': 'fixture@example.invalid', 'planType': 'plus'}
    if kind == 'apiKey':
        return {'type': 'apiKey'}
    return None


initialized = False
slow = None
approval = None
state = {'account': options.account}


def finish_login():
    if options.login == 'complete':
        state['account'] = 'chatgpt'
        send({'method': 'account/login/completed', 'params': {
            'loginId': 'fixture-login', 'success': True, 'error': None,
        }})
        send({'method': 'account/updated', 'params': {'authMode': 'chatgpt', 'planType': 'plus'}})
    elif options.login == 'failure':
        send({'method': 'account/login/completed', 'params': {
            'loginId': 'fixture-login', 'success': False, 'error': 'fixture login failed',
        }})

for line in sys.stdin:
    message = json.loads(line)
    method = message.get('method')
    request_id = message.get('id')
    params = message.get('params') or {}

    if method == 'initialize':
        expected = {'name': 'deeptwin', 'title': 'DeepTwin', 'version': '0.1.0'}
        if params.get('clientInfo') != expected:
            send({'id': request_id, 'error': {'code': -1, 'message': 'bad client info'}})
        else:
            send({'id': request_id, 'result': {'ready': True}})
        continue
    if method == 'initialized':
        initialized = True
        continue

    if method == 'account/read':
        mode = params.get('test')
        if mode == 'slow':
            slow = request_id
        elif mode == 'fast':
            send({'id': request_id, 'result': {'tag': 'fast'}})
            send({'id': slow, 'result': {'tag': 'slow'}})
            slow = None
        elif mode == 'server-request':
            approval = request_id
            send({'id': 'server-approval', 'method': 'item/commandExecution/requestApproval',
                  'params': {'private': 'must-not-run'}})
        elif mode == 'notifications':
            for index in range(250):
                send({'method': 'account/updated', 'params': {'sequence': index}})
            send({'id': request_id, 'result': {'done': True}})
        elif mode == 'hang':
            time.sleep(1)
            send({'id': request_id, 'result': {'tooLate': True}})
        elif mode == 'exit':
            sys.stderr.write('private stderr token\n')
            sys.stderr.flush()
            raise SystemExit(7)
        elif mode == 'error':
            send({'id': request_id, 'error': {'code': 999, 'message': 'private server payload'}})
        elif mode == 'duplicate':
            send({'id': request_id, 'result': {'delivery': 'first'}})
            send({'id': request_id, 'result': {'delivery': 'late-duplicate'}})
        elif mode == 'invalid-id':
            send({'id': [], 'result': {'private': 'invalid response id'}})
        elif mode == 'oversized':
            send({'method': 'oversized', 'params': {'value': 'x' * (1024 * 1024 + 50)}})
        else:
            send({'method': 'account/updated', 'params': {'authMode': None}})
            if not initialized:
                send({'id': request_id, 'error': {'code': -1, 'message': 'not initialized'}})
            else:
                send({'id': request_id, 'result': {
                    'account': account_value(state['account']), 'requiresOpenaiAuth': True,
                }})
        continue

    if method == 'account/login/start':
        send({'id': request_id, 'result': {
            'type': 'chatgpt', 'loginId': 'fixture-login', 'authUrl': options.auth_url,
        }})
        if options.login != 'pending':
            threading.Timer(0.03, finish_login).start()
        continue

    if method == 'account/login/cancel':
        send({'id': request_id, 'result': {'status': 'canceled'}})
        send({'method': 'account/login/completed', 'params': {
            'loginId': params.get('loginId'), 'success': False, 'error': 'canceled',
        }})
        continue

    if method == 'account/rateLimits/read':
        result = {'rateLimits': None, 'rateLimitsByLimitId': {}}
        if options.limits == 'known':
            result['rateLimits'] = {
                'limitId': 'codex',
                'primary': {'usedPercent': 25, 'windowDurationMins': 300, 'resetsAt': 1893456000},
                'secondary': None,
                'rateLimitReachedType': None,
            }
            result['rateLimitsByLimitId'] = {'codex': result['rateLimits']}
        send({'id': request_id, 'result': result})
        continue

    if method == 'model/list':
        send({'id': request_id, 'result': {'data': [{
            'id': 'gpt-fixture', 'model': 'gpt-fixture',
            'displayName': 'GPT Fixture', 'hidden': False,
            'defaultReasoningEffort': 'medium',
            'supportedReasoningEfforts': [
                {'reasoningEffort': 'low', 'description': '빠르게'},
                {'reasoningEffort': 'medium', 'description': '균형'},
            ],
            'inputModalities': ['text'], 'supportsPersonality': False,
            'isDefault': True,
        }, {
            'id': 'gpt-fixture-deep', 'model': 'gpt-fixture-deep',
            'displayName': 'GPT Fixture Deep', 'hidden': False,
            'defaultReasoningEffort': 'high',
            'supportedReasoningEfforts': [
                {'reasoningEffort': 'high', 'description': '깊게'},
            ],
            'inputModalities': ['text', 'image'], 'supportsPersonality': False,
            'isDefault': False,
        }], 'nextCursor': None}})
        continue

    if method is None and request_id == 'server-approval':
        refused = message.get('error', {}).get('code') == -32601
        send({'id': approval, 'result': {'refused': refused}})
        approval = None
        continue

    send({'id': request_id, 'error': {'code': -32601, 'message': 'unexpected'}})
