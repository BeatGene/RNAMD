#!/usr/bin/env python3
"""Run upstream inference with explicit paths and externally selected GPU.

Changes run settings, seed, GPU selection and unused visualization imports.
The upstream sampler and coordinate scaling are left unchanged.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import sys


def configure(tree, replacements, seed):
    found = set()
    nodes = []
    for node in tree.body:
        # These imports are unused by the upstream entry point's sampling path.
        # Avoid pulling notebook/visualization dependencies into headless inference.
        if isinstance(node, ast.ImportFrom) and node.module == "analysis":
            continue
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                if target.id == "chosen_gpu":
                    continue
                if target.id in replacements:
                    node.value = ast.Constant(replacements[target.id])
                    found.add(target.id)
            if (isinstance(target, ast.Subscript) and
                    ast.unparse(target.value) == "os.environ" and
                    ast.literal_eval(target.slice) in {"CUDA_DEVICE_ORDER", "CUDA_VISIBLE_DEVICES2", "CUDA_VISIBLE_DEVICES"}):
                continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            if ast.unparse(node.value.func) in {"torch.manual_seed", "np.random.seed"}:
                node.value.args = [ast.Constant(seed)]
        nodes.append(node)
    if found != set(replacements):
        raise ValueError("Upstream entry point changed; missing settings: " + str(set(replacements) - found))
    tree.body = nodes
    return ast.fix_missing_locations(tree)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--num-samples", type=int, default=2)
    parser.add_argument("--steps", type=int, default=800)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if not os.environ.get("CUDA_VISIBLE_DEVICES"):
        parser.error("Set CUDA_VISIBLE_DEVICES to the GPU you have selected")
    if not 1 <= args.num_samples <= 100 or not 1 <= args.steps <= 1023:
        parser.error("Use 1..100 samples and 1..1023 steps")
    args.source = args.source.resolve()
    args.checkpoint = args.checkpoint.resolve(strict=True)
    args.input = args.input.resolve(strict=True)
    args.output = args.output.resolve()
    if args.output.exists():
        parser.error("Output already exists; choose a new directory")
    from Bio import PDB
    import numpy as np
    structure = PDB.PDBParser(QUIET=True).get_structure("input", str(args.input))
    models = list(structure)
    if len(models) != 1 or len(list(models[0])) != 1:
        parser.error("Installation smoke input must contain one model and one RNA chain")
    residues = list(models[0].get_residues())
    if not 4 <= len(residues) <= 200 or any("C4'" not in r for r in residues):
        parser.error("Use a complete 4..200-nt RNA with one C4' per residue")
    entry = args.source / "infer_DynaRNA.py"
    text = entry.read_text()
    replacements = {"ckpt_dir": str(args.checkpoint.parent), "ckpt_path": str(args.checkpoint),
                    "pdb_file": str(args.input), "sample_dir": str(args.output),
                    "target_num": args.num_samples, "t_step": args.steps}
    code = compile(configure(ast.parse(text), replacements, args.seed), str(entry), "exec")
    sys.path.insert(0, str(args.source))
    os.chdir(args.source)
    os.environ.setdefault("MPLBACKEND", "Agg")
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable")
    args.output.mkdir(parents=True)
    (args.output / "run_settings.json").write_text(json.dumps({
        "source_entry_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "input": str(args.input), "checkpoint": str(args.checkpoint),
        "samples": args.num_samples, "steps": args.steps, "seed": args.seed,
        "cuda_visible_devices": os.environ["CUDA_VISIBLE_DEVICES"],
        "output_representation": "C4-only; upstream sampling/scaling unchanged",
    }, indent=2) + "\n")
    with torch.no_grad():
        exec(code, {"__name__": "__main__", "__file__": str(entry)})
    outputs = sorted(args.output.glob("valid_len_*.pdb"))
    if len(outputs) != args.num_samples:
        raise RuntimeError("Unexpected output count")
    for path in outputs:
        atoms = list(PDB.PDBParser(QUIET=True).get_structure("sample", str(path)).get_atoms())
        if len(atoms) != len(residues) or any(a.name != "C4'" for a in atoms):
            raise RuntimeError("Unexpected C4 atom count: " + str(path))
        if not np.isfinite(np.array([a.coord for a in atoms])).all():
            raise RuntimeError("Nonfinite output coordinates")
    print("PASS: generated", len(outputs), "C4-only structures. Scientific quality still needs validation.")


if __name__ == "__main__":
    main()

