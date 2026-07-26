"""High-level API: turn an ingredient list + cell geometry into a 3D pack.

This is the reusable core of pbg-parsimony. Organism-specific logic (which
molecules, their names/categories/abundances) lives in the caller (e.g.
v2ecoli); pbg-parsimony resolves structures, authors the recipe, and runs the
parsimony engine.
"""
from __future__ import annotations
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from pbg_parsimony.structures import StructureRef, fetch
from pbg_parsimony.engine import mesh_file, run_pipeline
from pbg_parsimony.recipe import object_block, author_recipe, build_pipeline


@dataclass
class Ingredient:
    """One molecular species to place. ``id`` is the unique key (becomes the
    recipe object key and the pack ingredient ``name``); ``region`` is
    ``interior`` | ``surface`` | ``fiber``.

    Provide a ``structure`` (meshed to a VdW surface) OR a ``sphere_radius``
    (a cheap sphere proxy, e.g. for membrane lipids). ``principal_vector``
    orients surface ingredients to the membrane normal."""
    id: str
    count: int
    structure: StructureRef | None = None
    sphere_radius: float | None = None
    color: tuple = (0.6, 0.6, 0.6)
    region: str = "interior"
    # Which envelope compartment this ingredient belongs to. Default cytoplasm
    # (the inner compartment). For a gram-negative envelope (build_pack envelope=…):
    # "cytoplasm" (inner interior) | "periplasm" (between the membranes) |
    # "inner_membrane" | "outer_membrane" (region="surface" → in that bilayer).
    compartment: str = "cytoplasm"
    display_name: str = ""
    category: str = ""
    proxy_voxel_size: float | None = None
    principal_vector: tuple | None = None
    packing_mode: str = "random"  # "tiled" → even Fibonacci surface layer (lipid leaflet)
    surface_offset: float = 0.0   # Å along the outward normal (bilayer leaflet ±δ / TM depth)
    lod_count: int = 4
    mesh_lods: str | None = None  # override the voxel-size LOD list passed to the
    #                               mesher (e.g. "16,8" for a big sparse object like
    #                               a flagellum tube, whose fine LODs are slow +
    #                               degenerate). None → the mesher default.
    pack_first: bool = False  # interior: pack in an early stage (before the small
    #                           molecules fragment the space) so large assemblies
    #                           reach their true count instead of being squeezed out.


@dataclass
class Capsule:
    """Spherocylinder cell geometry in Ångström (medial half-length + cap radius)."""
    half_len: float
    radius: float

    @classmethod
    def from_volume_fl(cls, volume_fl: float, radius_um: float = 0.5) -> "Capsule":
        """Capsule sized to a cell volume (fL≈µm³): V = πr²L + (4/3)πr³."""
        import math
        r = radius_um * 1e4  # µm → Å
        v = volume_fl * 1e12  # µm³ → Å³
        lcyl = max(0.0, (v - (4.0 / 3.0) * math.pi * r ** 3) / (math.pi * r ** 2))
        return cls(half_len=max(r, lcyl / 2.0), radius=r)


@dataclass
class Chromosome:
    """A supercoiled rod nucleoid. ``segment`` is the dsDNA mesh (e.g. RCSB
    1BNA); ``proteins`` are ingredient ids to bind along the fiber."""
    beads: int = 34000
    spacing: float = 135.0
    bead_radius: float = 12.0
    genome_csv: str | None = None
    supercoil: dict = field(default_factory=lambda: {"radius": 90.0, "pitch": 130.0, "domains": 200})
    segment: StructureRef | None = None
    segment_id: str = "dna_segment"
    color: tuple = (0.85, 0.75, 0.45)
    proteins: list = field(default_factory=list)
    # Replication state. ``n_chromosomes`` copies are laid out, one per cell
    # sub-region (``beads`` is the count *per* chromosome). ``fork_fraction`` in
    # (0,1) draws each chromosome as a theta structure — a replication bubble
    # around oriC pinched at two forks ``fork_fraction`` of the way to terC.
    # ``fork_marker`` is an ingredient id seated at each fork (the replisome).
    n_chromosomes: int = 1
    fork_fraction: float = 0.0
    fork_marker: str | None = None
    oric_marker: str | None = None   # ingredient id seated at each origin (oriC)
    ter_marker: str | None = None    # ingredient id seated at the terminus (terC)
    rnaps: list = field(default_factory=list)  # explicit RNAP placements: list of
    #   {"coordinates": int, "domain_index": int, "is_forward": bool}
    rnap_marker: str | None = None   # ingredient id used to render each RNAP
    rnas: list = field(default_factory=list)  # nascent RNA placements: list of
    #   {"root_coordinate": int, "root_domain": int, "length_nt": int, "is_mRNA": bool, "unique_index": int}
    rna_segment: str | None = None   # ingredient id used to render each nascent RNA bead
    rna_segment_free: str | None = None  # ingredient id for free (released) mRNA strands
    rna_angstrom_per_nt: float = 2.0  # strand contour length per nucleotide (Å)
    ribosomes: list = field(default_factory=list)  # explicit ribosome placements: list of
    #   {"mRNA_index": int, "pos_on_mRNA": int, "peptide_length": int}
    ribosome_marker: str | None = None  # ingredient id instanced at each ribosome position
    peptide_segment: str | None = None  # ingredient id instanced as each nascent peptide coil
    peptide_angstrom_per_aa: float = 3.0  # peptide contour length per amino acid (Å)
    # Septum constriction for a dividing cell. ``septum_depth`` is the fractional
    # radius reduction at midcell (0 = no taper; 0.5–0.7 = visible waist).
    # ``septum_width`` is the Gaussian σ in the same units as the capsule radius (Å).
    # When ``septum_depth > 0`` the packer's free-mRNA sampling and ribosome/peptide
    # confinement respect the tapered boundary instead of the full-width capsule.
    septum_depth: float = 0.0
    septum_width: float = 0.0


