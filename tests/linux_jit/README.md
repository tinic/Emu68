# Linux JIT emission adapter

This AArch64 Linux tool calls Emu68's real block translator and integer opcode
emitters. It loads a relocated big-endian m68k image at a 32-bit address and
writes the generated little-endian AArch64 instruction bytes, metadata, and a
guest-PC-to-ARM mapping. It does **not** execute the generated program.

The complete block translator is extracted verbatim from `M68k_Translator.c`.
The original register allocator, condition-code scanner, effective-address
code, exception emitter, and integer emitters are compiled directly. Firmware
allocation and instruction-cache reads have Linux shims. One DBcc scanner
read that assumes a big-endian host is changed to use `cache_read_16`; its
numeric meaning is preserved. FPU/LINEF translation fails explicitly.

Defaults match this revision's startup configuration: instruction depth 256,
loop count 8, CCR scan depth 20, inline range 8191. `EMU68_JIT_DEPTH`,
`EMU68_JIT_LOOPS`, and `EMU68_JIT_CCR` override them for emission experiments.
The firmware's final sentinel is excluded from `.bin` and instruction counts.

On an AArch64 Linux machine:

```sh
python3 tests/linux_jit/build.py
python3 tests/linux_jit/selftest.py build/linux-jit/emu68-emit
```

On the machine holding the stack and m68k toolchain:

```sh
python3 tests/linux_jit/build_rx.py \
  --stack-root /path/to/AmiNetXDuo \
  --cc /path/to/bin/m68k-amigaos-gcc \
  --out build/linux-jit/guest-o2
```

This compiles the existing `tcp_rxpass` and `tcp_rxflood` fixture sources at
`-O2 -m68020-60 -mregparm=3`, using the Amiga structure layouts. The fixture's
interrupt operations are stubbed as in the host test; libc and diagnostic
floating-point routines are emission-only stubs. These images must not be
treated as runnable correctness tests. `--candidate cap` and
`--candidate dispatch` create experimental source copies in the output
directory; they never edit the stack checkout.

An existing fully linked executable, including `tcpprof`, can be relocated
with `build_rx.py --hunk FILE --out DIRECTORY`. Save its m68k disassembly as
`DIRECTORY/guest.s`, using `m68k-amigaos-objdump -d -m m68k:68020 FILE`.
`build_lto_candidate.py` can relink a configured `tcpprof` with one replacement
source object. It requires the project's relocation check to pass and supports
an unmodified-source control through the same link procedure.

Transfer the image directory to Linux, then generate annotated RX dumps:

```sh
python3 tests/linux_jit/dump_rx.py \
  --emitter build/linux-jit/emu68-emit \
  --guest build/linux-jit/guest-o2/tcp_rxflood \
  --out build/linux-jit/cfg-o2 \
  --symbols __nx_tcp_socket_packet_process __nx_tcp_socket_state_data_check
```

Each unit has `.bin`, `.arm.s`, `.map.jsonl`, `.json`, and `.annotated.txt`
files. The latter puts each m68k instruction beside the ARM instructions it
emitted. Function entries, conditional successors, call continuations, and
recognized bounded switch targets are explored. LTO static symbols can be
missing; a displayed nearest symbol is not always the source function's name.
This is static coverage, not a trace of a packet's executed path.

See [ASSESSMENT.md](ASSESSMENT.md) for the Pi-generated RX findings.
