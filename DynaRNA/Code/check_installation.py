#!/usr/bin/env python3
"""Check upstream imports, exact weights and one synthetic reverse step.

The synthetic result is an installation check, not a scientific prediction.
Only load the official checkpoint verified by the offline bundle manifest.
"""
import argparse
import io
import os
from pathlib import Path
import pickle
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--device", choices=("cpu", "cuda"), required=True)
    args = parser.parse_args()
    if args.device == "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
    elif not os.environ.get("CUDA_VISIBLE_DEVICES"):
        parser.error("Set CUDA_VISIBLE_DEVICES to the GPU you have selected")
    sys.path.insert(0, str(args.source.resolve()))
    import numpy as np
    import torch
    from ml_collections import ConfigDict
    from experiments import torch_train_diffusion as upstream

    print("Python:", sys.version, flush=True)
    print("Torch:", torch.__version__, "CUDA build:", torch.version.cuda, flush=True)
    print("NumPy:", np.__version__, flush=True)
    if args.device == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is unavailable")
        print("GPU:", torch.cuda.get_device_name(0), "capability:", torch.cuda.get_device_capability(0), flush=True)
        a = torch.ones((32, 32), device="cuda")
        if not torch.allclose(a @ a, torch.full_like(a, 32)):
            raise RuntimeError("CUDA matmul check failed")
        torch.cuda.synchronize()

    class CPUUnpickler(pickle.Unpickler):
        def find_class(self, module, name):
            if module == "torch.storage" and name == "_load_from_bytes":
                return lambda data: torch.load(io.BytesIO(data), map_location="cpu", weights_only=False)
            return super().find_class(module, name)

    with args.checkpoint.open("rb") as handle:
        checkpoint = CPUUnpickler(handle).load()
    if not {"cfg", "exp_state"} <= checkpoint.keys():
        raise ValueError("Unexpected checkpoint structure")
    saved = checkpoint["cfg"]
    cfg = upstream.get_config()
    cfg.experiment.update(saved.experiment)
    cfg.model.update(saved.model)
    cfg.data.max_len = saved.data.max_len
    cfg.data.inpainting_training = False
    cfg.data.rmsd_filter = None
    cfg.data.monomer_only = True
    cfg.experiment.batch_size = 1
    cfg = ConfigDict(cfg)
    torch.manual_seed(0)
    np.random.seed(0)
    experiment = upstream.Experiment(cfg)
    if experiment.device != args.device:
        raise RuntimeError("Upstream selected an unexpected device: " + experiment.device)
    experiment.model.load_state_dict(checkpoint["exp_state"], strict=True)
    experiment.model.eval()
    # Exercise the actual upstream sampler, including the NumPy/Torch boundary.
    with torch.no_grad():
        result = experiment.sample_reverse_diffusion(
            bb_mask=np.ones((1, 4)), initial_coords=np.zeros((1, 4, 3), dtype=np.float32),
            rever_step=1,
        )
    if len(result) != 1 or np.asarray(result[0]).shape != (2, 4, 3):
        raise RuntimeError("Unexpected sampler result shape")
    if not np.isfinite(result[0]).all():
        raise RuntimeError("Nonfinite sampler result")
    if args.device == "cuda":
        torch.cuda.synchronize()
    print("PASS: upstream imports, strict weights, one reverse step on " + args.device, flush=True)


if __name__ == "__main__":
    main()