def _public_structure(ref):
    """Map an ingredient's StructureRef to the viewer info-box structure record
    ({db, id[, fmt]}). File-based composites (assembled complexes, the flagellum)
    have no single public PDB → None. A relaxed ``file`` ref (one with a sidecar
    ``<...>.provenance.json`` written by ``get_or_relax``) still yields a record,
    ``{"db": "relaxed", "id": ..., "provenance": ...}``, tracing back to the
    original fetched structure."""
    if ref is None:
        return None
    if ref.kind in ("pdb", "cif"):
        return {"db": "rcsb", "id": ref.ref, "fmt": ref.kind}
    if ref.kind == "alphafold":
        return {"db": "alphafold", "id": ref.ref}
    if ref.kind == "file":
        try:
            sc = Path(ref.ref).with_suffix(".provenance.json")
            if sc.exists():
                prov = json.loads(sc.read_text())
                return {"db": "relaxed", "id": prov.get("id"), "provenance": prov}
        except Exception:
            pass
    return None


def _publish_relaxed_pdb(ing, st: dict, struct_cache: Path) -> None:
    """Copy a relaxed ``file`` ingredient's PDB into ``struct_cache`` and point
    ``st["url"]`` at it (pack-relative), so the viewer can fetch the all-atom
    relaxed structure locally instead of hitting a public database. ``st`` is
    the record from ``_public_structure`` (mutated in place). Best-effort: any
    failure just leaves ``st`` without a ``url`` — the pack still builds."""
    if not st or st.get("db") != "relaxed":
        return
    ref = ing.structure
    if ref is None or ref.kind != "file":
        return
    try:
        src = Path(ref.ref)
        if not src.exists():
            return
        struct_cache.mkdir(parents=True, exist_ok=True)
        dest = struct_cache / f"{ing.id}.pdb"
        shutil.copy(src, dest)
        st["url"] = f"structures/{ing.id}.pdb"
    except Exception:
        pass


