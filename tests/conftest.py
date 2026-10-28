"""Skip tests that shell out to the Rust ``parsimony`` binary when it isn't built (e.g. CI)."""
import pytest

from viva_parsimony.engine import ParsimonyNotFound, find_parsimony_bin

# Test modules whose tests call build_pack(), which needs the binary.
_NEEDS_BINARY = {"test_ribosomes.py", "test_rnaps.py", "test_rnas.py"}


def _parsimony_available() -> bool:
    try:
        find_parsimony_bin()
        return True
    except ParsimonyNotFound:
        return False


def pytest_collection_modifyitems(config, items):
    if _parsimony_available():
        return
    skip = pytest.mark.skip(reason="parsimony binary not built in CI")
    for item in items:
        if item.path.name in _NEEDS_BINARY:
            item.add_marker(skip)
