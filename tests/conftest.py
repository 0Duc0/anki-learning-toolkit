import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# tests/legacy holds stand-alone scripts that each replace aqt.mw; they run in their own
# process through test_legacy_suites.py instead of being collected here.
collect_ignore = ["legacy"]
