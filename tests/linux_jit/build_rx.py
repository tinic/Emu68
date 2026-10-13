#!/usr/bin/env python3
"""Cross-build the unchanged AmiNetXDuo receive fixtures and relocate a HUNK.
The image is for JIT emission; its libc stubs are deliberately not executable.
"""
import argparse
import json
from pathlib import Path
import struct
import subprocess

BASE = 0x10000000

def load_hunk(path):
    blob = path.read_bytes()
    at = 0
    def word():
        nonlocal at
        v, = struct.unpack_from(">I", blob, at); at += 4; return v
    def skip(n):
        nonlocal at
        at += n
    assert word() == 1011
    while (n := word()): skip(4*n)
    table, first, last = word(), word(), word()
    assert first == 0 and last + 1 == table
    sizes = []
    for _ in range(table):
        size = word()
        if size >> 30 == 3: word()
        sizes.append((size & 0x3fffffff)*4)
    starts, offset = [], 0
    for size in sizes:
        starts.append(offset)
        offset = (offset + size + 15) & ~15
    image = bytearray(offset)
    symbols, relocs = {}, []
    hunk = 0
    while at < len(blob):
        kind = word() & 0x3fffffff
        if kind in (1001, 1002):
            n = word()*4
            image[starts[hunk]:starts[hunk]+n] = blob[at:at+n]; skip(n)
        elif kind == 1003: word()
        elif kind == 1004:
            while (count := word()):
                target = word()
                relocs.extend((hunk, target, word()) for _ in range(count))
        elif kind == 1008:
            while (n := word()):
                name = blob[at:at+n*4].rstrip(b"\0").decode(); skip(n*4)
                symbols[name] = BASE + starts[hunk] + word()
        elif kind in (1000, 1009): skip(word()*4)
        elif kind == 1010: hunk += 1
        else: raise ValueError(f"unsupported HUNK record {kind} at {at-4:x}")
    assert hunk == table
    for src, dst, off in relocs:
        at = starts[src]+off
        value, = struct.unpack_from(">I", image, at)
        struct.pack_into(">I", image, at, (value + BASE + starts[dst]) & 0xffffffff)
    return image, symbols

p = argparse.ArgumentParser()
p.add_argument("--stack-root", type=Path)
p.add_argument("--cc", type=Path)
p.add_argument("--hunk", type=Path, help="Relocate an existing linked executable")
p.add_argument("--out", type=Path, required=True)
p.add_argument("--opt", choices=["Os", "O2"], default="O2")
p.add_argument("--regparm", choices=["0", "3"], default="3")
p.add_argument("--candidate", choices=["cap", "dispatch"], help="Emission experiment; leaves stack sources untouched")
a = p.parse_args()
a.out.mkdir(parents=True, exist_ok=True)
if a.hunk:
    image, symbols = load_hunk(a.hunk)
    (a.out / "image.bin").write_bytes(image)
    (a.out / "symbols.json").write_text(json.dumps(symbols, indent=2))
    print(len(image), "bytes", len(symbols), "symbols")
    raise SystemExit(0)
if not a.stack_root or not a.cc:
    p.error("--stack-root and --cc are required to build fixtures")
stack = a.stack_root.resolve()
override = a.out / "port_override.h"
override.write_text('''#include "tx_port.h"
#undef TX_DISABLE
#undef TX_RESTORE
UINT _tx_thread_interrupt_disable(void);
VOID _tx_thread_interrupt_restore(UINT);
#define TX_DISABLE tx_saved_posture = _tx_thread_interrupt_disable();
#define TX_RESTORE _tx_thread_interrupt_restore(tx_saved_posture);
''')
runtime = a.out / "emission_stubs.c"
runtime.write_text('''#include <stddef.h>
int printf(const char *f, ...) { (void)f; return 0; }
int puts(const char *s) { (void)s; return 0; }
void *memset(void *p, int v, size_t n) { unsigned char *d=p; while(n--) *d++=v; return p; }
void *memcpy(void *p, const void *q, size_t n) { unsigned char *d=p; const unsigned char *s=q; while(n--) *d++=*s++; return p; }
void *memmove(void *p, const void *q, size_t n) { unsigned char *d=p; const unsigned char *s=q; if(d>s) { while(n) { --n; d[n]=s[n]; } } else while(n--) *d++=*s++; return p; }
int rand(void) { return 7; }
int ami_random_rand(void) { return 7; }
double __muldf3(double a, double b) { (void)b; return a; }
double __divdf3(double a, double b) { (void)b; return a; }
''')
common = ["nx_tcp_socket_rx_window_open", "nx_tcp_socket_rx_window_advertised",
          "nx_tcp_socket_state_data_check", "nx_tcp_socket_create",
          "nx_tcp_timestamp_option_get"]
