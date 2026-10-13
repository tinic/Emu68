from pathlib import Path
import re,subprocess,os
r=Path(__file__).resolve().parents[2];b=Path(os.environ['EMU68_MOVE16_TEST_WORK']);b.mkdir(parents=True,exist_ok=True)
a=(r/'include/A64.h').read_text();a=a[:a.index('#include <RegisterAllocator.h>')]+ '\n#endif\n';(b/'A64-encoders.h').write_text(a)
ctx=(r/'include/M68k.h').read_text();ctx=ctx[ctx.index('struct TranslatorContext {'):];ctx=ctx[:ctx.index('\n};')+3]
def body(t):return t[t.index('    {'):t.rfind('\n    }')+6]
base=body((Path(__file__).parent/'baseline-branch.txt').read_text())
linef=(r/'src/M68k_LINEF.c').read_text();start=linef.index('    /* MOVE16 (Ax)+, (Ay)+ */',linef.index('uint32_t EMIT_lineF'));end=linef.index('    /* MOVE16 other variations */',start);cand=body(linef[start:end])
t=(r/'src/M68k_Translator.c').read_text();pc=t[t.index('void EMIT_AdvancePC('):t.index('\nvoid EMIT_ResetOffsetPC(')]
s='''#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include <stdarg.h>
#include <stdint.h>
#include <string.h>
'''+ctx+'''
#include "A64-encoders.h"
#define ICACHE 0
#define REG_PC 18
static unsigned pool,pc_updates;
static int _pc_rel;
static const unsigned amap[]={13,14,15,16,17,27,28,29};
uint8_t host_flags;
void kprintf(const char *f,...){(void)f;abort();}
static uint16_t cache_read_16(int ignored,uintptr_t address){(void)ignored;return *(uint16_t*)address;}
static uint8_t RA_AllocARMRegister(struct TranslatorContext *ctx){(void)ctx;assert(pool<4);return 4+pool++;}
static uint8_t RA_MapM68kRegister(struct TranslatorContext *ctx,uint8_t i){(void)ctx;assert(i>=8&&i<16);return amap[i-8];}
static void RA_FreeARMRegister(struct TranslatorContext *ctx,uint8_t i){(void)ctx;(void)i;}
static void RA_SetDirtyM68kRegister(struct TranslatorContext *ctx,uint8_t i){(void)ctx;(void)i;}
'''+pc+'''
static unsigned baseline(struct TranslatorContext *ctx){
 unsigned insn_consumed=1;unsigned opcode=ctx->tc_M68kCodePtr[0],opcode2=ctx->tc_M68kCodePtr[1];
'''+base+'''
 return insn_consumed;
}
static unsigned candidate(struct TranslatorContext *ctx){
 unsigned insn_consumed=1;unsigned opcode=ctx->tc_M68kCodePtr[0],opcode2=ctx->tc_M68kCodePtr[1];
'''+cand+'''
 return insn_consumed;
}
int main(int argc, char **argv){
 unsigned fused,n,remaining,s,d,exts,offset,changed;
 uint16_t *page;assert(!posix_memalign((void**)&page,4096,8192));
 while(scanf("%u %u %u %u %u %u %u %u",&fused,&n,&remaining,&s,&d,&exts,&offset,&changed)==8){
  assert(n>=1&&n<=63&&s<8&&d<8&&offset<2048&&remaining>0);
  memset(page,0,8192);uint16_t *start=page+offset;
  for(unsigned i=0;i<n;i++){start[2*i]=0xf620+s;start[2*i+1]=0x8000+(d<<12)+(exts?((i*73+0x812)&0x8fff):0);}
  if(changed<n)start[2*changed+1]^=0x1000;
  uint32_t words[512]={0};struct TranslatorContext c={.tc_CodeStart=words,.tc_CodeEnd=words+512,.tc_CodePtr=words,.tc_M68kCodeStart=start,.tc_M68kCodePtr=start};
  unsigned consumed=0,groups[64]={0},ng=0;_pc_rel=argc>1?atoi(argv[1]):0;pc_updates=0;
  while(consumed<n && consumed<remaining){
   pool=0;c.tc_M68kInsnRemaining=remaining-consumed;
   unsigned k=fused?candidate(&c):baseline(&c);groups[ng++]=k;consumed+=k;
  }
  if(argc>2)EMIT_FlushPC(&c);\n  printf("{\\"consumed\\":%u,\\"words_advanced\\":%lu,\\"pc_relative\\":%d,\\"groups\\":[",consumed,(unsigned long)(c.tc_M68kCodePtr-start),_pc_rel);
  for(unsigned i=0;i<ng;i++)printf("%s%u",i?",":"",groups[i]);
  printf("],\\"words\\":[");for(unsigned i=0;i<(unsigned)(c.tc_CodePtr-words);i++)printf("%s%u",i?",":"",words[i]);puts("]}");
 }
 free(page);return 0;
}
'''
# C source needs ordinary escaped double quotes, not backslash+backslash.
s=s.replace('\\\\"','\\"')
(b/'emitter-probe.c').write_text(s)
subprocess.run([os.environ.get('CC','cc'),'-std=gnu2x','-O2','-Wall','-Wextra',str(b/'emitter-probe.c'),'-o',str(b/'emitter-probe')],check=True)
