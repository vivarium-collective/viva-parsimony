"""Pytest configuration for viva-parsimony.

A handful of test modules drive the external **parsimony** Rust binary (the
packing/relaxation engine). Stock CI — and a plain `pip install` checkout — has
no such binary, so those modules are skipped unless it is available. Set
``PARSIMONY_BIN`` (the binary) or ``PARSIMONY_HOME`` (the parsimony repo with
``target/release/parsimony`` built) to run them. Every test that does *not* need
the engine still runs, so CI meaningfully gates releases.
"""
from viva_parsimony.engine import ParsimonyNotFound, find_parsimony_bin


def _have_parsimony_binary() -> bool:
    try:
        find_parsimony_bin()
        return True
    except ParsimonyNotFound:
        return False


# Test modules that invoke the parsimony engine (and so require the binary).
_ENGINE_TEST_MODULES = [
    "test_relax_cache.py",
    "test_ribosomes.py",
    "test_rnaps.py",
    "test_rnas.py",
]

collect_ignore = [] if _have_parsimony_binary() else list(_ENGINE_TEST_MODULES)
