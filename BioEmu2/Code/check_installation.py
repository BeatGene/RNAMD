#!/usr/bin/env python3
"""CPU-only offline installation checks. Does not load weights or launch CUDA."""
import importlib.metadata
import platform
import socket
import sys
import sysconfig
from pathlib import Path


def deny_network(*args, **kwargs):
    raise RuntimeError('Network is disabled in this installation check')


def main():
    # Deny Python socket connections, including import-time resource requests.
    socket.create_connection = deny_network
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    print('Python:', sys.version, flush=True)
    print('Platform:', platform.system(), platform.machine(), platform.libc_ver(), flush=True)
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise RuntimeError('Expected Linux x86_64')
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError('Expected Python 3.12')
    headers = Path(sysconfig.get_path('include')) / 'Python.h'
    if not headers.is_file():
        raise RuntimeError('Python.h missing: Triton may need Python headers')
    for package in ('bioemu2', 'torch', 'cuequivariance', 'cuequivariance-torch',
                    'cuequivariance-ops-torch-cu12', 'cuequivariance-ops-cu12', 'triton'):
        print(package, importlib.metadata.version(package), flush=True)

    import torch
    from bioemu2 import EmuSession, MSA, System, load_model, propagate
    from bioemu2.structure.preparation import prepare_structure
    import cuequivariance_torch

    print('Torch CUDA runtime:', torch.version.cuda, flush=True)
    if torch.version.cuda != '12.6':
        raise RuntimeError('Expected CUDA 12.6 PyTorch build from the official cuda12 extra')
    system = System.from_description(rna=['GCGAAACGC'])
    structure = prepare_structure(system, msa=MSA({}), mode='equilibrium', contacts=[])
    print('RNA residues:', structure.num_residues, 'atoms:', structure.num_nodes, flush=True)
    if structure.num_residues != 9 or structure.num_nodes <= 0:
        raise RuntimeError('Unexpected standard RNA topology')
    print('CPU_OFFLINE_CHECK_OK', flush=True)
    print('GPU kernels, checkpoint loading and propagation are NOT tested here.', flush=True)


if __name__ == '__main__':
    main()
