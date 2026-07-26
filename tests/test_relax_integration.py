"""Slow, opt-in end-to-end integration test for structure relaxation.

Fetches two tiny real proteins from RCSB, relaxes them in explicit water via
OpenMM (``relax_spec(..., relax=True)``), and packs the relaxed structures
into a cell via the parsimony CLI (``build_pack``). Needs network, OpenMM,
and ``PARSIMONY_HOME`` (the parsimony CLI) — skipped by default (``-m "not
slow"``) and whenever those prerequisites are missing.
"""
from __future__ import annotations
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow


def test_two_ingredient_relaxed_pack(tmp_path):
    """relax=True on a 2-ingredient spec -> relaxed cached PDBs (+ provenance)
    and a valid pack that meshed the relaxed files."""
    pytest.importorskip("openmm")
    if not os.environ.get("PARSIMONY_HOME"):
        pytest.skip("PARSIMONY_HOME not set (parsimony CLI needed to mesh/pack)")

    from pbg_parsimony import processes as P
    from pbg_parsimony.api import build_pack

    spec = {
        "ingredients": [
            {"id": "crambin", "structure": {"kind": "pdb", "ref": "1CRN"}, "count": 3},
            {"id": "trpcage", "structure": {"kind": "pdb", "ref": "1L2Y"}, "count": 3},
        ],
        "capsule": {"volume_fl": 1.0, "radius_um": 0.4},
    }
    cache = tmp_path / "cache"
    relaxed = P.relax_spec(spec, relax=True, cache_dir=str(cache),
                            relax_cfg={"equil_ps": 5.0, "padding_nm": 1.0, "seed": 0})

    for ing in relaxed["ingredients"]:
        s = ing["structure"]
        assert s["kind"] == "file" and s["ref"].endswith(".pdb")
        p = Path(s["ref"])
        assert p.is_file()
        assert p.with_suffix(".provenance.json").is_file()

    out = tmp_path / "pack"
    res = build_pack(P.spec_to_ingredients(relaxed), P.spec_capsule(relaxed),
                      out_dir=str(out), name="relaxed_cell")
    assert res["n_placed"] > 0
    assert os.path.isfile(res["pack_path"])
