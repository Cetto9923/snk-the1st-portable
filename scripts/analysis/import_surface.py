#!/usr/bin/env python3
"""Map every import of the primary guest module onto the provider that has it.

For the Sora no Kiseki the 1st boot the device loads main and rtld as guest
modules and answers the rest from the host HLE. This script prints the same
view per namespace and names the provider for each import, so the porting
surface (host HLE vs nnSdk vs multimedia) is explicit instead of guessed.

Usage:
  python3 scripts/analysis/import_surface.py --primary main.bin \\
      --provider rtld=rtld.bin --provider sdk=sdk.bin \\
      --provider multimedia=subsdk0.bin --out report.json
"""
import argparse
import collections
import importlib.util
import json
import sys
from pathlib import Path


def load_resolver(path):
    spec = importlib.util.spec_from_file_location("ric", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def namespace(name):
    if name.startswith("_ZN2nn"):
        rest = name[6:]
        i = 0
        while i < len(rest) and rest[i].isdigit():
            i += 1
        j = i
        while j < len(rest) and rest[j].isalpha():
            j += 1
        return "nn::" + rest[i:j]
    if name.startswith("_ZNSt") or name.startswith("_ZSt"):
        return "libc++"
    if name.startswith("__"):
        return "compiler-rt"
    if name.startswith("_ZN5movie"):
        return "movie"
    if name.startswith("nn"):
        return "nn-legacy"
    return "libc/other"


def defined_exports(resolver, nso):
    ctx = resolver.parse(nso)
    exports = set()
    index = 0
    while index < 40000:
        try:
            info = ctx["sym_info"](index)
            name = ctx["sym_name"](index)
        except Exception:
            break
        if name and info[3] != 0:
            exports.add(name)
        index += 1
    return exports


def imports_of(resolver, nso):
    ctx = resolver.parse(nso)
    stubs = resolver.build_plt_map(ctx)
    names = []
    for stub, entry in stubs.items():
        names.append(ctx["sym_name"](entry[0]))
    return names


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--primary", type=Path, required=True)
    ap.add_argument("--provider", action="append", default=[], metavar="NAME=NSO")
    ap.add_argument("--hle", type=Path, action="append", default=[])
    ap.add_argument("--resolver", type=Path, required=True)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    resolver = load_resolver(args.resolver)
    hle = set()
    for source in args.hle:
        text = source.read_text(encoding="utf-8", errors="replace")
        import re
        hle.update(re.findall(r'"([A-Za-z_][A-Za-z0-9_:]{2,})"', text))
    providers = {}
    for spec in args.provider:
        name, _, path = spec.partition("=")
        providers[name] = defined_exports(resolver, Path(path))

    rows = []
    for name in imports_of(resolver, args.primary):
        if name in hle:
            provider = "host-hle"
        else:
            provider = "MISSING"
            for pname, exports in providers.items():
                if name in exports:
                    provider = pname
                    break
        rows.append({"name": name, "namespace": namespace(name), "provider": provider})

    by_ns = collections.defaultdict(collections.Counter)
    for row in rows:
        by_ns[row["namespace"]][row["provider"]] += 1
    print("%-16s %6s  %s" % ("namespace", "total", "providers"))
    for ns in sorted(by_ns, key=lambda k: -sum(by_ns[k].values())):
        counts = by_ns[ns]
        detail = " ".join("%s=%d" % (p, counts[p]) for p in sorted(counts))
        print("%-16s %6d  %s" % (ns, sum(counts.values()), detail))
    total = collections.Counter(row["provider"] for row in rows)
    print("total=%d  %s" % (len(rows), " ".join("%s=%d" % kv for kv in sorted(total.items()))))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"rows": rows}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
