#!/usr/bin/env python3
"""Resolve the guest module graph and report what the HLE still has to provide.

Every NSO in the title is analysed twice: the names it imports and the names
it exports. An import is satisfied when the inherited HLE answers it by name
or when a peer module exports it. Whatever is left is genuine new work.
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


def hle_surface(sources):
    known = set()
    for source in sources:
        text = source.read_text(encoding="utf-8", errors="replace")
        known.update(STRNCMP.findall(text))
        known.update(STRCMP.findall(text))
        known.update(PURE.findall(text))
        known.update(match.group(1) for match in LITERAL.finditer(text))
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
    parser = argparse.ArgumentParser(description="Guest module graph and HLE gap")
    parser.add_argument("--modules", action="append", required=True,
                        metavar="NAME=NSO=INSPECTION")
    parser.add_argument("--hle", type=Path, action="append", required=True)
    parser.add_argument("--resolver", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    resolver = load_resolver(args.resolver)
    known = hle_surface(args.hle)

    modules = {}
    exports = {}
    for spec in args.modules:
        name, nso_path, inspection_path = spec.split("=", 2)
        ctx = resolver.parse(Path(nso_path))
        stubs = resolver.build_plt_map(ctx)
        imports = sorted({ctx["sym_name"](entry[0]) for entry in stubs.values()})
        inspection = json.loads(Path(inspection_path).read_text(encoding="utf-8"))
        # A dynamic symbol is defined by the module when it has a section;
        # section 0 means SHN_UNDEF, that is an import of this module.
        exported = {symbol["name"] for symbol in inspection.get("symbols", [])
                    if symbol.get("name") and symbol.get("section")}
        modules[name] = {"nso": nso_path, "imports": imports,
                         "import_count": len(imports),
                         "export_count": len(exported)}
        exports[name] = exported

    all_exports = set()
    for names in exports.values():
        all_exports |= names

    report = {"modules": {}, "unresolved": []}
    counts = Counter()
    for name, info in modules.items():
        by_hle, by_peer, missing = [], [], []
        peer_exports = all_exports - exports[name]
        for symbol in info["imports"]:
            if symbol in known:
                by_hle.append(symbol)
            elif symbol in peer_exports:
                by_peer.append(symbol)
            else:
                missing.append(symbol)
        report["modules"][name] = {
            "imports": info["import_count"],
            "exports": info["export_count"],
            "satisfied_by_hle": len(by_hle),
            "satisfied_by_peer_module": len(by_peer),
            "unresolved": len(missing),
            "unresolved_names": missing,
        }
        for symbol in missing:
            counts[namespace(symbol)] += 1
        report["unresolved"].extend(missing)

    report["unresolved_total"] = len(report["unresolved"])
    report["unresolved_by_namespace"] = dict(counts.most_common())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("module graph")
    for name, info in report["modules"].items():
        print(f"  {name:<10} imports={info['imports']:<5} exports={info['exports']:<6} "
              f"hle={info['satisfied_by_hle']:<4} peer={info['satisfied_by_peer_module']:<4} "
              f"unresolved={info['unresolved']}")
    print(f"total unresolved: {report['unresolved_total']}")
    for ns, count in counts.most_common():
        print(f"  {count:>4}  {ns}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
