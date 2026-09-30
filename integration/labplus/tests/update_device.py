"""Partition safety checks reject unknown layouts and oversized images."""
import importlib.util,struct,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from update_device import validate_partition
entry=lambda sub,offset,size:struct.pack('<HBBII16sI',0x50aa,0,sub,offset,size,b'ota',0)
table=entry(0x10,0x20000,0x500000)+entry(0x11,0x520000,0x500000)+b'\xff'*32
for address in (0x20000,0x520000):validate_partition(table,address,4096)
for t,addr,size in [(table,0x10000,4096),(table,0x20000,0x500001),(table,0x20000,0),(entry(0x10,0x20000,0x400000),0x20000,4096),(b'bad',0x20000,4096)]:
 try:validate_partition(t,addr,size)
 except ValueError:continue
 raise AssertionError('Unsafe partition accepted')
print('PASS: active app slot only, layout and size rejection')
