"""Remove generated project files without touching sources or local graphs by default."""

import argparse
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]


def generated_paths(include_outputs=False):
    paths = [ROOT / name for name in (
        "build", "dist", ".pytest_cache", ".mypy_cache", ".ruff_cache", "htmlcov",
        "tests/out", "tests/out_multi", "tests/out_replay",
    )]
    paths.extend(ROOT.glob("*.egg-info"))
    paths.extend(ROOT.glob(".coverage"))
    paths.extend(ROOT.glob(".coverage.*"))
    for name in ("domimap", "tests", "scripts", "benchmarks"):
        base = ROOT / name
        if base.is_symlink() or not base.is_dir():
            continue
        for path in base.rglob("*"):
            if any(parent.is_symlink() for parent in path.parents if parent != ROOT):
                continue
            if path.name == "__pycache__" or path.suffix in {".pyc", ".pyo"}:
                paths.append(path)
    if include_outputs:
        paths.append(ROOT / "out")
    # Select parents before children so a removed cache is not processed twice.
    selected = []
    for path in sorted(set(paths), key=lambda p: (len(p.parts), str(p))):
        if any(parent.is_symlink() for parent in path.parents if parent != ROOT):
            continue
        if not path.exists() and not path.is_symlink():
            continue
        if any(parent in selected for parent in path.parents):
            continue
        selected.append(path)
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="List files without deleting them")
    parser.add_argument("--outputs", action="store_true", help="Also delete the local out/ graphs")
    args = parser.parse_args()
    paths = generated_paths(args.outputs)
    for path in paths:
        print(("Would remove " if args.dry_run else "Remove ") + str(path.relative_to(ROOT)))
        if args.dry_run:
            continue
        if path.is_symlink() or path.is_file():
            path.unlink()
        else:
            shutil.rmtree(path)
    if not paths:
        print("Project is clean.")


if __name__ == "__main__":
    main()
