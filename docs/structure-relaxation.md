# Structure relaxation (opt-in)

Ingredient structures are fetched as-is from RCSB (PDB/mmCIF) or AlphaFold DB —
crystallographic/predicted coordinates, no solvent, no minimization. For
callers that want an all-atom, explicit-water-relaxed structure instead
(closer to a physically settled conformation), viva-parsimony can run each
structure through a short OpenMM equilibration before packing.

**This is opt-in and defaults OFF.** Nothing changes for existing callers
unless they explicitly set `relax=True`.

## Enabling it

Two equivalent entry points:

- **Function**: `viva_parsimony.processes.relax_spec(spec, *, relax=True, cache_dir, relax_cfg)`
  returns a deep copy of `spec` with each `alphafold`/`pdb`/`cif` ingredient's
  `structure` rewritten to `{"kind": "file", "ref": <cached relaxed pdb path>}`.
  Existing `file` refs pass through unchanged. Feed the result to
  `spec_to_ingredients` / `spec_capsule` / `build_pack` as usual.

- **Step**: `viva_parsimony.processes.StructureRelaxStep` — a `process_bigraph`
  `Step` (`spec` in, `spec` out) for composites, wrapping `relax_spec` with
  its `config_schema` as the params below. Registered via
  `register_parsimony(core)` as `"StructureRelaxStep"`.

```python
from viva_parsimony import processes as P

relaxed = P.relax_spec(spec, relax=True, cache_dir="out/cache",
                        relax_cfg={"equil_ps": 5.0, "padding_nm": 1.0, "seed": 0})
```

## Parameters

All parameters are part of the cache key (see below), so changing any of them
produces a distinct relaxed structure rather than silently reusing a stale one.

| param              | default                                      | meaning                                   |
|---------------------|-----------------------------------------------|--------------------------------------------|
| `forcefield`         | `["amber14-all.xml", "amber14/tip3pfb.xml"]` | OpenMM force field XML files               |
| `water_model`        | `"tip3p"`                                     | explicit water model                       |
| `padding_nm`         | `1.0`                                          | solvent box padding around the solute (nm) |
| `ionic_strength_M`   | `0.15`                                         | neutralizing/background ion concentration  |
| `temperature_K`      | `300.0`                                        | equilibration temperature                  |
| `timestep_fs`        | `2.0`                                          | integrator timestep (fs)                   |
| `equil_ps`           | `200.0`                                        | equilibration length (ps)                  |
| `minimize`           | `True`                                         | run an energy minimization before equilibration |
| `seed`               | `0`                                            | RNG seed (velocities/ion placement)        |

## Cache layout

Relaxed structures are cached under `<cache_dir>/relaxed/`, keyed by a SHA1
hash over the structure reference, every relax param above, the (best-effort)
AlphaFold model version, and the installed OpenMM version — so a different
force field, padding, seed, etc. never collides with an existing cache entry:

```
<cache_dir>/relaxed/<obj_id>__<hash>.pdb
<cache_dir>/relaxed/<obj_id>__<hash>.provenance.json
```

The provenance sidecar records the source kind/id, model version, the relax
params used, whether relaxation actually succeeded (`relaxed: true/false`),
and a UTC timestamp. `viva_parsimony.api._public_structure` reads this sidecar
so the packed sidecar/viewer info box still shows a public structure record
for a relaxed ingredient (`{"db": "relaxed", "id": ..., "provenance": {...}}`)
even though its `structure.kind` is now `"file"`.

A cache **hit** returns the existing relaxed path without touching the
network or OpenMM.

## Failure handling

Relaxation is best-effort **per ingredient**: any failure — a
`pbg_openmm.relax.RelaxError` (e.g. a structure OpenMM can't parameterize), a
missing/failed structure fetch (network down, bad id), or OpenMM not being
installed at all — is logged and that single ingredient falls back to its
raw (unrelaxed) fetched structure rather than aborting the whole pack. This
mirrors the non-relax path's existing "skip a bad ingredient" behavior in
`build_pack`, so `relax=True` is safe to leave on for a heterogeneous
ingredient list where a rare structure might not fetch or relax cleanly.

## Requirements

- [OpenMM](https://openmm.org/) installed (`pbg-openmm`'s `relax_in_water`
  wraps it). If OpenMM isn't importable, that's just another per-ingredient
  failure mode: the ingredient falls back to its raw structure (per
  "Failure handling" above) and the pack still builds; import of
  `viva_parsimony` itself always succeeds either way.
- AMBER14 / TIP3P force field files (bundled with OpenMM's data files;
  no extra download).
- Network access to fetch the raw structure on a cache miss (RCSB/AlphaFold).

## Measured runtime

Two tiny real proteins (crambin, PDB `1CRN`, 46 residues; trp-cage, PDB
`1L2Y`, 20 residues — an NMR ensemble, which relaxed cleanly with no
fallback needed) relaxed and packed end-to-end
(`tests/test_relax_integration.py::test_two_ingredient_relaxed_pack`,
`equil_ps=5.0`, `padding_nm=1.0`) in **~45 seconds** total, including network
fetch, OpenMM equilibration for both structures, meshing, and packing via the
parsimony CLI. Larger structures and/or a production `equil_ps` (default
`200.0`, 40x this test's `5.0`) will take proportionally longer — budget
relaxation as a per-structure, cached, one-time cost rather than a per-run one.

## Testing

- `viva_parsimony.relax_cache` unit tests (`tests/test_relax_cache.py`) and the
  `relax_spec`/`StructureRelaxStep` unit tests (`tests/test_structure_relax_step.py`)
  run in the fast suite (`-m "not slow"`), with OpenMM/network mocked out.
- `tests/test_relax_integration.py` is a real, slow, network+OpenMM+CLI
  end-to-end test, marked `@pytest.mark.slow` and excluded from the default
  run. Run it explicitly:

  ```
  PARSIMONY_HOME=/path/to/parsimony PYTHONUTF8=1 \
    python -m pytest tests/test_relax_integration.py -m slow -v
  ```

  It skips cleanly (rather than failing) if OpenMM isn't installed or
  `PARSIMONY_HOME` isn't set.

## Follow-on (not in this branch)

Wiring `relax=` through end-to-end into a specific whole-cell composite is
deliberately left out of this branch/PR — separate follow-ups:

- **v2ecoli**: thread a `relax=` flag into the `baseline_parsimony` composite /
  `EcoliPackStep` so the `structural-ecoli` `s01` study can generate relaxed
  packs (routing each ingredient's structure through `StructureRelaxStep` /
  `get_or_relax` ahead of `ParsimonyPackStep`).
- **3d-ecoli**: the equivalent passthrough in `3d-ecoli/ecoli_3d/build.py` /
  `composite.py`, so `build_model`/`EcoliStructuralStep` can opt in the same
  way.
