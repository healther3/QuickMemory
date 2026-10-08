"""Collect release notices from the actual build environment, never user data.

Run with the same Python environment used for build_windows.py, after npm ci.
Explicit upstream-license fetches cover missing wheel license files and native
libraries whose license texts are absent from the Python installation.
"""
from __future__ import annotations

import argparse
import hashlib
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
    name = canonicalize_name(dist.metadata["Name"])
    if name == "proxy-tools" and dist.version == "0.1.0":
        if not allow_fetch:
            raise RuntimeError("proxy_tools wheel/sdist has no LICENSE; rerun with --fetch-missing")
        # Upstream has no release tags. This immutable release-day commit's
        # complete module matches both the PyPI 0.1.0 sdist and installed wheel.
        # Package metadata says MIT, but the actual upstream license is BSD:
        # preserve the full original notice instead of manufacturing MIT text.
        base = "https://raw.githubusercontent.com/jtushman/proxy_tools/70b751ef5e0647d974506fd5871903711b5e1811/"
        module = Path(dist.locate_file("proxy_tools/__init__.py"))
        expected_module = "d1539d95e1a713c068ca81d42e047b2c76568964cf277596d4e19efb22f476be"
        if hashlib.sha256(module.read_bytes()).hexdigest() != expected_module:
            raise RuntimeError("proxy_tools source changed; re-audit its upstream license")
        url = base + "LICENSE.txt"
        with urlopen(url, timeout=30) as response:
            raw = response.read()
        if hashlib.sha256(raw).hexdigest() != "a428fb8a2e762af3eb0a6edbbb88e9b42ccfee80fd9b423958bcacf9b9abbfe4":
            raise RuntimeError("Unexpected upstream proxy_tools LICENSE content")
        return [(url + " (module SHA256 verified; upstream BSD notice, despite MIT package metadata)", raw.decode("utf-8"))]
    if name != "tokenizers":
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


def native_notices(allow_fetch: bool) -> list[tuple[str, list[tuple[str, str]]]]:
    """Include native runtime notices omitted by this Python installation.

    Version-reporting modules supply exact versions. libffi and statically
    linked liblzma do not expose a patch version here, so explicitly label the
    license source revisions rather than claiming an unverified binary version.
    """
    import pyexpat
    import sqlite3
    import ssl
    import zlib

    if not allow_fetch:
        raise RuntimeError("Native runtime licenses require --fetch-missing")
    openssl = ssl.OPENSSL_VERSION.split()[1]
    expat = pyexpat.EXPAT_VERSION.removeprefix("expat_")
    versions = [openssl, expat, sqlite3.sqlite_version, zlib.ZLIB_RUNTIME_VERSION]
    if not all(re.fullmatch(r"\d+\.\d+\.\d+", version) for version in versions):
        raise RuntimeError("Unexpected native library version; review license source tags")
    raw = "https://raw.githubusercontent.com/"
    entries = [
        (f"Native runtime: OpenSSL {openssl}", [
            f"{raw}openssl/openssl/openssl-{openssl}/LICENSE.txt",
            f"{raw}openssl/openssl/openssl-{openssl}/AUTHORS.md",
        ]),
        (f"Native runtime: Expat {expat}", [
            f"{raw}libexpat/libexpat/R_{expat.replace('.', '_')}/expat/COPYING",
        ]),
        (f"Native runtime: zlib {zlib.ZLIB_RUNTIME_VERSION}", [
            f"{raw}madler/zlib/v{zlib.ZLIB_RUNTIME_VERSION}/LICENSE",
        ]),
        (f"Native runtime: SQLite {sqlite3.sqlite_version}", [
            f"{raw}sqlite/sqlite/version-{sqlite3.sqlite_version}/LICENSE.md",
        ]),
        ("Native runtime: libffi (libffi-8.dll ABI 8; exact patch version not exported)\n"
         "License source revisions: libffi v3.4.4 and v3.5.2; these labels identify\n"
         "the license sources, not an asserted binary version.", [
            f"{raw}libffi/libffi/v3.4.4/LICENSE",
            f"{raw}libffi/libffi/v3.5.2/LICENSE",
        ]),
        ("Native runtime: liblzma, statically linked in Python's _lzma extension\n"
         "Exact patch version not exported. Both historical public-domain and\n"
         "current 0BSD upstream licensing notices are retained. Source revisions\n"
         "below identify license texts, not an asserted binary version.\n"
         "This software includes code from XZ Utils <https://tukaani.org/xz/>.\n"
         "Copyright (C) The XZ Utils authors and contributors", [
            f"{raw}tukaani-project/xz/v5.2.5/COPYING",
            f"{raw}tukaani-project/xz/v5.8.1/COPYING",
            f"{raw}tukaani-project/xz/v5.8.1/COPYING.0BSD",
        ]),
    ]
    result = []
    for title, urls in entries:
        licenses = []
        for url in urls:
            with urlopen(url, timeout=30) as response:
                text = response.read().decode("utf-8")
            if len(text.strip()) < 100:
                raise RuntimeError("Incomplete upstream native license: " + url)
            licenses.append((url, text))
        result.append((title, licenses))
    return result


def webview_notices() -> list[tuple[str, list[tuple[str, str]]]]:
    """Match the bundled Microsoft SDK to the retained official NuGet license."""
    if sys.platform != "win32":
        return []
    directory = ROOT / "licenses" / "webview2-1.0.3856.49"
    source = json.loads((directory / "SOURCE.json").read_text(encoding="utf-8"))
    dist = metadata.distribution("pywebview")
    for name, entry in source["verified_pywebview_binaries"].items():
        binary = Path(dist.locate_file("webview/lib/" + name))
        if hashlib.sha256(binary.read_bytes()).hexdigest() != entry["sha256"]:
            raise RuntimeError(f"WebView2 SDK changed; verify its upstream license before release: {name}")
    licenses = []
    for name, digest in source["license_files"].items():
        file = directory / name
        if hashlib.sha256(file.read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"Retained WebView2 license does not match official source: {name}")
        licenses.append((name, read_text(file)))
    title = f"Microsoft WebView2 SDK {source['version']}\nSource: {source['source']}"
    return [(title, licenses)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect complete third-party release notices")
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "THIRD_PARTY_NOTICES.txt")
    parser.add_argument("--fetch-missing", action="store_true", help="Fetch missing wheel/native licenses from official source tags")
    args = parser.parse_args()

    runtime = runtime_distributions()
    packages = [python_notice(dist, args.fetch_missing) for dist in runtime]
    npm = npm_notices()
    native = native_notices(args.fetch_missing) + webview_notices()
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
        "The Python installation license is retained in full. Additional native\n"
        "runtime licenses not supplied in that file are included separately.\n"
        "The PyInstaller COPYING text includes the bootloader licensing exception.\n"
        "Source packages are available from the project URLs below and the versioned\n"
        "Python Package Index / npm registry entries corresponding to each package.\n"
        f"\nInventory: Python runtime packages {len(runtime)}; npm production packages {len(npm)}; "
        f"native library notice groups {len(native)}; build tools {len(build)}.\n"
    ]
    for title, files in [
        (f"Python interpreter {sys.version.split()[0]}", [("Python LICENSE.txt", read_text(python_license))]),
        *packages, *npm, *native, *build,
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
