#!/usr/bin/env python3
"""Offline, single-GPU BioEmu2 RNA generation/CIF mapping/propagation smoke test.

Exercises the real model; finite coordinates and file roundtrips are software
checks, not validation of RNA geometry, kinetics, or augmentation quality.
"""

import argparse
import datetime
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import sys
import time
import traceback

SEQUENCE = 'GGGCGAAAGCCC'  # 12 nt; a small synthetic RNA, no experimental label.


def deny_network(*args, **kwargs):
    raise RuntimeError('This smoke test forbids Python socket connections')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--checkpoint', type=Path)
    args = parser.parse_args()
    out = args.out.expanduser().absolute()
    out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report = {
        'status': 'running',
        'sequence': SEQUENCE,
        'length_nt': len(SEQUENCE),
        'num_samples': 1,
        'lag_time_ns': 1.0,
        'sampling_seed': 42,
        'propagation_seed': 43,
        'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'python': sys.version,
        'python_executable': sys.executable,
        'cuda_visible_devices': os.environ.get('CUDA_VISIBLE_DEVICES'),
        'network_policy': 'Local checkpoint; empty protein MSA; Python socket connections denied',
        'limitation': 'Software smoke test only; RNA physicality, scientific accuracy and data augmentation are not validated.',
        'stages_seconds': {},
    }
    current_stage = 'initialization'

    def write_report():
        report['elapsed_seconds'] = round(time.monotonic() - started, 3)
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    def stage(name, action):
        nonlocal current_stage
        current_stage = name
        print(f'[{name}] START', flush=True)
        before = time.monotonic()
        value = action()
        torch.cuda.synchronize()
        report['stages_seconds'][name] = round(time.monotonic() - before, 3)
        write_report()
        print(f'[{name}] OK ({report["stages_seconds"][name]:.3f} s)', flush=True)
        return value

    try:
        write_report()
        os.environ['HF_HUB_OFFLINE'] = '1'
        socket.create_connection = deny_network
        socket.socket.connect = deny_network
        socket.socket.connect_ex = deny_network
        print('Importing installed BioEmu2 and CUDA dependencies...', flush=True)
        import numpy as np
        import torch
        import mdtraj as md
        from bioemu2 import EmuSession, MSA, System, load_model, map_cif_atom_order, save_frames

        if not torch.cuda.is_available():
            raise RuntimeError('CUDA is unavailable; check the selected GPU and driver access')
        if torch.cuda.device_count() != 1:
            raise RuntimeError('Expose exactly one allocated GPU with CUDA_VISIBLE_DEVICES')
        report.update({
            'bioemu2_version': importlib.metadata.version('bioemu2'),
            'torch_version': torch.__version__,
            'torch_cuda_version': torch.version.cuda,
            'gpu_name': torch.cuda.get_device_name(0),
            'gpu_compute_capability': list(torch.cuda.get_device_capability(0)),
        })
        torch.cuda.reset_peak_memory_stats()
        print('GPU:', report['gpu_name'], flush=True)
        checkpoint = args.checkpoint
        if checkpoint is None:
            record = Path(sys.prefix) / 'bioemu2_checkpoint_path.txt'
            if not record.is_file():
                raise FileNotFoundError(f'Missing {record}; use --checkpoint to specify local weights')
            checkpoint = Path(record.read_text().strip())
        checkpoint = checkpoint.expanduser().resolve()
        if not checkpoint.is_file() or not checkpoint.with_name('config.yaml').is_file():
            raise FileNotFoundError(f'Local checkpoint and same-directory config.yaml required: {checkpoint}')
        report['checkpoint'] = str(checkpoint)
        print('Local checkpoint:', checkpoint, flush=True)

        model = stage('load_model', lambda: load_model(
            checkpoint_path=checkpoint, device='cuda', precision='bf16-mixed',
        ))
        if not model.supports_propagation:
            raise RuntimeError('The loaded checkpoint does not support propagation')
        system = System.from_description(rna=[SEQUENCE])
        system.to_yaml(out / 'system.yaml')
        emu = EmuSession(system, model=model, mode='equilibrium', msa=MSA({}))
        expected_atoms = system.topology.n_atoms

        def validate(frame, label):
            if frame.n_frames != 1 or frame.n_atoms != expected_atoms:
                raise RuntimeError(f'{label}: unexpected frames/atoms: {frame.n_frames}/{frame.n_atoms}')
            if frame.topology.n_residues != len(SEQUENCE):
                raise RuntimeError(f'{label}: residue count differs from the system')
            if not np.isfinite(frame.xyz).all():
                raise RuntimeError(f'{label}: NaN or Inf coordinates')

        start = stage('sample_start', lambda: emu.sample(num_samples=1, batch_size=1, seed=42))
        validate(start, 'sampled start')
        save_frames(start, out / 'start')

        # Exercise the saved CIF mapping path used for future external decoys.
        mapped = stage('reload_start_cif', lambda: map_cif_atom_order(system, out / 'start/topology.cif'))
        validate(mapped, 'mapped CIF')
        map_error = float(np.max(np.abs(mapped.xyz - start.xyz)))
        report['cif_roundtrip_max_error_A'] = map_error * 10.0
        if map_error > 0.0002:  # nm; allow rounding when saving a CIF in angstroms.
            raise RuntimeError(f'CIF atom-order/coordinate roundtrip mismatch: {map_error} nm')

        endpoint = stage('propagate_1ns', lambda: emu.propagate(
            mapped, lag_time_ns=1.0, batch_size=1, seed=43,
        ))
        validate(endpoint, 'propagated endpoint')
        save_frames(endpoint, out / 'propagated')

        def read_output():
            loaded = md.load_xtc(str(out / 'propagated/samples.xtc'),
                                 top=str(out / 'propagated/topology.cif'))
            validate(loaded, 'reloaded output')
            error = float(np.max(np.abs(loaded.xyz - endpoint.xyz)))
            # XTC coordinates are lossy-compressed in nm, unlike the CIF above.
            if error > 0.002:
                raise RuntimeError(f'XTC coordinate roundtrip mismatch: {error} nm')
            original_names = [(a.residue.index, a.residue.name, a.name) for a in endpoint.topology.atoms]
            loaded_names = [(a.residue.index, a.residue.name, a.name) for a in loaded.topology.atoms]
            if original_names != loaded_names:
                raise RuntimeError('Saved endpoint topology changed residue/atom order')
            report['xtc_roundtrip_max_error_A'] = error * 10.0
            return loaded

        loaded = stage('read_output_files', read_output)
        # Alignment removes overall rotation/translation. This measures motion
        # from the generated start, not error against an experimental structure.
        displacement = float(md.rmsd(endpoint[:], mapped[:], parallel=False)[0] * 10.0)
        if not np.isfinite(displacement):
            raise RuntimeError('Non-finite aligned start-to-endpoint RMSD')
        report.update({
            'status': 'passed',
            'n_atoms': loaded.n_atoms,
            'n_residues': loaded.topology.n_residues,
            'n_frames': loaded.n_frames,
            'start_to_endpoint_aligned_rmsd_A': displacement,
            'torch_peak_allocated_MiB': torch.cuda.max_memory_allocated() / 1024**2,
            'torch_peak_reserved_MiB': torch.cuda.max_memory_reserved() / 1024**2,
            'physicality_checked': False,
        })
        write_report()
        print('RNA_PROPAGATE_SMOKE_OK', flush=True)
        print('Report:', out / 'report.json', flush=True)
        print('This verifies execution and file I/O; it does not establish RNA physicality or dynamics accuracy.', flush=True)
        return 0
    except Exception as exc:
        report.update(status='failed', failed_stage=current_stage,
                      error_type=type(exc).__name__, error=str(exc))
        write_report()
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
