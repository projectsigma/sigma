"""Turn the project's existing multi-resolution PNG-backed ICO into a Win32 .res.
Only required builtins; reproducible, lossless reproduction of SIGMA logo icon.
"""
import struct
from pathlib import Path
src=Path(__file__).with_name('sigma.ico').read_bytes()
assert struct.unpack_from('<HH',src,0)==(0,1)
num=struct.unpack_from('<H',src,4)[0]
assert 1<=num<=32
records=[]
icon_group=struct.pack('<HHH',0,1,num)
for i in range(num):
  w,h,colors,rs,planes,bpp,sz,off=struct.unpack_from('<BBBBHHII',src,6+16*i)
  blob=src[off:off+sz]
  assert len(blob)==sz and blob[:8]==b'\x89PNG\r\n\x1a\n'
  records.append((3,i+1,blob))
  icon_group+=struct.pack('<BBBBHHIH',w,h,colors,rs,planes,bpp,sz,i+1)
records.append((14,1,icon_group))
def record(typ,name,data,lang=1033):
  # Windows .RES record: DATA size, HEADER size, numeric type/name, metadata.
  hdr=struct.pack('<IIHHHHIHHII',len(data),32,0xffff,typ,0xffff,name,0,0x0030,lang,0,0)
  assert len(hdr)==32
  return hdr+data+b'\0'*((-len(data))&3)
# The conventional null entry starts a .res file.
blank=record(0,0,b'')
Path(__file__).with_name('sigma.res').write_bytes(blank+b''.join(record(*r) for r in records))
print('resource bytes',len(blank)+sum(len(record(*r)) for r in records),'icon sizes',num)
