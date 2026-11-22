"""Explicit unbounded-policy compatible guard; original guard remains untouched."""
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import time
from unittest.mock import patch


def load_module(filename):
    spec = importlib.util.spec_from_file_location('root_v3_budget', filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scrub(value, secret=''):
    # Do not inspect, save, or forward private reasoning to evidence consumers.
    if isinstance(value, dict):
        return {key: scrub(item, secret) for key, item in value.items()
                if key not in {'reasoning_content', 'reasoning', 'api_key', 'authorization'}}
    if isinstance(value, (list, tuple)):
        return [scrub(item, secret) for item in value]
    if isinstance(value, str) and secret:
        return value.replace(secret, '[REDACTED]')
    return value


class GuardedHTTP:
    def __init__(self, authorization, *, case_id, evidence_dir):
        self.authorization = Path(authorization)
        self.auth = json.loads(self.authorization.read_text(encoding='utf-8-sig'))
        self.checkout = Path(self.auth['source_root']).resolve()
        adapter = Path(self.auth['unknown_budget_adapter'])
        if hashlib.sha256(adapter.read_bytes()).hexdigest() != self.auth['unknown_budget_adapter_sha256']:
            raise RuntimeError('Accounting adapter changed')
        self.budget_module = load_module(adapter)
        self.budget = self.budget_module.SharedBudget(self.authorization)
        self.case_id = case_id
        self.evidence = Path(evidence_dir)
        self.evidence.mkdir(parents=True, exist_ok=True)
        self.events = []
        self.sent = 0
        self.halted = False
        self.stack = None

    def scene_limit(self):
        caps = self.auth.get('per_scene_caps')
        if not isinstance(caps, dict) or self.case_id not in caps:
            raise RuntimeError('Scene has no root allocation; HTTP forbidden')
        cap = caps[self.case_id]
        if cap is None and self.budget.policy == self.budget_module.UNBOUNDED_POLICY:
            return None
        if type(cap) is not int or cap < 1:
            raise RuntimeError('Scene has no root allocation; HTTP forbidden')
        return cap

    def verify(self):
        if self.halted:
            raise RuntimeError('Guard halted; root accounting review required')
        command = ['git', '-c', 'safe.directory=' + self.checkout.as_posix()]
        actual = subprocess.run(command + ['rev-parse', 'HEAD'], cwd=self.checkout,
                                capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(command + ['status', '--porcelain', '--untracked-files=no'],
                               cwd=self.checkout, capture_output=True, text=True, check=True).stdout.strip()
        if actual != self.auth['frozen_sha'] or dirty:
            raise RuntimeError('Frozen product source changed; HTTP forbidden')
        config = Path(self.auth['profile_config'])
        if hashlib.sha256(config.read_bytes()).hexdigest() != self.auth['profile_config_sha256']:
            raise RuntimeError('Frozen profile configuration changed; HTTP forbidden')
        return self.budget.inspect()

    def stats(self):
        try:
            accounting = self.budget.inspect()
        except self.budget_module.BudgetStop as error:
            # Reading evidence must still work after an unknown paid outcome.
            # This does not reopen the execute gate or certify reported totals.
            data = self.budget_module.load(self.budget.path)
            accounting = {'status': 'BUDGET_HALTED', 'reason': str(error),
                          'unknown_usage': data.get('unknown_usage'),
                          'unverified_reported_totals': data.get('totals'),
                          'budget_id': data.get('budget_id')}
        return {**accounting, 'physical_calls_in_context': self.sent, 'guard_halted': self.halted,
                'model_configuration': {'max_tokens': self.auth['max_output_tokens'],
                                        'temperature': 0, 'top_p': 1, 'automatic_retries': 0}}

    def sanitized_events(self):
        return deepcopy(self.events)

    def save(self, name, value):
        target = self.evidence / name
        with target.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)

    def __enter__(self):
        import httpx
        import openai
        from app.request_budget import BudgetExceeded
        self.verify()
        original = httpx.HTTPTransport.handle_request
        original_client = openai.OpenAI.__init__
        original_transport = httpx.HTTPTransport.__init__
        outer = self

        def no_sdk_retry(client, *args, **kwargs):
            if kwargs.get('max_retries', 0) != 0:
                raise RuntimeError('SDK automatic retries forbidden')
            kwargs['max_retries'] = 0
            return original_client(client, *args, **kwargs)

        def no_transport_retry(transport, *args, **kwargs):
            if kwargs.get('retries', 0) != 0:
                raise RuntimeError('Transport automatic retries forbidden')
            kwargs['retries'] = 0
            return original_transport(transport, *args, **kwargs)

        def blocked_async(*args, **kwargs):
            raise RuntimeError('Unbudgeted async HTTP forbidden')

        def handle(transport, request):
            url = request.url
            if (request.method != 'POST' or url.scheme != 'https' or url.host != 'api.deepseek.com'
                    or url.port not in (None, 443) or url.path not in ('/chat/completions', '/v1/chat/completions')
                    or url.query or getattr(getattr(transport, '_pool', None), '_retries', 0) != 0):
                raise RuntimeError('Non-approved endpoint or retry policy; HTTP forbidden')
            outer.verify()
            cap = outer.scene_limit()
            ledger = outer.budget_module.load(outer.budget.path)
            spent = sum(entry.get('case') == outer.case_id for entry in ledger['entries'])
            if cap is not None and spent >= cap:
                raise BudgetExceeded('request_limit', before_http=True)
            payload = json.loads(request.content)
            if payload.get('model') != 'deepseek-flash':
                raise RuntimeError('Frozen model changed; HTTP forbidden')
            payload.pop('max_completion_tokens', None)
            payload.update(max_tokens=outer.auth['max_output_tokens'], temperature=0, top_p=1, stream=False)
            payload.pop('seed', None)
            body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            credential = request.headers.get('authorization', '').removeprefix('Bearer ')
            identifier = str(time.time_ns())
            outer.save('http-' + identifier + '-request.json', {'at': datetime.now(timezone.utc).isoformat(),
                'case_id': outer.case_id, 'body_sha256': hashlib.sha256(body).hexdigest(),
                'payload': scrub(payload, credential), 'headers_recorded': False})
            captured = {}
            attempted = False

            def send(actual_body):
                nonlocal attempted
                attempted = True
                outer.sent += 1
                actual = httpx.Request(request.method, request.url,
                    headers={key: value for key, value in request.headers.items() if key.lower() != 'content-length'},
                    content=actual_body, extensions=request.extensions)
                response = original(transport, actual)
                response.read()
                data = response.json()
                captured['response'] = response
                # Receipt saving occurs only after durable accounting, below.
                captured['data'] = data
                return response.status_code, data, data.get('id')

            def save_receipt(entry):
                data = scrub(captured.get('data', {}), credential)
                event = {'at': datetime.now(timezone.utc).isoformat(), 'case_id': outer.case_id,
                         'http_status': captured['response'].status_code,
                         'actual_response_model': data.get('model'), 'payload': data, 'budget': entry}
                outer.events.append(event)
                outer.save('http-' + identifier + '-receipt.json', event)

            try:
                outer.budget.execute(body, outer.case_id, send, save_receipt)
            except outer.budget_module.BudgetStop as error:
                if not attempted:
                    raise BudgetExceeded('token_reservation', before_http=True) from None
                # Known/unknown after-send facts stay in the ledger; never resend.
                outer.halted = True
                raise RuntimeError('Physical request stopped; consult durable budget and receipt') from error
            except BaseException:
                if attempted:
                    outer.halted = True
                raise
            return captured['response']

        self.stack = ExitStack()
        self.stack.enter_context(patch.object(openai.OpenAI, '__init__', no_sdk_retry))
        self.stack.enter_context(patch.object(httpx.HTTPTransport, '__init__', no_transport_retry))
        self.stack.enter_context(patch.object(httpx.HTTPTransport, 'handle_request', handle))
        self.stack.enter_context(patch.object(httpx.AsyncHTTPTransport, 'handle_async_request', blocked_async))
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)
