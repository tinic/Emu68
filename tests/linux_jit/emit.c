/* Linux adapter; the included block translator is generated verbatim.
 * SPDX-License-Identifier: MPL-2.0 */
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <string.h>
#include "translator.inc"

struct M68KState state;
struct M68KState *__m68k_state = &state;
uintptr_t guest_lo, guest_hi;
FILE *map_file;

int main(int argc, char **argv)
{
    if (argc != 4) {
        fprintf(stderr, "usage: emu68-emit IMAGE PC_HEX OUTPUT_PREFIX\n");
        return 2;
    }
    FILE *in = fopen(argv[1], "rb");
    if (!in) { perror(argv[1]); return 2; }
    struct stat st;
    if (fstat(fileno(in), &st)) { perror("fstat"); return 2; }
    guest_lo = 0x10000000;
    size_t size = ((size_t)st.st_size + 0x1ffff) & ~(size_t)0xffff;
    void *memory = mmap((void *)guest_lo, size, PROT_READ | PROT_WRITE,
                       MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
    if (memory == MAP_FAILED) { perror("guest mmap"); return 2; }
    guest_hi = guest_lo + size;
    if (fread(memory, 1, st.st_size, in) != (size_t)st.st_size) return 2;
    fclose(in);
    uint32_t pc = strtoul(argv[2], NULL, 16);
    if (pc < guest_lo || pc >= guest_lo + st.st_size) return 2;
    unsigned depth = getenv("EMU68_JIT_DEPTH") ? strtoul(getenv("EMU68_JIT_DEPTH"),NULL,0) : EMU68_M68K_INSN_DEPTH;
    unsigned loops = getenv("EMU68_JIT_LOOPS") ? strtoul(getenv("EMU68_JIT_LOOPS"),NULL,0) : EMU68_MAX_LOOP_COUNT;
    unsigned ccr = getenv("EMU68_JIT_CCR") ? strtoul(getenv("EMU68_JIT_CCR"),NULL,0) : EMU68_CCR_SCAN_DEPTH;
    if (!depth || depth > 256 || !loops || loops > 16 || ccr > JC2_CCR_SCAN_MASK) return 2;
    state.JIT_CONTROL = ((depth & 255u) << JCCB_INSN_DEPTH) |
        ((loops & 15u) << JCCB_LOOP_COUNT) |
        (EMU68_BRANCH_INLINE_DISTANCE << JCCB_INLINE_RANGE);
    state.JIT_CONTROL2 = ccr << JC2B_CCR_SCAN_DEPTH;
    local_state = calloc(512, sizeof(*local_state));
    uint32_t *arm = mmap((void *)0x20000000, 32768*sizeof(*arm), PROT_READ | PROT_WRITE,
                        MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
    char path[4096];
    snprintf(path, sizeof(path), "%s.map.jsonl", argv[3]);
    map_file = fopen(path, "w");
    if (!map_file || !local_state || arm == MAP_FAILED) return 2;
    disasm = 1; debug = 0;
    size_t bytes = M68K_Translate((void *)(uintptr_t)pc, arm, arm + 32768);
    if (bytes < 4 || arm[bytes/4-1] != 0xffffffffu) return 2;
    bytes -= 4; /* The firmware cache manager excludes the final sentinel. */
    fclose(map_file);
    snprintf(path, sizeof(path), "%s.bin", argv[3]);
    FILE *out = fopen(path, "wb");
    if (!out || fwrite(arm, 1, bytes, out) != bytes) return 2;
    fclose(out);
    snprintf(path, sizeof(path), "%s.json", argv[3]);
    out = fopen(path, "w");
    if (!out) return 2;
    fprintf(out, "{\"pc\":%u,\"guest_low\":%u,\"guest_high\":%u,"
        "\"m68k_instructions\":%u,\"arm_instructions\":%zu,"
        "\"prologue\":%u,\"epilogue\":%u,\"conditionals\":%u,"
        "\"jit_control\":%u,\"jit_control2\":%u,\"executed\":false}\n", pc,
        (unsigned)(uintptr_t)m68k_low, (unsigned)(uintptr_t)m68k_high,
        insn_count, bytes / 4, prologue_size, epilogue_size,
        conditionals_count, state.JIT_CONTROL, state.JIT_CONTROL2);
    fclose(out);
    printf("Emu68 %08x: %u guest instructions -> %zu ARM instructions\n",
           pc, insn_count, bytes / 4);
    munmap(arm, 32768*sizeof(*arm)); free(local_state); munmap(memory, size);
    return 0;
}
