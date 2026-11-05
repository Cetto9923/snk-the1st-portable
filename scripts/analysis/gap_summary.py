#!/usr/bin/env python3
"""Human readable summary of the runtime HLE gap report.

Usage:
  python3 scripts/analysis/gap_summary.py .local/analysis/runtime_gap.json
"""
import collections
import json
import sys


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
    if name.startswith("nn"):
        return "nn-legacy"
    return "libc/other"


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else ".local/analysis/runtime_gap.json"
    want = sys.argv[2:]
    report = json.load(open(path, encoding="utf-8"))
    groups = collections.defaultdict(list)
    for item in report["unresolved"]:
        groups[namespace(item["name"])].append(item)
    for key in sorted(groups, key=lambda k: -len(groups[k])):
        print("%-20s %3d" % (key, len(groups[key])))
    print("")
    for key in want or sorted(groups):
        items = groups.get(key, [])
        if not items:
            continue
        print("== " + key + " (" + str(len(items)) + ")")
        for item in items:
            print("   [%3d] %s" % (item["index"], item["name"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
