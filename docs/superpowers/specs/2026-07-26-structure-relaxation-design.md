# All-atom solvated structure relaxation + Bentopy roadmap

**Date:** 2026-07-26
**Repos:** `pbg-openmm` (new all-atom relax), `pbg-parsimony` (structure-acquisition step + cache; this spec lives here). Worktree `/Users/eranagmon/code/pbg-parsimony-relax`, branch `feat/structure-relaxation`, off `origin/main`.
**Context:** The parsimony 3D cell-packing pipeline fetches AlphaFold-predicted monomers and meshes them directly. The low-confidence disordered **tails stick out** in the packed scene (visually verified). We want to **relax each fetched structure with a short all-atom explicit-water MD run** so the tails compact — structured as a **reproducible process-bigraph step**. Part B/C (a Martini/Bentopy MD-packing back-end) is captured as a roadmap, not built now.

## Goals (Part A — the buildable spec)

1. A reusable **all-atom solvated relax** in `pbg-openmm`: a fetched protein PDB → (add water + ions, minimize, short NVT, strip solvent) → a relaxed atomistic PDB.
2. An explicit, upstream **`StructureRelaxStep`** in `pbg-parsimony` that turns structure acquisition (today imperative, buried in `build_pack`) into a real pbg node: fetch → relax (cached) → rewrite each ingredient to `StructureRef("file", relaxed.pdb)`, feeding the existing mesher/packer unchanged.
3. **Opt-in** (`relax=True`, default off) so normal packs are unaffected; **relax all** fetched structures when on.
4. **Reproducibility:** relaxed structures cached + provenance-recorded, keyed by the full input+parameter set, so any relaxed structure is regenerable from the record.

## Non-goals

- Not changing the Rust mesher, recipe, or pack pipeline — the relaxed PDB is a drop-in file at the existing fetch→mesh seam.
- Not GPU-optimizing / not production-length MD — a *short* relax to compact tails, cached one-time per structure.
- Not building the Bentopy/Martini MD back-end (Part B/C) — roadmap only.
- No CG↔atomistic back-mapping (that belongs to the Bentopy path).

## Background — the seam (verified)

- `pbg-parsimony/pbg_parsimony/structures.py` — `StructureRef(kind, ref)` (kinds `pdb`/`cif`/`alphafold`/`file`), `fetch()` downloads to `<cache>/<slug>.<ext>` (cache keyed only by slug — **no version/params**).
- `pbg-parsimony/pbg_parsimony/api.py` — `build_pack`'s `add_mesh` closure: `path = fetch(ref, struct_cache, slug=obj_id)` (**api.py:165**) → `mesh_file(path, mesh_dir, …)` (**api.py:166**). The mesher (`engine.mesh_file` → Rust `parsimony mesh`) consumes any atom-coordinate file path, so a relaxed PDB drops in with no downstream change.
- `pbg-parsimony/pbg_parsimony/processes.py` — `ParsimonyPackStep(Step)` (`spec_to_ingredients` + `build_pack`); `Ingredient.structure` accepts arbitrary `StructureRef`s.
- `3d-ecoli/ecoli_3d/build.py` — `select_ingredients`/`build_model` map species → `StructureRef`s (AlphaFold monomers + curated PDB/CIF assemblies).
- `pbg-openmm/pbg_openmm/processes.py` — `OpenMMMartiniProcess` is Martini CG, **vacuum-only, gro/top-in**; there is **no all-atom solvated path** — this spec adds it.

## Architecture

### Component 1 — `pbg-openmm`: all-atom solvated relax
New module `pbg_openmm/relax.py`:
```python
def relax_in_water(pdb_in: str, pdb_out: str, *, forcefield=("amber14-all.xml","amber14/tip3pfb.xml"),
                   water_model="tip3p", padding_nm=1.0, ionic_strength_M=0.15,
                   temperature_K=300.0, timestep_fs=2.0, equil_ps=200.0, minimize=True,
                   seed=0) -> dict:
    """Solvate an atomistic protein PDB, minimize + run short NVT, strip solvent,
    write the relaxed protein to pdb_out. Returns the provenance dict (all params
    + openmm version). Deterministic given seed (LangevinIntegrator.setRandomNumberSeed)."""
```
Flow: `PDBFile` → `Modeller` → `addHydrogens` → `addSolvent(padding, ionicStrength, neutralize)` → `ForceField.createSystem(PME, HBonds)` → `LangevinMiddleIntegrator(temperature, friction, dt)` (seeded) → `minimizeEnergy()` → run `equil_ps` NVT → select the protein atoms (drop `HOH`/ions) → write `pdb_out`. Best-effort: OpenMM/forcefield errors raise a typed `RelaxError` the caller catches. Also expose a thin `SolvatedRelaxStep(Step)` wrapper (inputs `structure_path`, config the params above, output `relaxed_path`) for direct pbg use.

### Component 2 — `pbg-parsimony`: `StructureRelaxStep` + cache
New `pbg_parsimony/relax_cache.py`:
- `relax_params_hash(ref, relax_cfg) -> str` — stable hash over `(source, id, resolved AlphaFold model_version, forcefield, water_model, padding, ionic_strength, temperature, timestep, equil_ps, seed, openmm_version)`.
- `relaxed_path(cache_dir, obj_id, phash) -> Path` = `<cache>/relaxed/<obj_id>__<phash>.pdb`.
- `get_or_relax(ref, cache_dir, relax_cfg) -> Path` — if the cached relaxed PDB exists, return it; else `fetch(ref)` → `relax_in_water(...)` → write cache + a `<...>.provenance.json` sidecar (the provenance dict) → return the path.

