"""Typed pre-HTTP budget refusals, distinct from provider/network failures."""


class BudgetExceeded(RuntimeError):
    def __init__(self, reason, *, remaining_tokens=None, reserved_tokens=None,
                 physical_requests=None, before_http=True):
        if reason not in {'request_limit', 'token_reservation', 'usage_unknown'}:
            raise ValueError('invalid budget reason')
        self.reason = reason
        self.remaining_tokens = remaining_tokens
        self.reserved_tokens = reserved_tokens
        self.physical_requests = physical_requests
        self.before_http = before_http is True
        super().__init__('模型请求预算不足；未确认业务完成。')

    def metadata(self):
        values = {'budget_reason': self.reason, 'before_http': self.before_http}
        for field in ('remaining_tokens', 'reserved_tokens', 'physical_requests'):
            value = getattr(self, field)
            if type(value) is int and value >= 0:
                values[field] = value
        return values


def budget_cause(error):
    """The SDK may wrap a transport guard in APIConnectionError; use types only."""
    seen, pending = set(), [error]
    while pending and len(seen) < 12:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        if isinstance(item, BudgetExceeded):
            return item
        pending.extend(v for v in (getattr(item, '__cause__', None), getattr(item, '__context__', None))
                       if isinstance(v, BaseException))
    return None
