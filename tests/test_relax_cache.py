"""Tests for the param-keyed relaxed-structure cache (no network, no OpenMM)."""
import json
from pathlib import Path

from pbg_parsimony import relax_cache as rc

CFG = {"forcefield": ["amber14-all.xml", "amber14/tip3pfb.xml"], "water_model": "tip3p",
       "padding_nm": 1.0, "ionic_strength_M": 0.15, "temperature_K": 300.0,
       "timestep_fs": 2.0, "equil_ps": 200.0, "seed": 0}


def _tiny_pdb(tmp_path) -> Path:
    """Write a minimal valid single-atom PDB and return its path."""
    p = tmp_path / "tiny.pdb"
    p.write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n"
        "END\n"
    )
    return p


def test_hash_stable_and_param_sensitive():
    ref = {"kind": "alphafold", "ref": "P0A6F5"}
    h1 = rc.relax_params_hash(ref, CFG, model_version="v4")
    h2 = rc.relax_params_hash(ref, CFG, model_version="v4")
    h3 = rc.relax_params_hash(ref, {**CFG, "seed": 1}, model_version="v4")
    h4 = rc.relax_params_hash(ref, CFG, model_version="v6")
    assert h1 == h2 and h1 != h3 and h1 != h4


def test_get_or_relax_cache_hit_skips_relax(tmp_path, monkeypatch):
    ref = {"kind": "file", "ref": str(_tiny_pdb(tmp_path))}
    calls = {"n": 0}
    monkeypatch.setattr(rc, "relax_in_water", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1) or {"seed": 0})
    monkeypatch.setattr(rc, "fetch", lambda ref, cd, slug=None: _tiny_pdb(tmp_path))
    p1 = rc.get_or_relax(ref, tmp_path / "cache", CFG, obj_id="x")   # miss → relaxes + writes provenance
    p2 = rc.get_or_relax(ref, tmp_path / "cache", CFG, obj_id="x")   # hit → no re-relax
    assert p1 == p2 and calls["n"] == 1
    assert (p1.with_suffix(".provenance.json")).is_file()


def test_relax_error_falls_back_to_raw(tmp_path, monkeypatch):
    from pbg_openmm.relax import RelaxError
    raw = _tiny_pdb(tmp_path)
    monkeypatch.setattr(rc, "fetch", lambda *a, **k: raw)
    monkeypatch.setattr(rc, "relax_in_water", lambda *a, **k: (_ for _ in ()).throw(RelaxError("boom")))
    out = rc.get_or_relax({"kind": "file", "ref": str(raw)}, tmp_path / "cache", CFG, obj_id="x")
    assert out == raw   # graceful fallback to the raw structure
