#!/usr/bin/env python3
"""Disassemble exported functions or raw ranges out of an unpacked NSO.

The extracted nnSdk module is the authoritative description of the nn::
API contract: it is the code the real console runs. Reading it keeps the
host HLE honest instead of guessing from the mangled name.

Usage:
  python3 scripts/analysis/disasm_symbol.py .local/nca/nso/sdk.bin \\
      --name _ZN2nn2os17SetMemoryHeapSizeEm --lines 60
  python3 scripts/analysis/disasm_symbol.py .local/nca/nso/main.bin \\
      --offset 0x464720 --lines 60
"""
import argparse
import importlib.util
import sys
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM


def load_resolver(path):
    spec = importlib.util.spec_from_file_location("ric", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def find_symbol(ctx, wanted):
    index = 0
    while index < 40000:
        try:
            info = ctx["sym_info"](index)
            name = ctx["sym_name"](index)
        except Exception:
            break
        if name == wanted and info[3] != 0:
            return index, info[4], info[5]
        index += 1
    return None, None, None


def disassemble(ctx, start, lines, stop_at_ret=False):
    code = ctx["data"][ctx["file_offset"](start):]
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    count = 0
    for insn in md.disasm(code, start):
        print("%08x  %-9s %s" % (insn.address, insn.mnemonic, insn.op_str))
        count += 1
        if count >= lines:
            break
        if stop_at_ret and insn.mnemonic == "ret":
            break


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("nso", type=Path)
    ap.add_argument("--name")
    ap.add_argument("--offset", type=lambda v: int(v, 0))
    ap.add_argument("--resolver", type=Path, default=Path("scripts/runtime/resolve_import_callers.py"))
    ap.add_argument("--lines", type=int, default=48)
    args = ap.parse_args()

    resolver = load_resolver(args.resolver)
    ctx = resolver.parse(args.nso)
    if args.offset is not None:
        print("# range 0x%x +%d lines" % (args.offset, args.lines))
        disassemble(ctx, args.offset, args.lines)
        return 0
    if not args.name:
        ap.error("need --name or --offset")
    index, value, size = find_symbol(ctx, args.name)
    if index is None:
        print("symbol not found: " + args.name)
        return 1
    print("# %s  index=%d  module_offset=0x%x  size=%d" % (args.name, index, value, size))
    disassemble(ctx, value, args.lines, stop_at_ret=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
