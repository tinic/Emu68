# TCP RX: assessment of actual Emu68 ARM output

The useful opportunities extend well beyond the Ethernet-header copy. The
strongest code-structure candidates found here are reducing repeated window
calculations and bypassing the general TCP state dispatcher on established
connections. The translator also spends substantial code on condition flags
and translation-unit exits.

## Evidence and limits

Generation ran on `192.168.1.115`, a Raspberry Pi 4 Model B Rev 1.5,
Cortex-A72, AArch64 Linux, GCC 14.2. The translator is Emu68
`d9059de8ec5be48e5599d64f83506f59715aa1ab`. The stack is AmiNetXDuo
`dd1cb22c6d681d99e2f18672b2fbfdf8d1e69b70`, NetX Duo
`2d871dca099603e76487bd14fdabeacdc223b89e`, built with the pinned GCC 16.2
m68k toolchain.

The baseline includes both standalone RX fixtures and the real fat
`-O2 -m68020-60 -mregparm=3 -flto` `tcpprof` executable. The real executable
and all four LTO control/candidate links passed `check-pcrel-exact.py` with
zero mismatches and zero unscanned relocations. The adapter self-test checks
big-endian instruction reads, dead-flag elimination, CMP/BEQ, JSR, RTS, and
mapping sizes. All requested baseline and LTO control/candidate units emitted
successfully: 2,355 units, plus the non-LTO experiments.

These are genuine emitted instruction bytes, disassembled by the Pi's GNU
objdump. The guest tests were not executed. Unit sizes include mutually
exclusive paths and duplicated loop bodies; they are code-cache footprint,
not executed instruction counts or throughput measurements. The Linux adapter
omits the execution dispatcher, peripherals, and guest memory execution.
Source hashes and adapter changes are in `build/linux-jit/source-manifest.json`.

Representative entry units, at default translator settings:

| Image and entry | Guest instructions translated | ARM instructions | Conditional exit blocks |
|---|---:|---:|---:|
| RX fixture: socket packet processing | 65 | 224 | 14 |
| RX fixture: data checking | 32 | 87 | 3 |
| RX fixture: open receive window | 18 | 77 | 5 |
| RX fixture: advertised window wrapper | 3 | 11 | 0 |
| RX fixture: receive-pass completion | 90 | 413 | 28 |
| Real LTO tcpprof: socket packet processing | 235 | 778 | 47 |

The 778-instruction unit is not a 778-instruction cost for one received
packet. An exit can skip most of it. It does show that state validation and
inlining create a large native fragment with many appended exits.

## Calls cost more than a native ARM BL

The advertised-window wrapper starts with two guest setup instructions and
`JSR` to the open-window helper. That JSR emits:

```asm
mov  w4, #target_low
movk w4, #target_high, lsl #16
add  w18, w18, #return_offset
str  w18, [x29, #-4]!
mov  w18, w4
```

Its unit then emits three guest-instruction-counter operations and `RET`.
Thus the call transfer is nine ARM instructions before dispatcher work.
An observed callee return is the guest return-address load plus five unit-exit
instructions: six more. A PC-relative call sometimes saves one instruction;
an indirect call emits three for the guest call itself. All still return to
the execution loop, which checks interrupt state and finds the next unit.

Guest register saves and argument movement are additional costs. In the
open-window helper, restoring one saved D2 with `MOVE.L (SP)+,D2` emits six
ARM instructions because its flags are considered live before RTS. The
actual load is only one of those. MOVEM saves/restores map efficiently to
pairs, but larger guest functions still spill compiler temporaries to the
guest stack; Emu68 does not eliminate those memory operations.

Small pure helpers are therefore good candidates for selective consolidation
or inlining. Blanket inlining is insufficient: LTO already removes the
open-window call in the advertised-window helper, while enlarging the emitted
fragment and its exit list. Decisions should use the final LTO output.

## Repeated window-cap calculation

The window-update decision in `nx_tcp_socket_state_data_check.c` evaluates
`_nx_tcp_socket_rx_window_cap(socket_ptr)` up to three times, when the cap is
nonzero and below the default window. The non-LTO ARM maps show three
separate five-instruction JSR sequences. A local cap snapshot leaves one.
That removes two call/return/dispatcher round trips on that path, in addition
to the duplicate helper work.

LTO already inlines those helpers, so its call count does not fall. It still
reloads the interface/cap and repeats tests inside the decision. The matched
LTO control contains an interface-pointer load at guest `+$72b0`, then another
at `+$72e2` for the same decision. The candidate keeps the pointer and cap in
temporaries. Its complete linked text is 104 bytes smaller than the matched
control. This is a code reduction, not a measured receive-speed increase.

This is the first code candidate to pursue. Snapshot the cap within that
decision, under the existing protection; avoid retaining socket fields across
callbacks that may change them. The relevant cap/default configuration must
be checked before estimating how often the three-evaluation path occurs.

## Established-state dispatch

After the earlier validation and ACK work, the general state switch compiles
to a bounds check, a PC-relative indexed word load, and an indirect JMP.
The observed dispatch sequence costs 23–24 ARM instructions. The JMP causes
a further five-instruction unit exit and a dispatcher lookup.

A temporary source copy tests `NX_TCP_ESTABLISHED` at the existing switch
site and leaves the remaining states in the switch. The common discrimination
becomes a state load, constant, compare, and branch: about 8–9 ARM instructions,
with no indirect-jump unit exit on the established path. The preceding
sequence/window/RST/option checks are still performed.

