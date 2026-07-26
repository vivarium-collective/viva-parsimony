# All-atom solvated structure relaxation (Part A) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Opt-in, reproducible all-atom solvated relaxation of fetched AlphaFold/PDB structures so their disordered tails compact before parsimony meshes/packs them.

**Architecture:** `pbg-openmm` gains `relax_in_water` (add water + ions → minimize → short NVT → strip solvent → relaxed PDB). `pbg-parsimony` gains a param-keyed relaxed-structure cache + an upstream `StructureRelaxStep` that rewrites each ingredient's `StructureRef` to the cached relaxed file. Existing mesher/packer consume the relaxed PDBs unchanged.

**Tech Stack:** Python 3, OpenMM (AMBER14/TIP3P force fields), `process_bigraph.Step`, pytest.

## Global Constraints — READ FIRST

- **Two repos.** Tasks 1 = `pbg-openmm`; Tasks 2–4 = `pbg-parsimony` (worktree `/Users/eranagmon/code/pbg-parsimony-relax`). Each task states its repo + branch. Make a feature branch in `pbg-openmm` (`feat/solvated-relax`) for Task 1.
- **Opt-in:** relaxation only runs under `relax=True`; default off → existing packs byte-identical.
- **Best-effort / never break a pack:** any OpenMM/forcefield/network failure for one structure logs + falls back to the raw fetched structure; it never raises out of a pack.
- **Reproducibility is the point:** the relaxed-structure cache key MUST include every input that changes the result (source, id, resolved AlphaFold model version, forcefield, water_model, padding, ionic_strength, temperature, timestep, equil_ps, seed, openmm_version); a `provenance.json` sidecar records them.
- **Real-OpenMM tests are `@pytest.mark.slow`** (register the marker); the default suite must not run OpenMM. Fast tests mock `relax_in_water`/`fetch`.
- Test env: `pbg-openmm` needs OpenMM importable (`python -c "import openmm"`); if the AMBER14/TIP3P force fields aren't bundled, note it and keep the slow test skippable.
- Follow each repo's existing module/test layout; return provenance dicts (not side-effect-only).

---

### Task 1: `pbg-openmm` — `relax_in_water` + `SolvatedRelaxStep`

**Repo:** `pbg-openmm` (branch `feat/solvated-relax`).
**Files:** Create `pbg_openmm/relax.py`; Test `tests/test_relax.py`.

