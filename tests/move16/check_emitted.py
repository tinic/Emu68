from model import *

scenarios=[(0x100003,0x100407),(0x100103,0x100117),(0x100117,0x100103),(0xffffffc3,0x100407),(0x100003,0xffffffc7),(0xffffffc3,0xfffffff7)]
count=0;fault_count=0;t=time.monotonic()
for mode in ('ram','bus','mixed'):
 m=Machine(mode)
 for n in range(1,32):
  for sidx in range(8):
   for didx in range(8):
    for s,d in scenarios:
     a=m.run(corpus[(0,n,sidx,didx)]['words'],s,d,sidx,didx,n)
     z=m.run(corpus[(1,n,sidx,didx)]['words'],s,d,sidx,didx,n)
     assert a[:3]==z[:3],(mode,n,sidx,didx,s,d)
     count+=1;fault_count+=z[3]
 print(json.dumps({'progress_mode':mode,'cases':count,'seconds':round(time.monotonic()-t,2)}),flush=True)
 # Full independent source/destination alignment matrix at short/packet/long runs.
 for n in (1,4,31):
  for so in range(16):
   for do in range(16):
    a=m.run(corpus[(0,n,0,1)]['words'],0x100100+so,0x100110+do,0,1,n)
    z=m.run(corpus[(1,n,0,1)]['words'],0x100100+so,0x100110+do,0,1,n)
    assert a[:3]==z[:3],(mode,n,so,do);count+=1;fault_count+=z[3]
out={'result':'PASS','equivalence_cases':count,'handled_pair_faults_candidate':fault_count,'emitter_cases':len(corpus),'emitter_edges':er,'four_moves_baseline_body':len(corpus[(0,4,0,1)]['words']),'four_moves_fused_body':len(corpus[(1,4,0,1)]['words']),'byte_order':'AArch64 big-endian data / little-endian instructions','checks':['Mapped RAM with true shared backing for 4..8GB aliases','Unmapped simulated bus access decoded and resumed at ARM PC+4','Mixed RAM/bus copies','All 64 source/destination guest-register identity pairs','k=1..31 including wrap and overlapping ranges','Independent 16x16 alignment matrices at k1,4,31','Final guest registers, NZCV, memory and canonical bus-event order','Translation budget, same-register fallback, reserved extension bits, code-page boundaries, changed register termination'], 'limits':['Actual paired-access code is executed; fault servicing is a source-derived model, not a full Emu68 emulator','Whole-firmware integration, real devices, interrupts, self-modifying code and target performance remain unvalidated'],'elapsed_seconds':round(time.monotonic()-t,2)}
(b/'corrected-results.json').write_text(json.dumps(out,indent=2)+'\n')
(b/'emitted-example.json').write_text(json.dumps({'baseline':corpus[(0,4,0,1)],'candidate':corpus[(1,4,0,1)]},indent=2)+'\n')
print(json.dumps({k:v for k,v in out.items() if k!='emitter_edges'},indent=2))

count_pc=0
for seed in (-120,-116,0,4,116,120):
 requests=[(f,n,n,0,1,0,0,99) for n in (1,4,31) for f in (0,1)]
 run=subprocess.run([str(b/'emitter-probe'),str(seed),'flush'],input=''.join(' '.join(map(str,x))+'\n' for x in requests),text=True,capture_output=True,check=True)
 entries=list(map(json.loads,run.stdout.splitlines()))
 for mode in ('ram','bus','mixed'):
  m=Machine(mode)
  for i,n in enumerate((1,4,31)):
   a=m.run(entries[2*i]['words'],0xffffffc3,0x100407,0,1,n)
   z=m.run(entries[2*i+1]['words'],0xffffffc3,0x100407,0,1,n)
   assert a[:3]==z[:3],(seed,mode,n)
   assert m.u.reg_read(regs[18])==(0x12345678+18*97+seed+4*n)&0xffffffff
   count_pc+=1
print(json.dumps({'pc_flush_cases':count_pc,'result':'PASS'}))
