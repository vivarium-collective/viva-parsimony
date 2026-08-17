"""Interactive demo for viva-parsimony.

Packs a small example cell (a handful of real PDB structures + a lipid membrane
in a capsule) and serves it in the interactive 3D viewer.

    PARSIMONY_HOME=/path/to/parsimony python -m viva_parsimony.demo

Needs the parsimony binary (see README) and network access for a few PDB
downloads. Output (pack + meshes + viewer) is written under ``--out``.
"""
from __future__ import annotations
import argparse
import functools
import http.server
import json
import shutil
import socketserver
import webbrowser
from pathlib import Path

from viva_parsimony import Ingredient, Capsule, StructureRef, build_pack

VIEWER = Path(__file__).parent / "viewer"


def demo_ingredients():
    """A small, recognisable mix of real structures — no external model needed."""
    return [
        Ingredient("groel", 40, StructureRef("pdb", "1AON"), color=(0.95, 0.85, 0.3),
                   display_name="GroEL/ES chaperonin", category="Protein folding",
                   region="interior", proxy_voxel_size=12.0),
        Ingredient("lysozyme", 320, StructureRef("pdb", "1AKI"), color=(0.5, 0.8, 0.55),
                   display_name="Lysozyme", category="Metabolism", region="interior"),
        Ingredient("hemoglobin", 220, StructureRef("pdb", "1HHO"), color=(0.85, 0.4, 0.4),
                   display_name="Hemoglobin", category="Metabolism", region="interior"),
        Ingredient("antibody", 70, StructureRef("pdb", "1IGY"), color=(0.55, 0.6, 0.9),
                   display_name="Immunoglobulin G (antibody)", category="Envelope",
                   region="interior", proxy_voxel_size=8.0),
        Ingredient("lipid", 6000, sphere_radius=12.0, color=(0.82, 0.78, 0.68),
                   display_name="Membrane lipid", category="Envelope", region="surface",
                   principal_vector=(0, 0, 1)),
    ]


def build_demo(out_dir: str | Path = "out/parsimony-demo", scale: float = 1.0) -> Path:
    """Pack the demo and assemble a self-contained viewer app. Returns the app dir."""
    out = Path(out_dir)
    app = out / "app"
    build = out / "_build"
    res = build_pack(demo_ingredients(), Capsule(half_len=1500.0, radius=900.0),
                     out_dir=build, name="demo", scale=scale, proxy_lod=2)
    print(f"packed {res['n_placed']} instances of {res['ingredients']} ingredient types")

    (app / "data").mkdir(parents=True, exist_ok=True)
    (app / "meshes").mkdir(parents=True, exist_ok=True)
    for f in ("index.html", "viewer.js", "obj-worker.js"):
        shutil.copy(VIEWER / f, app / f)

    pack = json.loads(Path(res["pack_path"]).read_text())
    for ing in pack["ingredients"]:
        for lod in ing.get("shape", {}).get("lods", []):
            fn = Path(lod["url"]).name
            lod["url"] = "meshes/" + fn
            src = build / "meshes" / fn
            if src.exists():
                shutil.copy(src, app / "meshes" / fn)
    (app / "data" / "demo.pack.json").write_text(json.dumps(pack))
    shutil.copy(res["sidecar_path"], app / "data" / "demo.meta.json")
    return app


def main():
    ap = argparse.ArgumentParser(description="Build + serve the viva-parsimony 3D demo.")
    ap.add_argument("--out", default="out/parsimony-demo")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--build-only", action="store_true", help="build the app and exit (no server)")
    a = ap.parse_args()
    app = build_demo(a.out, scale=a.scale)
    print(f"demo app assembled at {app}")
    if a.build_only:
        return
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(app))
    with socketserver.TCPServer(("", a.port), handler) as httpd:
        url = f"http://localhost:{a.port}/"
        print(f"serving interactive 3D demo at {url}  (Ctrl-C to stop)")
        if not a.no_open:
            webbrowser.open(url)
        httpd.serve_forever()


if __name__ == "__main__":
    main()