New Step in `pbg_parsimony/processes.py` — `StructureRelaxStep(Step)`:
- Input: the ingredient spec (same `spec` shape `ParsimonyPackStep` consumes). Config: `relax` (bool, default False) + the relax params (forcefield/water/padding/ionic/temperature/timestep/equil_ps/seed).
- `update()`: if `not relax` → pass the spec through unchanged. Else, for each ingredient's `StructureRef`, `get_or_relax(...)` and **rewrite** the ingredient's structure to `StructureRef("file", relaxed_path)`. Curated `file` refs (pre-assembled complexes) and already-relaxed refs pass through. Output: the rewritten spec.
- Wire it **before** `ParsimonyPackStep` in the composite/pipeline (a new execution layer), so the packer meshes relaxed PDBs. `EcoliStructuralStep`/`build_model` gain a `relax=` passthrough that, when set, routes structures through `get_or_relax` before packing (same effect for the imperative build.py path).

### Data flow
```
ingredient StructureRef (alphafold/pdb)
  → StructureRelaxStep (relax=True):
        get_or_relax → [cache hit? return] : fetch → relax_in_water (pbg-openmm) → cache <id>__<hash>.pdb + provenance.json
        → StructureRef("file", relaxed.pdb)
  → ParsimonyPackStep / build_pack → fetch (returns the file verbatim) → mesh_file → pack
(relax=False: unchanged — raw AlphaFold, as today)
```

## Reproducibility (core requirement)

- **Cache key = full param set**, so the same inputs always resolve to the same relaxed file, and different force-field/water/ns/seed produce distinct cache entries (no silent staleness — the current name-only cache's flaw).
- **Provenance sidecar** `<relaxed>.provenance.json` records: source, id, resolved AlphaFold model version, forcefield, water_model, padding, ionic_strength, temperature, timestep, equil_ps, seed, openmm_version, and a UTC timestamp — the relaxed structure is regenerable from it.
- Surface the relaxed-structure provenance into the pack's `<name>.meta.json` structure records (`api.py:_public_structure` ~L116-125) so a pack declares which relaxed structures (and params) it used.

## Testing

- **`relax_in_water` (pbg-openmm, `@slow`):** a tiny protein (or a short peptide) with a few-ps run + a small box → a valid relaxed PDB (parses; protein atoms present; water stripped); deterministic given seed (two runs with the same seed → identical output within tolerance). Guarded so the default suite doesn't run real OpenMM.
- **`relax_cache` (fast, unit):** `relax_params_hash` is stable + param-sensitive; `get_or_relax` returns the cached file on a hit (no re-relax) and writes provenance on a miss (relax mocked).
- **`StructureRelaxStep` (fast, mocked relax):** `relax=False` → spec unchanged; `relax=True` → each AlphaFold/pdb ingredient rewritten to `StructureRef("file", <cached relaxed>)`; curated `file` refs untouched.
- **Integration (`@slow`):** a 2-ingredient pack with `relax=True` produces relaxed cached PDBs + a valid `parsimony.pack.v1` that meshed the relaxed files.

## Risks

- **Compute cost:** all-atom explicit water on ~50 structures is heavy (minutes each on CPU). Mitigated by the cache (one-time per structure+params) and the opt-in flag; a first pass can relax a subset. Document expected runtime.
- **OpenMM/forcefield availability:** `relax_in_water` needs OpenMM + AMBER/TIP3P force fields in the env; failures degrade to using the raw fetched structure (logged), never break the pack.
- **Non-standard residues / AlphaFold quirks:** `addHydrogens`/`ForceField` may reject unusual residues — catch per-structure, fall back to raw, log which structures were relaxed vs. skipped (record in provenance).

## Roadmap — Part B/C (Bentopy MD-packing back-end; not built now)

**Vision:** one shared **cell recipe** (species counts from the v2ecoli state + envelope compartment geometry) drives **two back-ends**:
- **parsimony** — visual mesh → 3D Parsimony Viewer (today).
- **Bentopy** — a real *simulatable* coarse-grained cell: `bentopy-pack` (voxel `.npz` compartment masks derived from the cell envelope; seed + rearrange heuristic → `placements.json`) → `bentopy-render` (`.gro`/`.top`) → `bentopy-solvate` (Martini water/ions) → Gromacs/OpenMM MD.

**Bridge:** `pbg-martini` already provides `martinize_species` (atomistic PDB → CG), `solvate.py` (Martini water), `run_short_md` / `MartiniMDStep` — the CG pieces Bentopy plugs into. The all-atom relaxation (Part A) improves the **monomers feeding both** back-ends.

**Shared recipe abstraction (C):** factor the current `select_ingredients` output (species → counts → StructureRef + compartment) into a back-end-agnostic recipe object that either the parsimony packer or a new `bentopy` adapter (recipe → `.bent` segments + compartment masks) consumes. Reproducibility: the recipe + seed + structure-provenance (from A) fully determine either output.

**Sequencing (future):** (B1) a `bentopy` adapter: v2ecoli recipe → `.bent` + envelope voxel mask → `bentopy-pack`/`render`/`solvate` on a small CG system; evaluate. (B2) wire it as a pbg composite alongside the parsimony pack. (C) extract the shared recipe once both back-ends exist. Each its own spec → plan.
