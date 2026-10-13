from pathlib import Path
import subprocess,json,struct,sys,ctypes,random,time,os
b=Path(os.environ['EMU68_MOVE16_TEST_WORK']);sys.path.insert(0,str(b/'deps'))
from unicorn import Uc,UcError,UC_ARCH_ARM64,UC_MODE_BIG_ENDIAN,UC_HOOK_CODE,UC_HOOK_MEM_READ_UNMAPPED,UC_HOOK_MEM_WRITE_UNMAPPED
from unicorn.arm64_const import *
regs=[UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X2,UC_ARM64_REG_X3,UC_ARM64_REG_X4,UC_ARM64_REG_X5,UC_ARM64_REG_X6,UC_ARM64_REG_X7,UC_ARM64_REG_X8,UC_ARM64_REG_X9,UC_ARM64_REG_X10,UC_ARM64_REG_X11,UC_ARM64_REG_X12,UC_ARM64_REG_X13,UC_ARM64_REG_X14,UC_ARM64_REG_X15,UC_ARM64_REG_X16,UC_ARM64_REG_X17,UC_ARM64_REG_X18,UC_ARM64_REG_X19,UC_ARM64_REG_X20,UC_ARM64_REG_X21,UC_ARM64_REG_X22,UC_ARM64_REG_X23,UC_ARM64_REG_X24,UC_ARM64_REG_X25,UC_ARM64_REG_X26,UC_ARM64_REG_X27,UC_ARM64_REG_X28,UC_ARM64_REG_X29,UC_ARM64_REG_X30]
amap=[13,14,15,16,17,27,28,29];guest=amap+list(range(19,27))+[18]
# Use the patched C branch and original C branch with upstream A64 encoders.
requests=[];keys=[]
for n in range(1,32):
 for s in range(8):
  for d in range(8):
   for f in (0,1):requests.append(f'{f} {n} {n} {s} {d} 1 0 99\n');keys.append((f,n,s,d))
r=subprocess.run([str(b/'emitter-probe')],input=''.join(requests),text=True,capture_output=True,check=True)
corpus=dict(zip(keys,map(json.loads,r.stdout.splitlines())));assert len(corpus)==len(keys)
for (f,n,s,d),entry in corpus.items():
 assert entry['consumed']==n and entry['words_advanced']==2*n
 expected=5*n if s==d else (6*n if not f or n==1 else 2*n+4)
 expected+=n//31
 assert len(entry['words'])==expected,((f,n,s,d),len(entry['words']),expected)
# Recognition/depth/page/changed-register limits, without running device code.
edge=[(1,63,63,0,1,0,0,99),(1,10,3,0,1,0,0,99),(1,4,4,0,1,0,2046,99),(1,4,4,0,1,0,2047,99),(1,4,4,0,1,0,2044,99),(1,4,4,0,1,1,0,2)]
e=subprocess.run([str(b/'emitter-probe')],input=''.join(' '.join(map(str,x))+'\n' for x in edge),text=True,capture_output=True,check=True)
er=list(map(json.loads,e.stdout.splitlines()))
assert [x['groups'] for x in er]==[[31,31,1],[3],[1,3],[1,3],[2,2],[2,1,1]],er

class Machine:
 def __init__(self,mode):
  self.u=Uc(UC_ARCH_ARM64,UC_MODE_BIG_ENDIAN);self.mode=mode;self.codeaddr=0x1000000000;self.u.mem_map(self.codeaddr,4096)
  self.pages={a:(ctypes.c_ubyte*4096)() for a in (0,0x100000,0xfffff000)}
  self.mapped=set()
  for a,page in self.pages.items():
   if mode=='ram' or mode=='mixed' and a==0x100000:
    for virtual in (a,a+0x100000000):self.u.mem_map_ptr(virtual,4096,7,ctypes.addressof(page));self.mapped.add(virtual)
  self.u.hook_add(UC_HOOK_CODE,self.codehook)
  self.u.hook_add(UC_HOOK_MEM_READ_UNMAPPED|UC_HOOK_MEM_WRITE_UNMAPPED,self.faulthook)
 def data(self,a,size=16):
  a&=0xffffffff;page=self.pages[a&~4095];off=a&4095;assert off+size<=4096
  return bytes(page[off:off+size])
 def write(self,a,data):
  a&=0xffffffff;self.pages[a&~4095][a&4095:(a&4095)+len(data)]=data
 def decode(self,pc):
  op=int.from_bytes(self.u.mem_read(pc,4),'little')
  masked=op&0xffc00000
  if masked not in (0xa9400000,0xa9000000):return None
  offset=(op>>15)&127
  if offset&64:offset-=128
  rn=(op>>5)&31;rt=op&31;rt2=(op>>10)&31
  a=self.u.reg_read(regs[rn])+offset*8
  return masked==0xa9400000,a,rt,rt2
 def codehook(self,u,pc,size,data):
  item=self.decode(pc)
  if item:
   load,a,rt,rt2=item
   payload=self.data(a) if load else u.reg_read(regs[rt]).to_bytes(8,'big')+u.reg_read(regs[rt2]).to_bytes(8,'big')
   self.events.append(('read' if load else 'write',a&0xffffffff,payload))
 def faulthook(self,u,access,a,size,value,data):
  self.pending=self.decode(u.reg_read(UC_ARM64_REG_PC));assert self.pending is not None
  self.resume=u.reg_read(UC_ARM64_REG_PC)+4;u.emu_stop();return False
 def run(self,words,s,d,sidx,didx,n):
  for a,page in self.pages.items():page[:]=bytes((i*37+(a>>12)*13+n)&255 for i in range(4096))
  for i,reg in enumerate(regs):self.u.reg_write(reg,0x12345678+i*97)
  if sidx==didx:d=s
  self.u.reg_write(regs[amap[sidx]],s);self.u.reg_write(regs[amap[didx]],d)
  self.u.reg_write(UC_ARM64_REG_NZCV,0xb0000000)
  blob=struct.pack('<'+'I'*len(words),*words);self.u.mem_write(self.codeaddr,blob)
  self.u.ctl_remove_cache(self.codeaddr,self.codeaddr+4096)
  self.events=[];self.pending=None;faults=0;pc=self.codeaddr;end=pc+len(blob)
  while pc<end:
   try:self.u.emu_start(pc,end,count=512)
   except UcError:
    assert self.pending is not None
   if self.pending is None:break
   load,a,rt,rt2=self.pending
   # Serve one paired 16-byte bus access and resume at ELR+4, like vectors.c.
   if load:
    data=self.data(a);self.u.reg_write(regs[rt],int.from_bytes(data[:8],'big'));self.u.reg_write(regs[rt2],int.from_bytes(data[8:],'big'))
   else:self.write(a,self.u.reg_read(regs[rt]).to_bytes(8,'big')+self.u.reg_read(regs[rt2]).to_bytes(8,'big'))
   faults+=1;pc=self.resume;self.pending=None
  state=tuple(self.u.reg_read(regs[i]) for i in guest)+(self.u.reg_read(UC_ARM64_REG_NZCV),)
  expected_s=(s+16*n)&0xffffffff;expected_d=(d+16*n)&0xffffffff
  assert self.u.reg_read(regs[amap[sidx]])==expected_s
  assert self.u.reg_read(regs[amap[didx]])==expected_d
  assert self.u.reg_read(UC_ARM64_REG_NZCV)==0xb0000000
  return state,tuple(bytes(p) for p in self.pages.values()),tuple(self.events),faults

