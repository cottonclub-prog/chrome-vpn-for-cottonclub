"""Run tests against this independent helper, not the original desktop sources."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
raise SystemExit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
