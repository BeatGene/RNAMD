#!/usr/bin/env python3
"""Inventory or real AmberTools -> OL3/TIP3P -> OpenMM RNA smoke, offline."""
import argparse
import datetime
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback


def run_check(args, report, out):
    for name in ("numpy", "openmm", "parmed", "mdtraj"):
        importlib.import_module(name)
        report.setdefault("packages", {})[name] = importlib.metadata.version(name)
    import numpy as np
    import openmm as mm
    from openmm import app, unit

    prefix = Path(sys.prefix)
    for name in ("tleap", "cpptraj"):
        path = prefix / "bin" / name
        if not path.is_file() or not os.access(path, os.X_OK):
            raise RuntimeError("Missing executable in selected environment: " + str(path))
        report.setdefault("executables", {})[name] = str(path)
    for filename in ("leaprc.RNA.OL3", "leaprc.water.tip3p"):
        path = prefix / "dat/leap/cmd" / filename
        if not path.is_file():
            raise RuntimeError("Missing AmberTools force-field file: " + str(path))
    # Parse OpenMM's native XML as a separate installation check.
    app.ForceField("amber14/RNA.OL3.xml", "amber14/tip3p.xml")
    report["platforms"] = [mm.Platform.getPlatform(i).getName() for i in range(mm.Platform.getNumPlatforms())]
    report["plugin_load_failures"] = list(mm.Platform.getPluginLoadFailures())
    if args.platform == "inventory":
        report["scope"] = "Imports, executables, OL3 XML parsing; no dynamics or GPU context."
        return

    if args.platform == "CUDA":
        visible = os.environ.get("CUDA_VISIBLE_DEVICES", "")
        if not visible or visible.strip() == "-1" or "," in visible:
            raise RuntimeError("Set CUDA_VISIBLE_DEVICES to exactly one authorized GPU/UUID first.")
    if args.platform not in report["platforms"]:
        raise RuntimeError("Requested platform unavailable: " + args.platform)
    leap_input = """source leaprc.RNA.OL3
source leaprc.water.tip3p
rna = sequence { G5 G G C G A A A G C C C3 }
check rna
solvateBox rna TIP3PBOX 8.0
addIonsRand rna Na+ 0
saveAmberParm rna smoke.prmtop smoke.inpcrd
savePdb rna smoke_solvated.pdb
quit
"""
    (out / "build.leap").write_text(leap_input)
    leap_env = os.environ.copy()
    leap_env["AMBERHOME"] = str(prefix)
    leap_env["PATH"] = str(prefix / "bin") + os.pathsep + leap_env.get("PATH", "")
    report["stage"] = "tleap_build"
    print("START tleap: synthetic RNA, OL3, TIP3P, neutralizing Na+", flush=True)
    with (out / "tleap.log").open("w") as log:
        result = subprocess.run([str(prefix / "bin/tleap"), "-f", "build.leap"],
                                cwd=out, env=leap_env, stdout=log,
                                stderr=subprocess.STDOUT, timeout=180, check=False)
    if result.returncode != 0:
        raise RuntimeError("tleap failed; inspect tleap.log")
    for filename in ("smoke.prmtop", "smoke.inpcrd"):
        if not (out / filename).is_file() or (out / filename).stat().st_size == 0:
            raise RuntimeError("tleap did not write " + filename + "; inspect tleap.log")
    prmtop = app.AmberPrmtopFile(str(out / "smoke.prmtop"))
    inpcrd = app.AmberInpcrdFile(str(out / "smoke.inpcrd"))
    rna_residues = [r for r in prmtop.topology.residues() if r.name in {"A", "C", "G", "U", "A5", "C3", "G5"}]
    if len(rna_residues) != 12 or inpcrd.boxVectors is None:
        raise RuntimeError("Unexpected RNA residue count or missing periodic box")
    system = prmtop.createSystem(nonbondedMethod=app.PME,
                                nonbondedCutoff=0.8 * unit.nanometer,
                                constraints=app.HBonds, rigidWater=True)
    nonbonded = next(f for f in system.getForces() if isinstance(f, mm.NonbondedForce))
    charge = sum(nonbonded.getParticleParameters(i)[0].value_in_unit(unit.elementary_charge)
                 for i in range(system.getNumParticles()))
    if abs(charge) > 1e-3:
        raise RuntimeError("Solvated system not neutral: " + str(charge))
    platform_obj = mm.Platform.getPlatformByName(args.platform)
    properties = ({"DeviceIndex": "0", "Precision": "mixed"} if args.platform == "CUDA"
                  else {"Threads": "2"})
    integrator = mm.LangevinMiddleIntegrator(300 * unit.kelvin, 1 / unit.picosecond,
                                           0.001 * unit.picoseconds)
    integrator.setRandomNumberSeed(20261117)
    report["stage"] = "openmm_context"
    print("START OpenMM context on " + args.platform, flush=True)
    simulation = app.Simulation(prmtop.topology, system, integrator, platform_obj, properties)
    simulation.context.setPeriodicBoxVectors(*inpcrd.boxVectors)
    simulation.context.setPositions(inpcrd.positions)
    report["stage"] = "minimization"
    print("START minimization (up to 200 iterations)", flush=True)
    simulation.minimizeEnergy(maxIterations=200)
    simulation.context.setVelocitiesToTemperature(300 * unit.kelvin, 20261117)
    before = simulation.context.getState(getEnergy=True).getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
    report["stage"] = "dynamics"
    print("START dynamics: " + str(args.steps) + " steps, 1 fs/step", flush=True)
    simulation.step(args.steps)
    state = simulation.context.getState(getEnergy=True, getPositions=True)
    after = state.getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
    kinetic = state.getKineticEnergy().value_in_unit(unit.kilojoule_per_mole)
    positions = state.getPositions(asNumpy=True).value_in_unit(unit.nanometer)
    if not np.isfinite([before, after, kinetic]).all() or not np.isfinite(positions).all():
        raise RuntimeError("Nonfinite energy/positions in RNA smoke")
    report.update({"actual_platform": simulation.context.getPlatform().getName(),
                   "atoms_including_water_ions_hydrogen": system.getNumParticles(),
                   "rna_residues": len(rna_residues), "total_charge_e": charge,
                   "steps": args.steps, "timestep_fs": 1,
                   "potential_before_kJ_mol": before, "potential_after_kJ_mol": after,
                   "kinetic_after_kJ_mol": kinetic,
                   "scope": "Synthetic RNA software smoke only; not production equilibration, throughput, or biological validation."})
    if args.platform == "CUDA":
        report["cuda_device_index"] = platform_obj.getPropertyValue(simulation.context, "DeviceIndex")
        report["cuda_precision"] = platform_obj.getPropertyValue(simulation.context, "Precision")
    with (out / "final.pdb").open("w") as handle:
        app.PDBFile.writeFile(prmtop.topology, state.getPositions(), handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=("inventory", "CPU", "CUDA"), required=True)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--output-root", type=Path,
                        default=Path.home() / "openmm_rna_setup" / "checks")
    args = parser.parse_args()
    if not 1 <= args.steps <= 1000:
        parser.error("Smoke steps must be between 1 and 1000")
    args.output_root.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix=args.platform.lower() + "_", dir=args.output_root)).resolve()
    started = time.monotonic()
    report = {"ok": False, "requested_platform": args.platform, "python": sys.executable,
              "prefix": sys.prefix, "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
              "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "stage": "inventory"}
    print("Check directory:", out, flush=True)
    try:
        run_check(args, report, out)
        report.update(ok=True, stage="complete")
    except Exception:
        report["traceback"] = traceback.format_exc()
        print(report["traceback"], file=sys.stderr)
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print("RNA_MD_" + args.platform.upper() + ("_OK" if report["ok"] else "_FAILED"), flush=True)
    print("Report:", out / "report.json", flush=True)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
