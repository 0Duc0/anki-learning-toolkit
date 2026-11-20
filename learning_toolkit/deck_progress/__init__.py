"""Independent, display-only progress counters for Anki Desktop."""

import sys
import traceback

try:
    from .controller import register

    register()
except Exception:
    # An incompatible UI API must not interrupt collection opening or review.
    print("[Deck Progress] Could not initialize the display.", file=sys.stderr)
    traceback.print_exc()