**Interfaces:**
- Produces: `relax_in_water(pdb_in, pdb_out, *, forcefield=("amber14-all.xml","amber14/tip3pfb.xml"), water_model="tip3p", padding_nm=1.0, ionic_strength_M=0.15, temperature_K=300.0, timestep_fs=2.0, equil_ps=200.0, minimize=True, seed=0) -> dict` (returns the provenance dict incl. `openmm_version`; writes the relaxed protein-only PDB to `pdb_out`; raises `RelaxError` on OpenMM/forcefield failure). Plus `class RelaxError(Exception)` and a thin `SolvatedRelaxStep(Step)` (input `structure_path`; config = the params; output `relaxed_path`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_relax.py
import pytest
from pbg_openmm import relax as R

def test_provenance_shape_without_running(monkeypatch, tmp_path):
    # relax_in_water assembles a provenance dict of all params + openmm version;
    # stub the actual OpenMM run so this stays fast.
    monkeypatch.setattr(R, "_run_solvated_relax", lambda *a, **k: None)  # writes nothing
    (tmp_path/"in.pdb").write_text("REMARK stub\nEND\n")
    prov = R.relax_in_water(str(tmp_path/"in.pdb"), str(tmp_path/"out.pdb"),
                            seed=7, equil_ps=50.0)
    for k in ("forcefield","water_model","padding_nm","ionic_strength_M",
              "temperature_K","timestep_fs","equil_ps","seed","openmm_version"):
        assert k in prov
    assert prov["seed"] == 7 and prov["equil_ps"] == 50.0

@pytest.mark.slow
def test_relax_in_water_real_tiny(tmp_path):
    # a tiny structure, few steps, small box → a valid relaxed PDB (protein atoms
    # present, waters stripped). Skips cleanly if OpenMM/forcefields unavailable.
    openmm = pytest.importorskip("openmm")
    src = _write_tiny_peptide_pdb(tmp_path)   # helper: a few-residue peptide
    out = tmp_path/"relaxed.pdb"
    R.relax_in_water(str(src), str(out), equil_ps=2.0, padding_nm=0.6, seed=1)
    txt = out.read_text()
    assert out.is_file() and "ATOM" in txt and "HOH" not in txt
```

- [ ] **Step 2: Run — verify fail.** `python -m pytest tests/test_relax.py -v` (from pbg-openmm) → FAIL (module/func undefined).

- [ ] **Step 3: Implement `relax.py`**
- `relax_in_water` builds the provenance dict (all params + `openmm.version.version`), then calls `_run_solvated_relax(...)` (factored so tests can stub it): `PDBFile(pdb_in)` → `Modeller` → `addHydrogens(ForceField(*forcefield))` → `addSolvent(ForceField, model=water_model, padding=padding_nm*nm, ionicStrength=ionic_strength_M*molar, neutralize=True)` → `createSystem(nonbondedMethod=PME, constraints=HBonds)` → `LangevinMiddleIntegrator(temperature_K*kelvin, 1/ps, timestep_fs*fs)`; `integrator.setRandomNumberSeed(seed)` → `Simulation` → `minimizeEnergy()` (if minimize) → `context.setVelocitiesToTemperature(temperature, seed)` → `step(int(equil_ps*1000/timestep_fs))` → take final positions, select protein atoms (residue not in water/ion set) → `PDBFile.writeFile(protein_topology, protein_positions, out)`. Wrap OpenMM calls; on failure raise `RelaxError`.
- `SolvatedRelaxStep(Step)`: `update()` calls `relax_in_water(state["structure_path"], <out>, **config)`, returns `{"relaxed_path": out}`. Mirror an existing pbg-openmm Step's `config_schema`/`inputs`/`outputs` style.

- [ ] **Step 4: Run — verify pass.** Fast test PASSES; slow test PASSES (or skips) with OpenMM present.

- [ ] **Step 5: Commit.** `git commit -m "feat: all-atom solvated relax_in_water + SolvatedRelaxStep"`

---

### Task 2: `pbg-parsimony` — relaxed-structure cache

**Repo:** `pbg-parsimony` (worktree, branch `feat/structure-relaxation`).
**Files:** Create `pbg_parsimony/relax_cache.py`; Test `tests/test_relax_cache.py`.

**Interfaces:**
- Consumes: `structures.fetch`, `structures.alphafold_pdb_url` (for the model version); `pbg_openmm.relax.relax_in_water`.
- Produces: `relax_params_hash(ref: dict, relax_cfg: dict, *, model_version=None) -> str`; `relaxed_path(cache_dir, obj_id, phash) -> Path` (`<cache>/relaxed/<obj_id>__<phash>.pdb`); `get_or_relax(ref: dict, cache_dir, relax_cfg, *, obj_id) -> Path` (cache hit → return; miss → `fetch` → `relax_in_water` → write cache + `<...>.provenance.json`; on `RelaxError` → return the raw fetched path, log).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_relax_cache.py
import json
from pbg_parsimony import relax_cache as rc

CFG = {"forcefield": ["amber14-all.xml","amber14/tip3pfb.xml"], "water_model":"tip3p",
       "padding_nm":1.0,"ionic_strength_M":0.15,"temperature_K":300.0,
       "timestep_fs":2.0,"equil_ps":200.0,"seed":0}

def test_hash_stable_and_param_sensitive():
    ref = {"kind":"alphafold","ref":"P0A6F5"}
    h1 = rc.relax_params_hash(ref, CFG, model_version="v4")
    h2 = rc.relax_params_hash(ref, CFG, model_version="v4")
    h3 = rc.relax_params_hash(ref, {**CFG, "seed": 1}, model_version="v4")
    h4 = rc.relax_params_hash(ref, CFG, model_version="v6")
    assert h1 == h2 and h1 != h3 and h1 != h4

def test_get_or_relax_cache_hit_skips_relax(tmp_path, monkeypatch):
    ref = {"kind":"file","ref": str(_tiny_pdb(tmp_path))}
    calls = {"n":0}
    monkeypatch.setattr(rc, "relax_in_water", lambda *a, **k: calls.__setitem__("n", calls["n"]+1) or {"seed":0})
    monkeypatch.setattr(rc, "fetch", lambda ref, cd, slug=None: _tiny_pdb(tmp_path))
    p1 = rc.get_or_relax(ref, tmp_path/"cache", CFG, obj_id="x")   # miss → relaxes + writes provenance
    p2 = rc.get_or_relax(ref, tmp_path/"cache", CFG, obj_id="x")   # hit → no re-relax
    assert p1 == p2 and calls["n"] == 1
    assert (p1.with_suffix(".provenance.json")).is_file()

def test_relax_error_falls_back_to_raw(tmp_path, monkeypatch):
    from pbg_openmm.relax import RelaxError
    raw = _tiny_pdb(tmp_path)
    monkeypatch.setattr(rc, "fetch", lambda *a, **k: raw)
    monkeypatch.setattr(rc, "relax_in_water", lambda *a, **k: (_ for _ in ()).throw(RelaxError("boom")))
    out = rc.get_or_relax({"kind":"file","ref":str(raw)}, tmp_path/"cache", CFG, obj_id="x")
    assert out == raw   # graceful fallback to the raw structure
```

- [ ] **Step 2: Run — verify fail.**

- [ ] **Step 3: Implement.** `relax_params_hash` = `sha1` over a canonical JSON of `{source: ref["kind"], id: ref["ref"], model_version, **relax_cfg, openmm_version}`. `get_or_relax`: compute `phash` (resolve AlphaFold `model_version` from the pdbUrl basename, best-effort → None), `target = relaxed_path(...)`; if it exists → return it; else `src = fetch(ref_obj, cache_dir/"structures", slug=obj_id)`; `try: prov = relax_in_water(str(src), str(target), **relax_cfg); write target.with_suffix(".provenance.json") = {source,id,model_version,**prov,utc}` `except RelaxError: log; return src`. Import `relax_in_water`/`fetch` as module-level names (tests monkeypatch them).

- [ ] **Step 4: Run — verify pass.**

- [ ] **Step 5: Commit.** `git commit -m "feat: param-keyed relaxed-structure cache (get_or_relax + provenance)"`

---

### Task 3: `pbg-parsimony` — `StructureRelaxStep` + provenance in the pack

**Repo:** `pbg-parsimony` (worktree).
**Files:** Modify `pbg_parsimony/processes.py` (new Step + register); Modify `pbg_parsimony/api.py` (`_public_structure`/`meta.json` records relaxed provenance); Test `tests/test_structure_relax_step.py`.

**Interfaces:**
- Consumes: `relax_cache.get_or_relax` (Task 2).
- Produces: `StructureRelaxStep(Step)` — input the same `spec` shape `ParsimonyPackStep` consumes; config `{relax: bool=False, cache_dir, **relax params}`; output the spec with each ingredient's `structure` rewritten to `{"kind":"file","ref": <cached relaxed path>}` when `relax` and the ref is `alphafold`/`pdb`/`cif`; `file` refs pass through. Registered via `register_parsimony`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_structure_relax_step.py
from pbg_parsimony import processes as P

SPEC = {"ingredients":[
    {"id":"gapdh","structure":{"kind":"alphafold","ref":"P0A9B2"}},
    {"id":"ribo","structure":{"kind":"cif","ref":"4YBB"}},
    {"id":"blob","structure":{"kind":"file","ref":"/tmp/pre.pdb"}}]}

def test_relax_off_passthrough():
    step = P.StructureRelaxStep(config={"relax": False})
    out = step.update({"spec": SPEC})
    assert out["spec"] == SPEC   # untouched

def test_relax_on_rewrites_to_file_refs(monkeypatch, tmp_path):
    monkeypatch.setattr(P, "get_or_relax",
        lambda ref, cache_dir, cfg, obj_id: tmp_path/f"{obj_id}.pdb")
    step = P.StructureRelaxStep(config={"relax": True, "cache_dir": str(tmp_path)})
    out = step.update({"spec": SPEC})
    ing = {i["id"]: i for i in out["spec"]["ingredients"]}
    assert ing["gapdh"]["structure"] == {"kind":"file","ref": str(tmp_path/"gapdh.pdb")}
    assert ing["ribo"]["structure"] == {"kind":"file","ref": str(tmp_path/"ribo.pdb")}
    assert ing["blob"]["structure"] == {"kind":"file","ref":"/tmp/pre.pdb"}  # file passthrough
```

- [ ] **Step 2: Run — verify fail.**

- [ ] **Step 3: Implement.** `StructureRelaxStep(Step)` (mirror `ParsimonyPackStep`'s schema/`inputs`/`outputs`/`update` style): `update()` deep-copies `spec`; if not `config["relax"]` return it; else for each ingredient whose `structure["kind"]` in `{alphafold,pdb,cif}`, call `get_or_relax(structure, cache_dir, relax_cfg, obj_id=ingredient["id"])` and set `structure = {"kind":"file","ref": str(path)}`. Import `get_or_relax` as a module-level name (tests monkeypatch). Add to `register_parsimony`. In `api.py`, extend `_public_structure`/`meta.json` so a relaxed ingredient records `{db:"relaxed", id, provenance: <the .provenance.json contents>}` (best-effort read of the sidecar).

- [ ] **Step 4: Run — verify pass.**

- [ ] **Step 5: Commit.** `git commit -m "feat: StructureRelaxStep (opt-in) + relaxed provenance in pack meta"`

---

### Task 4: Integration (slow) + docs; ecoli composite passthrough

**Repo:** `pbg-parsimony` (worktree); + a thin note/change for `3d-ecoli`.
**Files:** Test `tests/test_relax_integration.py`; Modify `README`/docs (runtime + usage).

- [ ] **Step 1: Slow integration test**

```python
# tests/test_relax_integration.py
import json, pytest
@pytest.mark.slow
def test_two_ingredient_relaxed_pack(tmp_path):
    """relax=True on a 2-ingredient spec → relaxed cached PDBs + a valid pack that
    meshed the relaxed files. Needs OpenMM + the parsimony CLI (PARSIMONY_HOME)."""
    pytest.importorskip("openmm")
    from pbg_parsimony import processes as P
    spec = {"ingredients":[{"id":"a","structure":{"kind":"alphafold","ref":"<small accession>"}},
                           {"id":"b","structure":{"kind":"alphafold","ref":"<small accession>"}}]}
    relaxed = P.StructureRelaxStep(config={"relax": True, "cache_dir": str(tmp_path),
                                           "equil_ps": 5.0, "padding_nm": 0.8}).update({"spec": spec})
    for ing in relaxed["spec"]["ingredients"]:
        assert ing["structure"]["kind"] == "file"
        p = ing["structure"]["ref"]
        assert p.endswith(".pdb")
        assert (str(p).replace(".pdb",".provenance.json"))  # provenance beside it
    # then build_pack(...) over relaxed → parsimony.pack.v1 (assert format/placements)
```

- [ ] **Step 2: Run the FAST suite green** (`-m "not slow"`) across both repos; run the slow one manually once with OpenMM + `PARSIMONY_HOME` set, record runtime (~minutes/structure) in the docs.

- [ ] **Step 3: Docs** — a short `docs/` note: enabling `relax=True`, the param set, the cache layout (`structures/relaxed/<id>__<hash>.pdb` + `.provenance.json`), expected runtime + the opt-in default, and that it needs OpenMM + AMBER/TIP3P force fields.

- [ ] **Step 4: 3d-ecoli passthrough (follow-up, thin)** — in `3d-ecoli/ecoli_3d/build.py`/`composite.py`, thread a `relax=` flag so `EcoliStructuralStep`/`build_model` routes ingredient structures through `StructureRelaxStep`/`get_or_relax` before packing. Small; may be its own PR. Note it here so it isn't lost.

- [ ] **Step 5: Commit.** `git commit -m "test+docs: relaxed-pack integration + usage/runtime; note 3d-ecoli passthrough"`

---

## Self-Review

**Spec coverage:** all-atom solvated relax → Task 1; param-keyed cache + provenance (reproducibility) → Task 2; opt-in upstream `StructureRelaxStep` rewriting to file refs + provenance in meta → Task 3; slow integration + docs + ecoli wiring → Task 4. Roadmap B/C is explicitly out of this plan. ✔

**Placeholder scan:** No TBD/TODO in the tasks. `<small accession>` in the slow test is an intentional fill-in (pick a small monomer at implementation) — the only literal to choose, called out.

**Type consistency:** `relax_in_water(pdb_in, pdb_out, **params) -> provenance dict` (Task 1) consumed by `get_or_relax` (Task 2), which returns a `Path` consumed by `StructureRelaxStep` (Task 3) to build `{"kind":"file","ref": str(path)}`. `relax_params_hash`/`relaxed_path`/`get_or_relax` names consistent Tasks 2↔3. The `spec["ingredients"][*]["structure"]` `{kind,ref}` shape matches `processes._ref`/`spec_to_ingredients`.
