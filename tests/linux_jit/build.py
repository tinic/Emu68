#!/usr/bin/env python3
"""Build an emission-only Linux adapter around Emu68's actual integer JIT."""
import argparse
from pathlib import Path
import subprocess
import hashlib
import json

p = argparse.ArgumentParser()
p.add_argument("--build", type=Path, default=Path("build/linux-jit"))
p.add_argument("--cc", default="gcc")
a = p.parse_args()
root = Path(__file__).resolve().parents[2]
a.build.mkdir(parents=True, exist_ok=True)
source = (root / "src/M68k_Translator.c").read_text()
# Keep the complete block translator verbatim. The firmware cache manager that
# follows it is replaced by the adapter's caller-supplied buffer and manifest.
end = source.index("\n/*\n    Verify if the translated code has changed")
(a.build / "translator.inc").write_text(source[:end])
support = (root / "src/support.c").read_text()
(a.build / "support.inc").write_text(support[support.index("uint32_t number_to_mask("):])
sr = (root / "src/M68k_SR.c").read_text()
# One DBcc scanner read bypasses cache_read_16 because firmware is big endian.
# Preserve that read's meaning on a little-endian Linux compiler.
sr = sr.replace("(int16_t)(insn_stream[1])",
                "(int16_t)cache_read_16(ICACHE, (uintptr_t)&insn_stream[1])")
(a.build / "M68k_SR.c").write_text(sr)
sources = ["M68k_SR", "M68k_MULDIV", "M68k_MOVE", "M68k_EA", "M68k_LINE0",
           "M68k_LINE4", "M68k_LINE5", "M68k_LINE6", "M68k_LINE8",
           "M68k_LINE9", "M68k_LINEB", "M68k_LINEC", "M68k_LINED",
           "M68k_LINEE", "M68k_CC", "M68k_Exception"]
cmd = [a.cc, "-std=gnu2x", "-O0", "-g", "-ffunction-sections",
       "-fdata-sections", "-Wl,--gc-sections", "-D_REGLOCK_H",
       "-DSET_FEATURES_AT_RUNTIME=0", "-ffixed-v19", "-ffixed-v20",
       "-ffixed-v21", "-I" + str(root / "include"),
       "-I" + str(a.build.resolve()), str(root / "tests/linux_jit/emit.c"),
       str(root / "tests/linux_jit/shim.c")]
cmd += [str(a.build / "M68k_SR.c") if s == "M68k_SR" else
        str(root / "src" / (s + ".c")) for s in sources]
cmd += [str(root / "src/aarch64/RegisterAllocator64.c"),
        "-o", str(a.build / "emu68-emit")]
subprocess.run(cmd, check=True)
files = [root/"src/M68k_Translator.c", root/"src/support.c", root/"src/aarch64/RegisterAllocator64.c"]
files += [root/"src"/(s+".c") for s in sources]
(a.build/"source-manifest.json").write_text(json.dumps({
    "sha256":{str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest() for f in files},
    "adapter_changes":["firmware cache allocation replaced by caller buffer",
                       "DBcc raw 16-bit read routed through big-endian cache reader"],
    "executed":False}, indent=2))
