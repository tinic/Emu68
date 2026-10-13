/* Firmware services for an emission-only adapter. Unsupported execution
 * services fail explicitly; none is simulated as successful.
 * SPDX-License-Identifier: MPL-2.0 */
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include "support.h"
#include "M68k.h"
#include "cache.h"
#include "tlsf.h"
#include "support.inc"

extern uintptr_t guest_lo, guest_hi;
extern FILE *map_file;
void *tlsf, *jit_tlsf;
int debug_not_implemented;

static void unsupported(const char *name) {
    fprintf(stderr, "unsupported in emission adapter: %s\n", name); exit(2);
}
static void valid(uint32_t a, unsigned n) {
    if (a < guest_lo || (uintptr_t)a + n > guest_hi) {
        fprintf(stderr, "guest read outside image: %08x + %u\n", a, n); exit(2);
    }
}
uint8_t cache_read_8(enum CacheType t, uint32_t a) {
    (void)t; valid(a, 1); return *(uint8_t *)(uintptr_t)a;
}
uint16_t cache_read_16(enum CacheType t, uint32_t a) {
    (void)t; valid(a, 2); uint16_t v; memcpy(&v, (void *)(uintptr_t)a, 2); return BE16(v);
}
uint32_t cache_read_32(enum CacheType t, uint32_t a) {
    (void)t; valid(a, 4); uint32_t v; memcpy(&v, (void *)(uintptr_t)a, 4); return BE32(v);
}
uint64_t cache_read_64(enum CacheType t, uint32_t a) {
    (void)t; valid(a, 8); uint64_t v; memcpy(&v, (void *)(uintptr_t)a, 8); return BE64(v);
}
void *tlsf_malloc(void *h, uintptr_t n) { (void)h; return malloc(n); }
void tlsf_free(void *h, void *p) { (void)h; free(p); }
uintptr_t tlsf_get_free_size(void *h) { (void)h; return 64 * 1024 * 1024; }
void kprintf(const char *f, ...) {
    va_list a; va_start(a, f); vfprintf(stderr, f, a); va_end(a);
}
void arm_flush_cache(uintptr_t a, uint32_t n) { (void)a; (void)n; }
void arm_icache_invalidate(uintptr_t a, uint32_t n) { (void)a; (void)n; }
void disasm_open(void) {}
void disasm_close(void) {}
void disasm_print(uint16_t *pc, uint16_t count, uint32_t *arm, size_t n, uint32_t *start) {
    fprintf(map_file, "{\"guest_pc\":%u,\"guest_count\":%u,\"arm_offset\":%zu,\"arm_bytes\":%zu}\n",
        (unsigned)(uintptr_t)pc, count, (size_t)(arm-start)*4, n);
}
void EMIT_InjectDebugString(struct TranslatorContext *c, const char *f, ...) {
    (void)c; (void)f; unsupported("debug injection");
}
void EMIT_InjectPrintContext(struct TranslatorContext *c) {
    (void)c; unsupported("context injection");
}
void M68K_PrintContext(void *c) { (void)c; unsupported("print context"); }
void M68K_Exception(void) { unsupported("exception execution"); }
uint32_t EMIT_lineF(struct TranslatorContext *c) { (void)c; unsupported("FPU/LINEF"); return 0; }
uint32_t GetSR_LineF(uint16_t op) { (void)op; return 0; }
void LRU_InvalidateAll(void) {}
void M68K_Init(void) { unsupported("reset"); }
