from pbg_parsimony import processes as P

SPEC = {"ingredients": [
    {"id": "gapdh", "structure": {"kind": "alphafold", "ref": "P0A9B2"}},
    {"id": "ribo", "structure": {"kind": "cif", "ref": "4YBB"}},
    {"id": "blob", "structure": {"kind": "file", "ref": "/tmp/pre.pdb"}}]}


def test_relax_off_passthrough():
    out = P.relax_spec(SPEC, relax=False, cache_dir="/tmp/x", relax_cfg={})
    assert out == SPEC


def test_relax_on_rewrites_to_file_refs(monkeypatch, tmp_path):
    monkeypatch.setattr(P, "get_or_relax",
        lambda ref, cache_dir, relax_cfg, obj_id: tmp_path / f"{obj_id}.pdb")
    out = P.relax_spec(SPEC, relax=True, cache_dir=str(tmp_path), relax_cfg={"seed": 0})
    ing = {i["id"]: i for i in out["ingredients"]}
    assert ing["gapdh"]["structure"] == {"kind": "file", "ref": str(tmp_path / "gapdh.pdb")}
    assert ing["ribo"]["structure"] == {"kind": "file", "ref": str(tmp_path / "ribo.pdb")}
    assert ing["blob"]["structure"] == {"kind": "file", "ref": "/tmp/pre.pdb"}
    assert SPEC["ingredients"][0]["structure"] == {"kind": "alphafold", "ref": "P0A9B2"}  # input unmutated


def test_step_registered():
    from process_bigraph import allocate_core
    core = P.register_parsimony(allocate_core())
    assert "StructureRelaxStep" in core.link_registry  # registered for composite use
