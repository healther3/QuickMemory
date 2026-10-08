"""Collect release notices from the actual build environment, never user data.

Run with the same Python environment used for build_windows.py, after npm ci.
The only possible network request is an explicit upstream-license fallback for
the tokenizers wheel, which does not currently ship its LICENSE file.
"""
from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
import re
import sys
from pathlib import Path
from urllib.request import urlopen

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


ROOT = Path(__file__).resolve().parents[1]
LICENSE_NAME = re.compile(r"^(licen[cs]e|copying|notice)(?:$|[._-])", re.I)
LICENSE_SUFFIXES = {"", ".txt", ".md", ".rst", ".apache", ".apache2", ".bsd", ".mit", ".psf", ".gpl", ".lgpl"}


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def is_license(path: Path) -> bool:
    return bool(LICENSE_NAME.match(path.name)) and path.suffix.lower() in LICENSE_SUFFIXES


def runtime_distributions() -> list[metadata.Distribution]:
    """Resolve installed runtime dependencies, including enabled extra markers."""
    pending = []
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            requirement = Requirement(line)
            if requirement.marker is None or requirement.marker.evaluate():
                pending.append((requirement.name, set(requirement.extras)))
    seen: dict[str, tuple[metadata.Distribution, set[str]]] = {}
    while pending:
        name, extras = pending.pop()
        key = canonicalize_name(name)
        if key in seen and extras <= seen[key][1]:
            continue
        dist = metadata.distribution(name)
        extras |= seen.get(key, (None, set()))[1]
        seen[key] = (dist, extras)
        for spec in dist.requires or []:
            requirement = Requirement(spec)
            active = requirement.marker is None or any(
                requirement.marker.evaluate({"extra": extra}) for extra in ["", *sorted(extras)]
            )
            if active:
                pending.append((requirement.name, set(requirement.extras)))
    return [seen[key][0] for key in sorted(seen)]


def upstream_license(dist: metadata.Distribution, allow_fetch: bool) -> list[tuple[str, str]]:
    """Use a versioned primary source, never infer a full license from its name."""
    if canonicalize_name(dist.metadata["Name"]) != "tokenizers":
        return []
    if not re.fullmatch(r"\d+\.\d+\.\d+", dist.version):
        return []
    if not allow_fetch:
        raise RuntimeError("tokenizers wheel has no LICENSE; rerun with --fetch-missing")
    url = f"https://raw.githubusercontent.com/huggingface/tokenizers/v{dist.version}/LICENSE"
    with urlopen(url, timeout=30) as response:
        text = response.read().decode("utf-8")
    if "Apache License" not in text or "END OF TERMS AND CONDITIONS" not in text:
        raise RuntimeError("Unexpected upstream tokenizers LICENSE content")
    return [(url, text)]


def python_notice(dist: metadata.Distribution, allow_fetch: bool) -> tuple[str, list[tuple[str, str]]]:
    details = [f"Python package: {dist.metadata['Name']} {dist.version}"]
    expression = dist.metadata.get("License-Expression")
    if expression:
        details.append(f"Declared license expression: {expression}")
    elif dist.metadata.get("License"):
        details.append("Declared license metadata:\n" + dist.metadata["License"])
    for classifier in dist.metadata.get_all("Classifier", []):
        if classifier.startswith("License ::"):
            details.append("Declared classifier: " + classifier)
    for project_url in dist.metadata.get_all("Project-URL", []):
        details.append("Project URL: " + project_url)
    homepage = dist.metadata.get("Home-page")
    if homepage:
        details.append("Homepage: " + homepage)
    licenses = []
    for file in sorted(dist.files or [], key=str):
        if is_license(Path(file)):
            actual = Path(dist.locate_file(file))
            if actual.is_file():
                licenses.append((str(file).replace("\\", "/"), read_text(actual)))
    if not licenses:
        licenses = upstream_license(dist, allow_fetch)
    if not licenses:
        raise RuntimeError(f"Missing full license text for {dist.metadata['Name']} {dist.version}")
    return "\n".join(details), licenses


def npm_notices() -> list[tuple[str, list[tuple[str, str]]]]:
    lock = json.loads((ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    result = []
    for path, entry in sorted(lock["packages"].items()):
        if not path or entry.get("dev"):
            continue
        package_dir = ROOT / "frontend" / path
        package = json.loads((package_dir / "package.json").read_text(encoding="utf-8"))
        if package["version"] != entry["version"]:
            raise RuntimeError(f"npm package version differs from lockfile: {path}")
        licenses = [
            (file.relative_to(package_dir).as_posix(), read_text(file))
            for file in sorted(package_dir.rglob("*"))
            if file.is_file() and is_license(file) and "node_modules" not in file.relative_to(package_dir).parts
        ]
        if not licenses:
            raise RuntimeError(f"Missing full license text for npm package {package['name']}")
        details = f"npm production package: {package['name']} {package['version']}"
        if package.get("license"):
            details += "\nDeclared license metadata: " + str(package["license"])
        result.append((details, licenses))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect complete third-party release notices")
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "THIRD_PARTY_NOTICES.txt")
    parser.add_argument("--fetch-missing", action="store_true", help="Fetch missing tokenizers license from its official version tag")
    args = parser.parse_args()

    runtime = runtime_distributions()
    packages = [python_notice(dist, args.fetch_missing) for dist in runtime]
    npm = npm_notices()
    build = [python_notice(metadata.distribution(name), args.fetch_missing)
             for name in ("pyinstaller", "pyinstaller-hooks-contrib")]
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise RuntimeError("The build Python installation does not provide LICENSE.txt")
    sections = [
        "QuickMemory third-party notices\n\n"
        "The QuickMemory project license does not replace these third-party licenses.\n"
        "Collected from the installed build environment and npm production lockfile.\n"
        "The dependency inventory is conservative: optional code may not be exercised\n"
        "or bundled. Package license files and notices are reproduced without edits.\n"
        "The Python installation license includes its bundled third-party notices.\n"
        "The PyInstaller COPYING text includes the bootloader licensing exception.\n"
        "Source packages are available from the project URLs below and the versioned\n"
        "Python Package Index / npm registry entries corresponding to each package.\n"
        f"\nInventory: Python runtime packages {len(runtime)}; npm production packages {len(npm)}; "
        f"build tools {len(build)}.\n"
    ]
    for title, files in [
        (f"Python interpreter {sys.version.split()[0]}", [("Python LICENSE.txt", read_text(python_license))]),
        *packages, *npm, *build,
    ]:
        sections.append("\n" + "=" * 78 + "\n" + title + "\n")
        for label, text in files:
            sections.append("\n--- " + label + " ---\n\n" + text.rstrip() + "\n")
    output = "".join(sections)
    for local in (str(ROOT), str(Path(sys.base_prefix)), str(Path(sys.prefix))):
        if local in output:
            raise RuntimeError("Unexpected machine-specific path in collected notices")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding="utf-8", newline="\n")
    print(f"Collected {len(runtime)} Python runtime packages, {len(npm)} npm production packages, "
          f"Python and {len(build)} build tools; {len(output.encode('utf-8'))} bytes")


if __name__ == "__main__":
    main()