tests = {"tcp_rxpass": common + ["nx_tcp_receive_pass_begin", "nx_tcp_receive_pass_complete"],
         "tcp_rxflood": common + ["nx_tcp_socket_packet_process"]}
flags = ["-"+a.opt, "-m68020-60", "-mregparm="+a.regparm,
         "-fomit-frame-pointer", "-fno-strict-aliasing", "-fno-builtin",
         "-DNX_INCLUDE_USER_DEFINE_FILE", "-DAMINETXDUO_TCP_TIMESTAMP_OFF",
         "-DAMINETXDUO_TCP_WINDOW_SCALING", "-include", str(override.resolve())]
for inc in ["port/threadx-amiga/inc", "port/netxduo-amiga/inc",
            "third_party/threadx/common/inc", "third_party/netxduo/common/inc", "include"]:
    flags += ["-I"+str(stack/inc)]
for name, core in tests.items():
    dest = a.out / name; dest.mkdir(exist_ok=True)
    sources = [stack/"tests/netstack/host"/("test_"+name+"_host.c")]
    sources += [stack/"third_party/netxduo/common/src"/(s+".c") for s in core]
    sources.append(runtime)
    if a.candidate:
        wanted = "nx_tcp_socket_state_data_check.c" if a.candidate == "cap" else "nx_tcp_socket_packet_process.c"
        for i, src in enumerate(sources):
            if src.name != wanted: continue
            text = src.read_text()
            if a.candidate == "cap":
                at = text.index("    /* Determine if an ACK should be forced out for window update")
                end = text.index("    /* If the incoming packet caused the sequence number", at)
                decision = text[at:end]
                assert decision.count("_nx_tcp_socket_rx_window_cap(socket_ptr)") == 3
                decision = decision.replace("_nx_tcp_socket_rx_window_cap(socket_ptr)", "window_cap")
                text = text[:at] + "    {\n    ULONG window_cap = _nx_tcp_socket_rx_window_cap(socket_ptr);\n" + decision + "    }\n\n" + text[end:]
            else:
                at = text.index("    switch (socket_ptr -> nx_tcp_socket_state)")
                first = text.index("    case  NX_TCP_ESTABLISHED:", at)
                last = text.index("    case  NX_TCP_CLOSE_WAIT:", first)
                body = text[first:last].split(":",1)[1]
                body = body[:body.rindex("        break;")]
                text = text[:first] + text[last:]
                text = text[:at] + "    if (socket_ptr -> nx_tcp_socket_state == NX_TCP_ESTABLISHED)\n    {\n" + body + "    }\n    else\n" + text[at:]
            dst = dest/src.name
            dst.write_text(text)
            sources[i] = dst
    objects = []
    for src in sources:
        obj = dest/(src.stem+".o")
        subprocess.run([str(a.cc), *flags, "-c", str(src), "-o", str(obj)], check=True)
        objects.append(obj)
    exe = dest/(name+".hunk")
    subprocess.run([str(a.cc), "-m68020-60", "-nostdlib", "-Wl,-e,_main",
                    *map(str, objects), "-lgcc", "-o", str(exe)], check=True)
    image, symbols = load_hunk(exe)
    (dest/"image.bin").write_bytes(image)
    (dest/"symbols.json").write_text(json.dumps(symbols, indent=2))
    objdump = a.cc.with_name("m68k-amigaos-objdump")
    dis = subprocess.check_output([str(objdump), "-d", "-m", "m68k:68020", str(exe)], text=True)
    (dest/"guest.s").write_text(dis)
    (dest/"build.json").write_text(json.dumps({"opt": a.opt, "regparm": a.regparm, "candidate":a.candidate,
        "flags": flags, "sources": list(map(str, sources)), "execution_stubs": True}, indent=2))
    print(name, len(image), "bytes", len(symbols), "symbols")
