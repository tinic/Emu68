#!/usr/bin/env python3
"""Known integer opcodes validate endian reads, CCR scanning, and map offsets."""
import argparse
import json
from pathlib import Path
import struct
import subprocess
import tempfile

p=argparse.ArgumentParser()
p.add_argument("emitter",type=Path)
a=p.parse_args()
with tempfile.TemporaryDirectory() as tmp:
    d=Path(tmp)
    image=bytearray(1024)
    struct.pack_into(">7H",image,0,0x7001,0x7202,0xb081,0x6702,0x4a80,0x4a80,0x4e75)
    struct.pack_into(">HIH",image,0x100,0x4eb9,0x10000120,0x4e75)
    struct.pack_into(">2H",image,0x120,0x7007,0x4e75)
    (d/"image.bin").write_bytes(image)
    cases=[(0,{0:1,2:1,4:4,6:2}), (0x100,{0x100:5}), (0x122,{0x122:1})]
    for entry,expected in cases:
        prefix=d/f"unit-{entry:x}"
        subprocess.run([str(a.emitter),str(d/"image.bin"),f"{0x10000000+entry:x}",str(prefix)],check=True,capture_output=True)
        rows=[json.loads(x) for x in Path(str(prefix)+".map.jsonl").read_text().splitlines()]
        counts={r['guest_pc']-0x10000000:r['arm_bytes']//4 for r in rows if r['guest_pc']}
        for pc,n in expected.items(): assert counts[pc]==n,(pc,counts[pc],n)
        meta=json.loads(Path(str(prefix)+".json").read_text())
        assert Path(str(prefix)+".bin").stat().st_size == 4*meta['arm_instructions']
        assert sum(r['arm_bytes'] for r in rows) == 4*meta['arm_instructions']
    print("emission adapter: endian reads, dead flags, CMP/BEQ, JSR, RTS, and map sizes PASS")
