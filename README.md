# viva-parsimony

Reusable [process-bigraph](https://github.com/vivarium-collective/process-bigraph)
packing of **3D whole-cell structural models**. It wraps the
[parsimony](https://github.com/prismofeverything/parsimony) engine (a
cellPACK-style molecular packer) and turns a list of molecular ingredients +
cell geometry into a packed 3D cell that the parsimony viewer (or any compatible
viewer) can render.

It is **organism-agnostic**: the caller supplies *which* molecules, their
abundances, names and categories, and the structure source for each. A
whole-cell model such as [v2ecoli](https://github.com/vivarium-collective/v2ecoli)
provides those; viva-parsimony does the structure resolution, recipe authoring,
and packing.

## See it live

**[Explore a 3D whole-cell *E. coli* model in your browser →](https://pub-eb913fbbdc584bd7add047c823570b13.r2.dev/viewer/index.html?models=https://pub-eb913fbbdc584bd7add047c823570b13.r2.dev/ecoli-3d/viz/3d/models.json)**

Hundreds of molecular species packed at true abundance from a
[v2ecoli](https://github.com/vivarium-collective/v2ecoli) cell state — ribosomes,
RNA polymerase, metabolic enzymes, the supercoiled chromosome, flagella. Switch
between a **newborn cell** and a **pre-division cell** (two segregated,
daughter-centered chromosomes), toggle/isolate species by functional category,
and **"View in VR"** on a Meta Quest. This whole scene is built by viva-parsimony
and rendered in the bundled viewer (`viva_parsimony/viewer/`).

## What it does

1. **Resolve structures** — RCSB PDB / mmCIF (large assemblies) or AlphaFold DB
   (by UniProt accession), cached locally. (Also accepts a local `file`.)
2. **Mesh** each to Van-der-Waals surface LODs (via `parsimony mesh`).
3. **Author** a `2.1-parsimony` recipe (capsule cell, interior/surface regions,
   supercoiled rod nucleoid) + a staged octree pipeline + an ingredient
   metadata sidecar (display names + categories).
4. **Pack** with the parsimony octree engine → a `*.pack.json`.

## Install

```bash
uv venv
uv pip install -e ".[dev]"
```

Requires Python >= 3.10. `process-bigraph` and `bigraph-schema` are pulled from
their `main` branches (see `[tool.uv.sources]` in `pyproject.toml`); use `uv` so
those sources are honored.

### Runtime requirement: the parsimony binary

Packing shells out to the `parsimony` binary, which must be reachable. Set one of:

- `PARSIMONY_BIN` — path to the binary, or
- `PARSIMONY_HOME` — the parsimony repo (built: `cargo build --release`), or
- have `parsimony` on `PATH`.

(Structure relaxation additionally needs OpenMM; see `StructureRelaxStep` below.)

## Interactive demo

Pack a small example cell (real PDB structures + a lipid membrane in a capsule)
and explore it in the bundled 3D viewer:

```bash
PARSIMONY_HOME=/path/to/parsimony python -m viva_parsimony.demo
# or, after install:  viva-parsimony-demo
```

It builds the pack, assembles a self-contained viewer app, and opens it in your
browser. The ingredient panel groups molecules by category, is searchable, and
lets you toggle/isolate each species. The same composite is catalogued at
`viva_parsimony/composites/parsimony-demo.composite.yaml` for the
vivarium-dashboard.

## Python API

```python
from viva_parsimony import build_pack, Ingredient, Capsule, Chromosome, StructureRef

ingredients = [
    Ingredient("ribosome", count=6000, region="interior",
               structure=StructureRef("cif", "4YBB"),
               display_name="70S ribosome", category="Translation",
               color=(0.95, 0.55, 0.25)),
    Ingredient("ompA", count=20000, region="surface",
               structure=StructureRef("alphafold", "P0A910"),
               display_name="outer membrane protein A", category="Envelope",
               color=(0.8, 0.55, 0.85)),
    # lipids can use a cheap sphere proxy instead of a meshed structure:
    Ingredient("lipid", count=6000, region="surface", sphere_radius=12.0),
]
result = build_pack(
    ingredients,
    Capsule.from_volume_fl(1.15),          # cell volume in fL
    Chromosome(genome_csv="ecoli_k12_genes.csv",
               segment=StructureRef("pdb", "1BNA")),
    out_dir="out/ecoli", name="ecoli_3d", scale=0.3,
)
print(result["n_placed"], result["pack_path"])
```

`build_pack` returns `{pack_path, sidecar_path, recipe_path, pipeline_path,
n_placed, ingredients}`. Structures cache under `<out_dir>/structures` and meshes
under `<out_dir>/meshes`.

Passing `envelope={"inner": Capsule(...), "outer": Capsule(...)}` builds a
gram-negative two-membrane envelope; ingredients are then routed into nested
compartments by `Ingredient.compartment` (`cytoplasm` | `periplasm` |
`inner_membrane` | `outer_membrane`).

## In a process-bigraph composite

```python
from viva_parsimony import register_parsimony
register_parsimony(core)   # makes local:ParsimonyPackStep / local:StructureRelaxStep resolve
```

- **`ParsimonyPackStep`** — packs a cell from live molecular `counts` (input) +
  a structural `spec` (config), emitting the pack result on its `pack` output.
- **`StructureRelaxStep`** — opt-in upstream Step that rewrites each ingredient's
  fetched structure to a cached water-relaxed structure (OpenMM) before packing;
  `relax=False` (default) passes structures through unchanged.

## API overview

Exported from the top-level `viva_parsimony` package:

- **`build_pack`** — high-level entry point: resolve + mesh structures, author
  the recipe, and pack the cell.
- **`Ingredient`** — one molecular species to place (structure or sphere proxy,
  region/compartment, count, display metadata).
- **`Capsule`** — spherocylinder cell geometry; `Capsule.from_volume_fl(...)`
  sizes it to a cell volume.
- **`Chromosome`** — a supercoiled rod nucleoid (replication state, forks, nascent
  RNA/ribosome/peptide placements, septum constriction).
- **`StructureRef`** — a structure source: `pdb` / `cif` (RCSB id), `alphafold`
  (UniProt accession), or `file` (local path).
- **`find_parsimony_bin`** / **`ParsimonyNotFound`** — locate the parsimony
  binary (raises if unreachable).
- **`ParsimonyPackStep`** / **`StructureRelaxStep`** / **`register_parsimony`** —
  the process-bigraph Steps and their registration helper.

A back-compatibility shim distribution (`pbg-parsimony`, under `shim/`)
re-exports `viva_parsimony` for the package's former name.

## Links

- Repository: https://github.com/vivarium-collective/viva-parsimony
- parsimony engine: https://github.com/prismofeverything/parsimony
- process-bigraph: https://github.com/vivarium-collective/process-bigraph

*A project of the [Vivarium Collective](https://github.com/vivarium-collective).*
