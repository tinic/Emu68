#!/usr/bin/env python3
"""Dump genuine JIT units at RX function entries and CFG boundaries."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import struct

p = argparse.ArgumentParser()
p.add_argument("--emitter", type=Path, required=True)
p.add_argument("--guest", type=Path, required=True)
p.add_argument("--out", type=Path, required=True)
p.add_argument("--symbols", nargs="+", required=True)
a = p.parse_args()
a.out.mkdir(parents=True, exist_ok=True)
symbols = json.loads((a.guest/"symbols.json").read_text())
instructions = {}
for line in (a.guest/"guest.s").read_text().splitlines():
    m = re.match(r"\s*([0-9a-f]+):\s*((?:[0-9a-f]{4}\s+)+)\s*(\S+)\s*(.*)", line)
    if m:
        pc = 0x10000000 + int(m[1], 16)
        instructions[pc] = {"asm": m[3] + " " + m[4], "op": m[3],
                            "size": len(m[2].split())*2, "args": m[4]}
branches = ("bra", "bsr", "bhi", "bls", "bcc", "bcs", "bne", "beq",
            "bvc", "bvs", "bpl", "bmi", "bge", "blt", "bgt", "ble", "db")
ordered = sorted(instructions)
# objdump wraps instructions longer than three words onto a byte-only line.
for pc, following in zip(ordered, ordered[1:]):
    if following-pc <= 22: instructions[pc]["size"] = following-pc
image = (a.guest/"image.bin").read_bytes()
# GCC's bounded switch is MOVE.W(table, Dn.L*2),Dn; JMP(table,Dn.W).
# The bytes at table are signed offsets, never executable guest instructions.
switches = {}
for i, pc in enumerate(ordered):
    ins = instructions[pc]
    if ins["op"] != "jmp" or "," not in ins["args"]: continue
    target = re.search(r"([0-9a-f]+)\s+<", ins["args"])
    if not target: continue
    table = 0x10000000+int(target[1],16)
    bound = None
    for prev in reversed(ordered[max(0,i-8):i]):
        match = re.match(r"#(\d+),d\d$", instructions[prev]["args"])
        if instructions[prev]["op"] == "moveq" and match:
            bound = int(match[1]); break
    if bound is not None and bound < 256:
        targets = []
        for n in range(bound+1):
            off, = struct.unpack_from(">h", image, table-0x10000000+2*n)
            targets.append(table+off)
        if all(t in instructions for t in targets): switches[pc] = targets
summary = []
for symbol in a.symbols:
    if symbol not in symbols:
        raise SystemExit("symbol not present: " + symbol)
    start = symbols[symbol]
    end = min((pc for pc in symbols.values() if pc > start), default=start+4096)
    entries, visited, pending = {start}, set(), [start]
    while pending:
        pc = pending.pop()
        if pc in visited or not start <= pc < end or pc not in instructions: continue
        visited.add(pc)
        ins = instructions[pc]
        following = pc+ins["size"]
        successors = []
        if ins["op"].startswith(branches) or ins["op"] in ("jsr", "jmp"):
            target = re.search(r"([0-9a-f]+)\s+<", ins["args"])
            indirect_jump = ins["op"] == "jmp" and "," in ins["args"]
            if target and not indirect_jump:
                addr = 0x10000000 + int(target[1], 16)
                if start <= addr < end and addr in instructions:
                    entries.add(addr); successors.append(addr)
            if pc in switches:
                for addr in switches[pc]:
                    if start <= addr < end:
                        entries.add(addr); successors.append(addr)
            if not ins["op"].startswith("bra") and ins["op"] != "jmp" and following < end and following in instructions:
                entries.add(following)
                successors.append(following)
        elif ins["op"] not in ("rts", "rtd", "rte", "trap"):
            successors.append(following)
        pending.extend(successors)
    units, failures = [], []
    for pc in sorted(entries):
        prefix = a.out/(symbol+"-"+format(pc,"08x"))
        r = subprocess.run([str(a.emitter), str(a.guest/"image.bin"),
                            format(pc,"x"), str(prefix)], capture_output=True, text=True)
        if r.returncode:
            failures.append({"pc":pc,"error":r.stderr}); continue
        arm_text = subprocess.check_output(["objdump", "-D", "-b", "binary",
            "-m", "aarch64", str(prefix)+".bin"], text=True)
        Path(str(prefix)+".arm.s").write_text(arm_text)
        arm_lines = {}
        for line in arm_text.splitlines():
            m = re.match(r"\s*([0-9a-f]+):\s+[0-9a-f]{8}\s+(.*)", line)
            if m: arm_lines[int(m[1],16)] = m[2]
        annotated = []
        records = [json.loads(row) for row in Path(str(prefix)+".map.jsonl").read_text().splitlines()]
        costs = []
        for record in records:
            guest_pc = record["guest_pc"]
            ins = instructions.get(guest_pc, {})
            count = record["arm_bytes"]//4
            annotated.append(f"\n68k {guest_pc:08x}: {ins.get('asm','UNIT EXIT')}  [{count} ARM instructions]")
            off = record["arm_offset"]
            for at in range(off, off+record["arm_bytes"],4):
                annotated.append(f"  {at:04x}: {arm_lines.get(at,'?')}")
            costs.append({**record, "asm":ins.get("asm","EXIT"), "arm_count":count})
        Path(str(prefix)+".annotated.txt").write_text("\n".join(annotated)+"\n")
        meta = json.loads(Path(str(prefix)+".json").read_text())
        units.append({**meta, "costs":costs})
    summary.append({"symbol":symbol,"start":start,"end":end,"entries":len(entries),
                    "units":units,"failures":failures})
    print(symbol, "entries", len(entries), "dumps",len(units),"failed",len(failures))
(a.out/"summary.json").write_text(json.dumps(summary,indent=2))
if any(item["failures"] for item in summary): raise SystemExit(1)
