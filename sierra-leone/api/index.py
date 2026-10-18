"""Vercel entry point: every /api/* request runs the CRM's API handler."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from slcrm.server import Handler  # noqa: E402


class handler(Handler):  # Vercel's Python runtime looks for a class named `handler`
    pass
