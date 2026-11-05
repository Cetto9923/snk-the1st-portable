#!/usr/bin/env python3
"""Exact HLE gap for the runtime module set that is actually loaded on device.

The static coverage report (hle_coverage.py) treats every peer module in
the title as a symbol provider. That is not what the device does: the boot
configuration loads main and rtld as guest modules and answers every
other import from the host HLE. This script reproduces exactly that view,
so the gap list matches the unresolved= counter the runtime prints.

Usage:
  python3 scripts/analysis/runtime_gap.py \\
      --module main=.local/nca/nso/main.bin \\
      --module rtld=.local/nca/nso/rtld.bin \\
      --hle src/runtime/hle/nso_host.c \\
      --out .local/analysis/runtime_gap.json
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
    """Every import name the inherited HLE answers by name."""
    known = set()
    for source in sources:
        text = source.read_text(encoding="utf-8", errors="replace")
        known.update(STRNCMP.findall(text))
        known.update(STRCMP.findall(text))
        known.update(PURE.findall(text))
        known.update(m.group(1) for m in LITERAL.finditer(text))
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


def defined_exports(resolver, nso: Path):
    """Symbols a guest module defines (st_shndx != 0), i.e. what it can export."""
    ctx = resolver.parse(nso)
    exports = set()
    index = 0
    while index < 20000:
        try:
            info = ctx["sym_info"](index)
            name = ctx["sym_name"](index)
        except Exception:
            break
        if name and info[3] != 0:
            exports.add(name)
        index += 1
    return exports


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--module", action="append", required=True, metavar="NAME=NSO")
    ap.add_argument("--hle", type=Path, action="append", required=True)
    ap.add_argument("--resolver", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--max-callers", type=int, default=8)
    args = ap.parse_args()

    resolver = load_resolver(args.resolver)
    known = hle_surface(args.hle)

    modules = []
    for spec in args.module:
        name, _, path = spec.partition("=")
        modules.append((name, Path(path)))

    peer_exports = set()
    for _name, path in modules:
        peer_exports |= defined_exports(resolver, path)

    report = {"modules": {}, "imports": [], "unresolved": [],
              "unresolved_by_namespace": {}, "unresolved_total": 0}

    for name, path in modules:
        ctx = resolver.parse(path)
        stubs = resolver.build_plt_map(ctx)
        sym_to_stub = {}
        for stub, entry in stubs.items():
            sym_to_stub.setdefault(entry[0], stub)
        callers = resolver.scan_callers(ctx, set(stubs.values()))

        info = {"nso": str(path), "imports": len(sym_to_stub),
                "provided_by_hle": 0, "provided_by_peer": 0, "unresolved": 0}
        for index in sorted(sym_to_stub):
            symbol = ctx["sym_name"](index)
            if symbol in known:
                info["provided_by_hle"] += 1
                provider = "hle"
            elif symbol in peer_exports:
                info["provided_by_peer"] += 1
                provider = "peer"
            else:
                provider = "host"
            # Every import is recorded with the owner that answers it, so the
            # HLE table generators can rebuild the whole surface from this
            # report and not only from the still open gap.
            report["imports"].append({"module": name, "index": index,
                                      "name": symbol, "provider": provider})
            if provider != "host":
                continue
            stub = sym_to_stub[index]
            sites = callers.get(stub, [])
            report["unresolved"].append({
                "module": name,
                "index": index,
                "name": symbol,
                "call_sites": ["0x%x" % s for s in sites[:args.max_callers]],
                "call_site_count": len(sites),
            })
            info["unresolved"] += 1
        report["modules"][name] = info

    counts = Counter(namespace(item["name"]) for item in report["unresolved"])
    report["unresolved_by_namespace"] = dict(counts.most_common())
    report["unresolved_total"] = len(report["unresolved"])

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("modules: " + ", ".join(
        "%s imports=%d hle=%d peer=%d unresolved=%d" % (
            n, report["modules"][n]["imports"], report["modules"][n]["provided_by_hle"],
            report["modules"][n]["provided_by_peer"], report["modules"][n]["unresolved"])
        for n, _ in modules))
    print("unresolved total = %d" % report["unresolved_total"])
    for ns, count in counts.most_common():
        print("  %4d  %s" % (count, ns))
    return 0


if __name__ == "__main__":
    sys.exit(main())
