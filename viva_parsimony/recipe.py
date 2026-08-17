"""Author parsimony recipe + staged-pipeline JSON from resolved ingredients."""
from __future__ import annotations

LOD_VOXELS = [16.0, 8.0, 4.0, 2.5]


def object_block(color, lod_paths, proxy_voxel_size=None, principal_vector=None,
                 packing_mode=None, surface_offset=None):
    """A mesh ingredient object for the recipe ``objects`` map. ``principal_vector``
    (a local axis) is aligned to the surface normal by the engine during surface
    placement — e.g. a flagellum's whip axis pointing outward from the envelope.
    ``packing_mode`` (``"tiled"`` → even Fibonacci surface layer, e.g. a lipid
    leaflet) and ``surface_offset`` (Å along the outward normal, e.g. a bilayer
    leaflet at ±δ or a membrane protein's depth) feed surface placement."""
    o = {
        "type": "mesh",
        "color": [float(c) for c in color],
        "mesh_lods": [{"path": p, "voxel_size": LOD_VOXELS[min(i, len(LOD_VOXELS) - 1)]}
                      for i, p in enumerate(lod_paths)],
    }
    if proxy_voxel_size:
        o["proxy_voxel_size"] = float(proxy_voxel_size)
    if principal_vector is not None:
        o["principal_vector"] = [float(v) for v in principal_vector]
    if packing_mode and packing_mode != "random":
        o["packing_mode"] = packing_mode
    if surface_offset:
        o["surface_offset"] = float(surface_offset)
    return o


def _capsule(half, r):
    return {"kind": "capsule", "a": [-half, 0, 0], "b": [half, 0, 0], "radius": float(r)}


def author_recipe(name, objects, interior, surface, capsule, chromosome=None,
                  bbox_pad=1.2, cell_compartment=None, envelope=None):
    """Assemble a ``2.1-parsimony`` recipe dict. ``capsule`` is
    ``{"half_len","radius"}`` (Å); ``chromosome`` is a recipe chromosome block.
    ``cell_compartment`` overrides the default capsule compartment (e.g. a
    ``{"kind":"mesh","mesh_path":...}`` constricted-cell mesh for a septum).

    ``envelope`` builds a gram-negative two-membrane envelope: a dict
    ``{"outer": {half_len,radius,interior,surface}, "inner": {…}}``. The outer
    ``cell`` compartment's interior holds the inner ``cytoplasm`` compartment
    (its volume is excluded → the gap is the periplasm) plus periplasm
    directives; cytoplasm holds the cytoplasm directives + chromosome."""
    half, r = float(capsule["half_len"]), float(capsule["radius"])
    if envelope is not None:
        o, i = envelope["outer"], envelope["inner"]
        oh, orad = float(o["half_len"]), float(o["radius"])
        # Each membrane is a capsule, or a constricted MESH for a dividing cell
        # (so both membranes neck at the septum).
        outer_comp = ({"kind": "mesh", "mesh_path": o["mesh_path"]}
                      if o.get("mesh_path") else _capsule(oh, orad))
        inner_comp = ({"kind": "mesh", "mesh_path": i["mesh_path"]}
                      if i.get("mesh_path") else _capsule(float(i["half_len"]), float(i["radius"])))
        recipe = {
            "name": name, "version": "0.1.0", "format_version": "2.1-parsimony",
            "description": "Gram-negative envelope packed by viva-parsimony.",
            "bounding_box": [[-(oh + orad), -orad * bbox_pad, -orad * bbox_pad],
                             [oh + orad, orad * bbox_pad, orad * bbox_pad]],
            "objects": objects,
            "composition": {
                "space": {"regions": {"interior": ["cell"]}},
                "cell": {  # outer membrane (surface) + periplasm (interior, minus the inner child)
                    "compartment": outer_comp,
                    "regions": {"interior": ["cytoplasm"] + o["interior"], "surface": o["surface"]},
                },
                "cytoplasm": {  # inner membrane (surface) + cytoplasm (interior)
                    "compartment": inner_comp,
                    "regions": {"interior": i["interior"], "surface": i["surface"]},
                },
            },
        }
        if chromosome:
            recipe["chromosome"] = chromosome
        return recipe
    comp = cell_compartment or _capsule(half, r)
    recipe = {
        "name": name, "version": "0.1.0", "format_version": "2.1-parsimony",
        "description": "Packed by viva-parsimony.",
        "bounding_box": [[-(half + r), -r * bbox_pad, -r * bbox_pad],
                         [half + r, r * bbox_pad, r * bbox_pad]],
        "objects": objects,
        "composition": {
            "space": {"regions": {"interior": ["cell"]}},
            "cell": {
                "compartment": comp,
                "regions": {"interior": interior, "surface": surface},
            },
        },
    }
    if chromosome:
        recipe["chromosome"] = chromosome
    return recipe


def build_pipeline(name, recipe_rel, *, surface_ids, has_chromosome, has_fiber_proteins,
                   backend="octree", clearance_cell_size=40, big_ids=None):
    """Staged octree pipeline: chromosome → membrane (surface) → fiber proteins →
    big interior assemblies → densified interior.

    ``big_ids`` are large interior assemblies (ribosome, chaperonin, …) packed in
    an EARLY stage, before the flood of small molecules fragments the space — so
    they reach their true abundance instead of being squeezed out (a combined
    interior stage saturates a 70S ribosome at ~561 of 20,000; packed first it
    reaches the full 20,000)."""
    big_ids = list(big_ids or [])
    stages = []
    deps_for_interior = []
    if has_chromosome:
        stages.append({"id": "chromosome", "kind": "chromosome"})
        deps_for_interior.append("chromosome")
    if surface_ids:
        stages.append({"id": "membrane", "kind": "pack",
                       "include": list(surface_ids), "exclude": [], "densify": False})
    if has_chromosome and has_fiber_proteins:
        stages.append({"id": "fiber_proteins", "kind": "fiber_pack", "depends_on": ["chromosome"]})
        deps_for_interior.append("fiber_proteins")
    if big_ids:
        big_stage = {"id": "big", "kind": "pack", "include": big_ids, "exclude": [], "densify": True}
        if deps_for_interior:
            big_stage["depends_on"] = list(deps_for_interior)
        stages.append(big_stage)
        deps_for_interior.append("big")
    interior_stage = {"id": "interior", "kind": "pack", "include": [],
                      "exclude": list(surface_ids) + big_ids, "densify": True,
                      "clearance_cell_size": clearance_cell_size}
    if deps_for_interior:
        interior_stage["depends_on"] = deps_for_interior
    stages.append(interior_stage)
    return {"name": name, "recipe": recipe_rel, "seed": 0,
            "strict_bounds": True, "backend": backend, "stages": stages}