The matched real LTO control and candidate preserve this distinction. The
control uses its state table at guest `+$8b3e`; the candidate checks established
at `+$8d00` and sends other states to its table. Linked text grows by 12 bytes
against that control. The first entry unit happens to have the same size in
both images because it stops before this decision; comparing only function
entry totals would miss the improvement.

This is the second candidate. It avoids roughly twenty emitted instructions
and one execution-loop transition at that decision. Its effect on the entire
RX workload remains unmeasured.

## Condition flags and narrow operations

A common CMP/branch pair in the actual output is:

```asm
cmp  w20, w19
cset w11, cc
bfi  w6, w11, #1, #1
tbz  w6, #1, exit
add  w18, w18, #guest_pc_delta
```

The compare's result is packed into the guest CCR and the branch tests that
packed bit. Emu68 clears `host_flags` before each guest instruction, so these
adjacent guest operations do not share native NZCV directly. Other cases use
MRS/EOR/BFXIL to reconstruct several guest flags. A first flag operation also
loads the packed SR from a SIMD lane. This is why simple C comparisons can
expand into several ARM instructions.

Narrow guest arithmetic and shifts sometimes cost seven to eleven instructions
for one guest opcode, especially when partial-register semantics and X must
be preserved. The switch's indexed word load itself costs nine in the displayed
unit (ten when it also initializes the CCR), including
sign extension, insertion into the guest D register, and CCR work. Wider
operations are not always cheaper: their live flags and the following paths
determine the expansion.

For guest C, combine equivalent predicates where correctness allows it and
keep rare state/error logic out of a compact common path. For the Emu68 fork,
CMP/Bcc fusion or reliable native-flag lifetime tracking is a substantial
separate opportunity. Simply deleting the `host_flags` reset is unsafe;
guest carry/borrow mapping and every intervening emitted instruction must be
accounted for.

## Amiga locking and cold tails

The real LTO output also contains the port's inlined critical-section code.
For example, guest `+$cfa0`, `ADDQ.B #1,295(A6)`, emits eleven ARM instructions:
address calculation, byte load, shifted arithmetic, byte store, and guest
flag reconstruction. This site is the rare `_tx_amiga_permit_finish` tail,
which restores `TDNestCnt` before calling Exec Permit. The related byte
increments/decrements elsewhere in the emitted RX region cost nine to eleven
instructions depending on the available CCR state.

This explains why counting guest opcodes alone is misleading. The port
deliberately uses one guest read-modify-write instruction to preserve nesting
against interrupts; splitting it into C load/add/store would break that
property. Keep the guest operation intact. A useful next source experiment is
preventing LTO from folding the rare Permit tail into the socket-processing
body, then checking register saves, exits, and common-path code size. That may
save footprint while adding a call on the rare path. No locking or rescheduling
checks should be removed, and these static dumps do not establish how often
the tail executes.

## Loop duplication and JIT depth

The receive-pass completion loop is copied into its translation unit:

| Loop setting | ARM instructions in the same entry unit |
|---|---:|
| Default 8 | 413 |
| 4 | 245 |
| 2 | 161 |
| 1 | 1,169 |

Setting 1 is anomalous. For repeated backward jumps, the translator initializes
`max_rev_jumps` to `loop_count - 1`, then stops only when a predecrement equals
zero. At setting 1 it starts at zero and decrements to -1, so this limit fails
to stop duplication; the instruction-depth limit eventually stops it. Do not
use setting 1 as a small-loop control.

For the real LTO socket-processing entry, depth 64 emits 220 ARM instructions,
depth 128 emits 421, and default depth 256 emits 778. Smaller units reduce
footprint and duplicated exits but require more dispatcher transitions. CCR
scanning is also shortened near unit ends. Static output alone cannot select
the fastest depth or loop setting.

## What should follow

First test the cap snapshot and established-state discrimination independently
for correctness, then inspect their final shipping library output. Next
consider extracting the rare out-of-order, handshake, and error bodies to
reduce guest register pressure and the common fragment's exits. Preserve all
validation and packet-lifetime rules: the TCP header snapshot is needed
because a waiting receiver can consume the packet before processing finishes.

The native-flag and loop-count findings belong to the Emu68 fork. The raw ARM
and annotated mappings are retained under `build/linux-jit/cfg-*`; they support
these assessments without assigning an unmeasured throughput number.

Representative annotated output:

- [Call wrapper](../../build/linux-jit/cfg-o2/__nx_tcp_socket_rx_window_advertised-10000c64.annotated.txt)
- [Original state dispatch](../../build/linux-jit/cfg-o2/__nx_tcp_socket_packet_process-10001790.annotated.txt)
- [Established-state candidate](../../build/linux-jit/cfg-dispatch/__nx_tcp_socket_packet_process-10001794.annotated.txt)
- [Byte nesting update and Exec call](../../build/linux-jit/cfg-lto/__nx_tcp_socket_packet_process-1000cfa0.annotated.txt)

## Integrated stack changes

The subsequent implementation is on AmiNetXDuo and NetX Duo branches
`codex/tcp-rx-jit-codegen`. It applies the cap snapshot and established-state
test, and keeps `_tx_amiga_permit_finish` out of line with `noinline, cold`.
The stack's `docs/plans/emu68-tcp-rx-jit.md` and `emu68-rx-arm/` directory retain
the final shipping-library comparison, annotated snippets, and binary hashes.
That comparison emitted 2,837 units on the Pi without failures. Established
dispatch is 29 ARM instructions including the old unit exit versus 9 after;
linked library text falls by 6,752 bytes. Six targeted host tests pass, including
ACK-driven state changes and receive-queue ownership. Generated ARM remains
unexecuted; these results establish improved code generation, not throughput.
