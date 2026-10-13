# MOVE16 emitter regression checks

Run with Python 3, Unicorn 2.x and a host C compiler supporting `-std=gnu2x`:

```sh
python3 tests/move16/run.py
```

`CC` selects the host compiler. The runner creates and removes a temporary
directory under `build/`; it does not build, install or boot firmware.

The probe extracts the current postincrement MOVE16 branch, TranslatorContext,
AdvancePC/FlushPC and A64 encoders directly from the source. The reference is
the pre-fusion postincrement branch retained in `baseline-branch.txt`.
Register-allocation stubs use Emu68's fixed guest-register mappings.

The suite checks 3,968 emitter cases and executes 38,016 big-endian AArch64
equivalence cases: all source/destination guest registers, lengths 1..31,
shared-register fallback, overlaps, all alignment pairs, wrapping addresses,
translation budgets, code-page boundaries and changed-register termination.
Shared physical backing models Emu68's 4..8 GB alias. A paired-access fault
hook models canonicalization and resume at ARM PC+4; RAM, bus and mixed paths
compare final guest registers, NZCV, bytes and access order. Another 54 cases
check deferred PC updates through the real FlushPC emitter.

This is a bounded bus model. It does not validate full device behavior,
interrupts, unhandled faults or firmware integration. Native Cortex-A72 copy
measurements showed 24.2% less time for a hot 1472-byte body, with no material
gain for repeated 1 MiB copies; those are not network throughput results.
