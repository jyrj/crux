#!/usr/bin/env python3
"""Resolve OpenTitan IP file dependencies for Yosys synthesis.

Iteratively runs yosys-slang, parses error messages for missing packages/modules,
finds the files that provide them, and retries until compilation succeeds.
"""

import subprocess
import re
from pathlib import Path

OT_ROOT = Path("extern/opentitan/hw")
PLUGIN = Path("extern/yosys-slang/build/slang.so")
PRIM_RTL = OT_ROOT / "ip/prim/rtl"

# Known package -> file mappings
PKG_MAP = {}

def build_pkg_map():
    """Scan all .sv files for package declarations."""
    for sv in OT_ROOT.rglob("*.sv"):
        text = sv.read_text(errors="ignore")
        for m in re.finditer(r'^\s*package\s+(\w+)\s*;', text, re.MULTILINE):
            PKG_MAP[m.group(1)] = str(sv)

def build_module_map():
    """Scan all .sv files for module declarations."""
    mod_map = {}
    for sv in OT_ROOT.rglob("*.sv"):
        text = sv.read_text(errors="ignore")
        for m in re.finditer(r'^\s*module\s+(\w+)', text, re.MULTILINE):
            mod_map[m.group(1)] = str(sv)
    return mod_map

def try_compile(files: list[str], top: str) -> tuple[bool, list[str]]:
    """Try to compile with yosys-slang, return (success, missing_names)."""
    cmd = [
        "yosys", "-p",
        f"plugin -i {PLUGIN}; read_slang {' '.join(files)} "
        f"-I {PRIM_RTL} --top {top} -DSYNTHESIS"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

    if "Build succeeded" in result.stdout:
        return True, []

    missing = set()
    for line in (result.stdout + result.stderr).split("\n"):
        m = re.search(r"unknown class or package '(\w+)'", line)
        if m:
            missing.add(m.group(1))
        m = re.search(r"unknown module '(\w+)'", line)
        if m:
            missing.add(m.group(1))
    return False, list(missing)

def resolve_deps(ip_name: str, top_module: str):
    """Iteratively resolve dependencies for an OT IP."""
    build_pkg_map()
    mod_map = build_module_map()
    all_maps = {**PKG_MAP, **mod_map}

    ip_dir = OT_ROOT / "ip" / ip_name / "rtl"
    files = [str(f) for f in sorted(ip_dir.glob("*.sv"))]

    max_iters = 20
    for i in range(max_iters):
        ok, missing = try_compile(files, top_module)
        if ok:
            print(f"SUCCESS after {i} iterations")
            print(f"Files ({len(files)}):")
            for f in files:
                print(f"  {f}")
            return files

        if not missing:
            print(f"FAILED with unknown errors")
            return None

        added = False
        for name in missing:
            if name in all_maps:
                dep = all_maps[name]
                if dep not in files:
                    files.insert(0, dep)  # packages first
                    added = True
                    print(f"  + {Path(dep).name} (provides {name})")
            else:
                print(f"  ? Cannot find: {name}")

        if not added:
            print(f"STUCK: no new files to add. Missing: {missing}")
            return None

    print(f"FAILED: max iterations reached")
    return None


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <ip_name> <top_module>")
        sys.exit(1)
    resolve_deps(sys.argv[1], sys.argv[2])
