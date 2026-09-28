"""A delayed second CRLF prompt must not acknowledge the following command."""
from pathlib import Path
import importlib.util
p=Path(__file__).resolve().parents[1]/'tools/device.py'
spec=importlib.util.spec_from_file_location('device_under_test',p);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class Port:
 def __init__(self,*a,**k):self.packets=[];self.delayed=False;self.input=b''
 def open(self):pass
 def close(self):pass
 def write(self,data):
  if data==b'\r\n':self.packets.append(b'app> ');self.delayed=True;return
  if data==b'\n' and not self.input:self.packets.append(b'app> ');return
  self.input+=data
  if self.input.endswith(b'\n'):
   if self.delayed:self.packets.append(b'app> ');self.delayed=False
   self.packets.append(self.input+b'CURRENT_REPLY\napp> ');self.input=b''
 def read(self,n):return self.packets.pop(0) if self.packets else b''
module.serial.Serial=Port
current=module.Device();assert 'CURRENT_REPLY' in current.command('test');current.close()
# Exercise the former CRLF handshake and immediate command write.
old=Port();old.write(b'\r\n');assert old.read(100)==b'app> ';old.write(b'test\n')
assert old.read(100)==b'app> ' # premature success, actual reply remains unread
print('PASS: delayed duplicate prompt breaks old handshake; single-newline synchronization returns current reply')
