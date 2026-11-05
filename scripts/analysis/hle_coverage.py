#!/usr/bin/env python3
"""Compare a guest NSO import list against the inherited HLE surface.

The runtime binds imports by name, so the reuse question is simply: which
imports does the existing HLE already answer, and which ones are still
missing for this title.
"""
import argparse
import importlib.util
import json
import re
import sys
from collections import Counter
from pathlib import Path

STRNCMP = re.compile(r'strncmp\s*\(\s*name\s*,\s*"([^"]+)"')
STRCMP = re.compile(r'strcmp\s*\(\s*name\s*,\s*"([^"]+)"')
PURE = re.compile(r'PURE\((\w+)\)')
LITERAL = re.compile(r'"([A-Za-z_][A-Za-z0-9_:]{2,})"')


def load_resolver(path: Path):
    spec = importlib.util.spec_from_file_location("ric", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def guest_imports(resolver, nso: Path):
    ctx = resolver.parse(nso)
    stubs = resolver.build_plt_map(ctx)
    names = []
    for stub, entry in stubs.items():
        symbol = entry[0]
        names.append((symbol, ctx["sym_name"](symbol)))
    names.sort()
    return names


def hle_surface(sources: list[Path]):
    """Collect every import name the inherited HLE answers by name."""
    known = set()
    for source in sources:
        text = source.read_text(encoding="utf-8", errors="replace")
        known.update(STRNCMP.findall(text))
        known.update(STRCMP.findall(text))
        known.update(PURE.findall(text))
        # typed[] tables and other literal name tables
        for match in LITERAL.finditer(text):
            known.add(match.group(1))
    return known


def namespace(name: str) -> str:
    if name.startswith("_ZN2nn"):
        parts = name.split("E")
        if len(parts) > 1:
            return "nn::" + parts[0][len("_ZN2nn"):]
    if name.startswith("nn"):
        return "nn(legacy)"
    if name.startswith("__"):
        return "compiler-rt"
    return "libc/other"


def main():
    parser = argparse.ArgumentParser(description="HLE coverage for a guest NSO")
    parser.add_argument("--nso", type=Path, required=True)
    parser.add_argument("--hle", type=Path, action="append", required=True)
    parser.add_argument("--resolver", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    resolver = load_resolver(args.resolver)
    imports = guest_imports(resolver, args.nso)
    known = hle_surface(args.hle)

    covered = []
    missing = []
    for symbol, name in imports:
        (covered if name in known else missing).append({"index": symbol, "name": name})

    by_ns = Counter(namespace(item["name"]) for item in missing)
    report = {
        "nso": str(args.nso),
        "imports_total": len(imports),
        "covered": len(covered),
        "missing": len(missing),
        "missing_by_namespace": dict(by_ns.most_common()),
        "missing_names": [item["name"] for item in missing],
        "covered_names": [item["name"] for item in covered],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"imports={len(imports)} covered={len(covered)} missing={len(missing)} "
          f"({100.0 * len(covered) / max(1, len(imports)):.1f}% reused)")
    print("missing by namespace:")
    for ns, count in by_ns.most_common():
        print(f"  {count:>4}  {ns}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