def build_pack(ingredients, capsule: Capsule, chromosome: Chromosome | None = None, *,
               out_dir, name: str = "model", scale: float = 1.0, proxy_lod: int = 2,
               cell_mesh=None, envelope: dict | None = None) -> dict:
    """Resolve + mesh structures, author the recipe, and pack the cell.

    ``envelope`` enables a gram-negative two-membrane envelope: a dict
    ``{"inner": Capsule, "outer": Capsule}``. Ingredients are then routed by
    ``Ingredient.compartment`` into nested compartments — outer ``cell`` (its
    surface = outer membrane, interior = periplasm) wrapping inner ``cytoplasm``
    (its surface = inner membrane, interior = cytoplasm). The chromosome lives in
    the cytoplasm. ``None`` → the original single-capsule cell.

    Returns ``{pack_path, sidecar_path, recipe_path, pipeline_path, n_placed,
    ingredients}``. Meshes go in ``<out_dir>/meshes``; structures cache in
    ``<out_dir>/structures``; the recipe references meshes as ``meshes/…``.
    """
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    struct_cache = out_dir / "structures"
    mesh_dir = out_dir / "meshes"
    objects, interior, surface, fiber, sidecar = {}, [], [], [], {}
    big_ids = []  # interior ingredients to pack first (pack_first=True)
    surface_ids = []
    # Envelope mode: route directives into the nested cell(outer)/cytoplasm(inner)
    # compartments. cell.surface = outer membrane, cell.interior = periplasm,
    # cytoplasm.surface = inner membrane, cytoplasm.interior = cytoplasm.
    env = {"cell": {"interior": [], "surface": []},
           "cytoplasm": {"interior": [], "surface": []}}

    def _route(ing):
        c = ing.compartment
        if c == "periplasm":      return "cell", "interior"
        if c == "outer_membrane": return "cell", "surface"
        if c == "inner_membrane": return "cytoplasm", "surface"
        return "cytoplasm", "interior"

    def add_mesh(obj_id, ref, color, proxy=None, lod_count=4, principal_vector=None,
                 mesh_lods=None, packing_mode=None, surface_offset=None):
        path = fetch(ref, struct_cache, slug=obj_id)
        stem = mesh_file(path, mesh_dir, lods=mesh_lods) if mesh_lods else mesh_file(path, mesh_dir)
        lods = [f"meshes/{stem}.lod{i}.obj" for i in range(lod_count)
                if (mesh_dir / f"{stem}.lod{i}.obj").exists()]
        if not lods:
            return False
        objects[obj_id] = object_block(color, lods, proxy, principal_vector,
                                       packing_mode, surface_offset)
        return True

    for ing in ingredients:
        if ing.structure is None and ing.sphere_radius is not None:
            obj = {"type": "single_sphere", "radius": float(ing.sphere_radius),
                   "color": [float(c) for c in ing.color]}
            if ing.principal_vector is not None:
                obj["principal_vector"] = list(ing.principal_vector)
            if ing.packing_mode and ing.packing_mode != "random":
                obj["packing_mode"] = ing.packing_mode
            if ing.surface_offset:
                obj["surface_offset"] = float(ing.surface_offset)
            objects[ing.id] = obj
        else:
            try:
                if not add_mesh(ing.id, ing.structure, ing.color, ing.proxy_voxel_size, ing.lod_count,
                                ing.principal_vector, ing.mesh_lods,
                                ing.packing_mode, ing.surface_offset):
                    print(f"  skip {ing.id}: no LODs"); continue
            except Exception as e:  # noqa: BLE001 — one bad structure shouldn't kill the build
                print(f"  skip {ing.id}: structure error {str(e)[:60]}"); continue
        cnt = max(1, int(ing.count * scale)) if ing.count > 0 else 0
        sidecar[ing.id] = {"display_name": ing.display_name or ing.id,
                           "category": ing.category, "count": cnt}
        # Record the public structure source so the viewer's info box can show the
        # real all-atom structure (RCSB id / AlphaFold accession). File-based
        # composites (assembled complexes, the flagellum) have no single public
        # structure → omitted (the box shows "no public structure"). A relaxed
        # `file` ref is the exception: it carries a provenance sidecar back to
        # the original public structure, so it still yields a record (db:"relaxed").
        st = _public_structure(ing.structure)
        if st:
            _publish_relaxed_pdb(ing, st, struct_cache)
            sidecar[ing.id]["structure"] = st
        if cnt <= 0:
            # Marker-only object (e.g. the fork replisome): registered so the
            # chromosome stage can seat it at the replication forks, but not
            # placed randomly via a count directive.
            continue
        directive = {"object": ing.id, "count": cnt}
        if ing.region == "fiber":
            fiber.append(directive); continue
        if ing.region == "surface":
            surface_ids.append(ing.id)
        if envelope is not None:
            rc, region = _route(ing)
            env[rc][region].append(directive)
            if region == "interior" and ing.pack_first:
                big_ids.append(ing.id)
        elif ing.region == "surface":
            surface.append(directive)
        else:
            interior.append(directive)
            if ing.pack_first:
                big_ids.append(ing.id)

    chrom_block = None
    if chromosome is not None:
        if chromosome.segment is not None:
            add_mesh(chromosome.segment_id, chromosome.segment, chromosome.color)
        genome_rel = None
        if chromosome.genome_csv:
            shutil.copy(chromosome.genome_csv, out_dir / "genome.csv")
            genome_rel = "genome.csv"
        chrom_block = {
            "beads": chromosome.beads, "spacing": chromosome.spacing,
            "bead_radius": chromosome.bead_radius, "color": list(chromosome.color),
            "compartment": "cell", "segment": chromosome.segment_id,
            "supercoil": chromosome.supercoil, "proteins": fiber,
            "n_chromosomes": chromosome.n_chromosomes,
            "fork_fraction": chromosome.fork_fraction,
        }
        if chromosome.fork_marker:
            chrom_block["fork_marker"] = chromosome.fork_marker
        if chromosome.oric_marker:
            chrom_block["oric_marker"] = chromosome.oric_marker
        if chromosome.ter_marker:
            chrom_block["ter_marker"] = chromosome.ter_marker
        if chromosome.rnaps:
            chrom_block["rnaps"] = chromosome.rnaps
        if chromosome.rnap_marker:
            chrom_block["rnap_marker"] = chromosome.rnap_marker
        if chromosome.rnas:
            chrom_block["rnas"] = chromosome.rnas
        if chromosome.rna_segment:
            chrom_block["rna_segment"] = chromosome.rna_segment
            chrom_block["rna_angstrom_per_nt"] = chromosome.rna_angstrom_per_nt
        if chromosome.rna_segment_free:
            chrom_block["rna_segment_free"] = chromosome.rna_segment_free
        if chromosome.ribosomes:
            chrom_block["ribosomes"] = chromosome.ribosomes
        if chromosome.ribosome_marker:
            chrom_block["ribosome_marker"] = chromosome.ribosome_marker
        if chromosome.peptide_segment:
            chrom_block["peptide_segment"] = chromosome.peptide_segment
            chrom_block["peptide_angstrom_per_aa"] = chromosome.peptide_angstrom_per_aa
        if chromosome.septum_depth > 0:
            chrom_block["septum_depth"] = chromosome.septum_depth
            chrom_block["septum_width"] = chromosome.septum_width
        if genome_rel:
            chrom_block["genome"] = genome_rel
        sidecar[chromosome.segment_id] = {
            "display_name": "Chromosomal DNA (B-form duplex)",
            "category": "Nucleoid", "count": chromosome.beads}

    # Optional constricted-cell mesh (a dividing-cell septum): write it next to
    # the recipe and point the cell compartment at it instead of the capsule.
    cell_compartment = None
    if cell_mesh is not None:
        verts, faces = cell_mesh
        obj_lines = [f"v {x:.2f} {y:.2f} {z:.2f}" for (x, y, z) in verts]
        obj_lines += [f"f {a + 1} {b + 1} {c + 1}" for (a, b, c) in faces]
        (out_dir / "cell.obj").write_text("\n".join(obj_lines) + "\n")
        cell_compartment = {"kind": "mesh", "mesh_path": "cell.obj"}

    env_arg = None
    if envelope is not None:
        if chrom_block is not None:
            chrom_block["compartment"] = "cytoplasm"  # nucleoid lives inside the inner membrane

        def _mesh_path(mesh, fname):  # write a (verts, faces) mesh as OBJ, return its rel path
            verts, faces = mesh
            lines = [f"v {x:.2f} {y:.2f} {z:.2f}" for (x, y, z) in verts]
            lines += [f"f {a + 1} {b + 1} {c + 1}" for (a, b, c) in faces]
            (out_dir / fname).write_text("\n".join(lines) + "\n")
            return fname

        outer_spec = {"half_len": envelope["outer"].half_len, "radius": envelope["outer"].radius,
                      "interior": env["cell"]["interior"], "surface": env["cell"]["surface"]}
        inner_spec = {"half_len": envelope["inner"].half_len, "radius": envelope["inner"].radius,
                      "interior": env["cytoplasm"]["interior"], "surface": env["cytoplasm"]["surface"]}
        # Dividing cell: constricted membrane meshes (pinched at the septum).
        if envelope.get("outer_mesh"):
            outer_spec["mesh_path"] = _mesh_path(envelope["outer_mesh"], "om.obj")
        if envelope.get("inner_mesh"):
            inner_spec["mesh_path"] = _mesh_path(envelope["inner_mesh"], "im.obj")
        env_arg = {"outer": outer_spec, "inner": inner_spec}
    recipe = author_recipe(name, objects, interior, surface,
                           {"half_len": capsule.half_len, "radius": capsule.radius},
                           chrom_block, cell_compartment=cell_compartment, envelope=env_arg)
    recipe_path = out_dir / f"{name}.json"
    recipe_path.write_text(json.dumps(recipe, indent=2))
    pipeline = build_pipeline(name, f"{name}.json", surface_ids=surface_ids,
                              has_chromosome=chrom_block is not None,
                              has_fiber_proteins=bool(fiber), big_ids=big_ids)
    pipeline_path = out_dir / f"{name}.pipeline.json"
    pipeline_path.write_text(json.dumps(pipeline, indent=2))
    sidecar_path = out_dir / f"{name}.meta.json"
    sidecar_path.write_text(json.dumps({"ingredients": sidecar}, indent=1))

    pack_path = out_dir / f"{name}.pack.json"
    res = run_pipeline(pipeline_path, pack_path, proxy_lod=proxy_lod)
    n_placed = 0
    try:
        n_placed = len(json.loads(pack_path.read_text()).get("placements", []))
    except Exception:
        pass
    return {"pack_path": str(pack_path), "sidecar_path": str(sidecar_path),
            "recipe_path": str(recipe_path), "pipeline_path": str(pipeline_path),
            "n_placed": n_placed, "ingredients": len(sidecar), "stdout": res["stdout"]}
