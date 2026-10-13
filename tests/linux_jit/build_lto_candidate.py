#!/usr/bin/env python3
"""Relink tcpprof with one experimental source object before the NetX archive.
Production sources and archives are left untouched. The usual relocation check
is required before accepting the linked analysis image.
"""
import argparse
import json
from pathlib import Path
import shlex
import subprocess

p=argparse.ArgumentParser()
p.add_argument("--stack-build", type=Path, required=True)
p.add_argument("--source", type=Path, required=True)
p.add_argument("--out", type=Path, required=True)
a=p.parse_args()
build=a.stack_build.resolve(); source=a.source.resolve(); out=a.out.resolve()
out.mkdir(parents=True,exist_ok=True)
commands=json.loads((build/"compile_commands.json").read_text())
entry=next(e for e in commands if Path(e["file"]).name==source.name)
compile_args=shlex.split(entry["command"])
compile_args[compile_args.index("-o")+1]=str(out/"candidate.o")
compile_args[compile_args.index("-c")+1]=str(source)
subprocess.run(compile_args,cwd=entry["directory"],check=True)
link_dir=build/"tests/perf/prof"
link=shlex.split((link_dir/"CMakeFiles/tcpprof.dir/link.txt").read_text())
link[link.index("-o")+1]=str(out/"linked.hunk")
for i,arg in enumerate(link):
    if arg.startswith("-Wl,-Map="): link[i]="-Wl,-Map="+str(out/"linked.map")
link.insert(link.index("CMakeFiles/tcpprof.dir/tcpprof.c.obj")+1,str(out/"candidate.o"))
subprocess.run(link,cwd=link_dir,check=True)
stack=Path(entry["file"]).parents[4]
subprocess.run(["python3",str(stack/"tools/check-pcrel-exact.py"),
    str(out/"linked.hunk"),str(out/"linked.map"),str(link_dir)],check=True)
subprocess.run(["python3",str(Path(__file__).with_name("build_rx.py")),
    "--hunk",str(out/"linked.hunk"),"--out",str(out)],check=True)
objdump=Path(compile_args[0]).with_name("m68k-amigaos-objdump")
(out/"guest.s").write_text(subprocess.check_output([str(objdump),"-d","-m","m68k:68020",str(out/"linked.hunk")],text=True))
(out/"build.json").write_text(json.dumps({"source":str(source),"compile":compile_args,"link":link,"executed":False},indent=2))
