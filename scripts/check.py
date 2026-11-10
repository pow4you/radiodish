"""
Run everything that should pass before a release.

    python scripts/check.py            # tests, build both packages, twine check, install smoke test
    python scripts/check.py --tests    # just the tests
    python scripts/check.py --cov      # same, with a coverage report for the tests
    python scripts/check.py --tests --cov

Needs only uv (https://docs.astral.sh/uv/) -- no other tooling, and it works
the same on Windows, macOS and Linux.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
PACKAGES = ("radiodish", "radiodish-actor")


def run(*cmd: str) -> None:
    print("\n$", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def main(argv: list[str]) -> None:
    # 1. every test in the workspace (the root pyproject points pytest at packages/)
    # --with pytest-cov: the plugin is pulled in for this run, so --cov works
    # even before pytest-cov has been added to the dev dependency group
    cov = "--cov" in argv
    run(
        "uv", "run", "--all-packages", *(["--with", "pytest-cov"] if cov else []),
        "pytest", *(["--cov", "--cov-report=term-missing"] if cov else []),
    )
    if "--tests" in argv:
        return

    # 2. build both distributions from scratch
    for old in [*DIST.glob("*.whl"), *DIST.glob("*.tar.gz")]:
        old.unlink()  # (uv also keeps a dist/.gitignore, which must stay and is not a package)
    for package in PACKAGES:
        run("uv", "build", "--package", package)

    # 3. the READMEs must render on PyPI, and the metadata must be valid
    artifacts = sorted(str(p) for pattern in ("*.whl", "*.tar.gz") for p in DIST.glob(pattern))
    run("uv tool run", "twine", "check", *artifacts)

    # 4. install the built wheels into a clean environment and import them --
    #    catches what tests running against the source tree can't (e.g. an
    #    import that only works when src/ happens to be on sys.path)
    wheels = sorted(str(p) for p in DIST.glob("*.whl"))
    run(
        "uv", "run", "--no-project", "--isolated", "--python", ">=3.13",
        *[arg for wheel in wheels for arg in ("--with", wheel)],
        "python", "-c", "import radiodish, radioactor; print('install smoke test ok')",
    )
    print("\nAll checks passed.")


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)
