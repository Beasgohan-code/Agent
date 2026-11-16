"""Task-local decorative identity; never authorization or a text-redaction filter."""
from contextvars import ContextVar
from functools import wraps

_WORKER = ContextVar('worker_presentation', default=False)


def controller_label(controller, worker):
    return worker if _WORKER.get() else controller


def presentation(handler, *, worker):
    """Keep controller branding out of worker updates and their child tasks."""
    @wraps(handler)
    async def scoped(*args, **kwargs):
        token = _WORKER.set(worker)
        try:
            return await handler(*args, **kwargs)
        finally:
            _WORKER.reset(token)
    return scoped
