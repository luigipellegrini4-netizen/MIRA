"""Solo controlli statici/test senza DB: NON configura un database alternativo."""
import os

os.environ.setdefault("MIRA_SECRET_KEY", "mira-static-checks-only-never-use-for-serving")
from .settings import *  # noqa: F403,E402

DATABASES = {"default": {"ENGINE": "django.db.backends.dummy"}}
