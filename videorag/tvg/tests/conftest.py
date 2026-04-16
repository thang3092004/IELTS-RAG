"""
conftest.py for videorag.tvg tests.

Stubs heavy top-level modules not needed for TVG unit tests so that
importing videorag.tvg.* does not require transformers/tiktoken.
"""
import sys
from unittest.mock import MagicMock

# Stub heavy packages only if not installed
for _mod in [
    "transformers",
    "tiktoken",
    "torch",
    "torch.nn",
    "torch.nn.functional",
]:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
