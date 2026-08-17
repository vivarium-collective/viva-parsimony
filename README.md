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
   (by UniProt accession), cached locally.
2. **Mesh** each to Van-der-Waals surface LODs (via `parsimony mesh`).
3. **Author** a `2.1-parsimony` recipe (capsule cell, interior/surface regions,
   supercoiled rod nucleoid) + a staged octree pipeline + an ingredient
   metadata sidecar (display names + categories).
4. **Pack** with the parsimony octree engine → a `*.pack.json`.

## Requirements

The `parsimony` binary must be reachable. Set one of:
- `PARSIMONY_BIN` — path to the binary, or
- `PARSIMONY_HOME` — the parsimony repo (built: `cargo build --release`), or
- have `parsimony` on `PATH`.

## Interactive demo

Pack a small example cell (real PDB structures + a lipid membrane in a capsule)
and explore it in the bundled 3D viewer:

```bash
PARSIMONY_HOME=/path/to/parsimony python -m viva_parsimony.demo
# or, after `pip install`:  viva-parsimony-demo
```

It builds the pack, assembles a self-contained viewer app, and opens it in your
browser. The ingredient panel groups molecules by category, is searchable, and
lets you toggle/isolate each species. The same composite is catalogued at
`viva_parsimony/composites/parsimony-demo.composite.yaml` for the
vivarium-dashboard.

## Use

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
    # …
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

In a process-bigraph composite, use `ParsimonyPackStep` (counts come in as the
`counts` input; the structural spec is config). `register_parsimony(core)`
makes `local:ParsimonyPackStep` resolve.

*A project of the [Vivarium Collective](https://github.com/vivarium-collective).*
