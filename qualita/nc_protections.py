from contextlib import contextmanager
from contextvars import ContextVar

_nc_writing = ContextVar("mira_nc_writing", default=False)
_nc_movement = ContextVar("mira_nc_movement", default=None)


@contextmanager
def _nc_write():
    token = _nc_writing.set(True)
    try:
        yield
    finally:
        _nc_writing.reset(token)


@contextmanager
def _movement_for_nc(nc_id, kind):
    token = _nc_movement.set((nc_id, kind))
    try:
        yield
    finally:
        _nc_movement.reset(token)
