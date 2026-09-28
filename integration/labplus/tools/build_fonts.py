from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
import json
root=Path(__file__).resolve().parents[1];out=root/'sdcard/labplus/fonts';out.mkdir(exist_ok=True)
cjk=ImageFont.truetype(str(root/'assets/NotoSansSC.ttf'),22);cjk.set_variation_by_axes([500])
mono=ImageFont.truetype(str(root/'assets/RobotoMono.ttf'),20);mono.set_variation_by_axes([500])
def raster(cp,size,cjk,mono):
 im=Image.new('L',(size,size));d=ImageDraw.Draw(im)
 d.text((1,size-3),chr(cp),font=mono if cp<128 else cjk,fill=255,anchor='ls')
 data=im.tobytes();return bytes(((data[i]//17)<<4)|(data[i+1]//17) for i in range(0,len(data),2))
ranges=[[32,126],[0x2000,0x206f],[0x3000,0x30ff],[0x3400,0x9fff],[0xff00,0xffef]]
data=bytearray();shard=0;count=0
for a,b in ranges:
 for cp in range(a,b+1):
  data+=raster(cp,24,cjk,mono);count+=1
  if count%1024==0:
   (out/('body-%02d.bin'%shard)).write_bytes(data);data=bytearray();shard+=1
if data:(out/('body-%02d.bin'%shard)).write_bytes(data)
cp_set=set(range(32,127))
for p in (root/'sdcard').rglob('*.lua'):cp_set.update(ord(c) for c in p.read_text() if ord(c)>127)
cjk32=ImageFont.truetype(str(root/'assets/NotoSansSC.ttf'),30);cjk32.set_variation_by_axes([600])
mono32=ImageFont.truetype(str(root/'assets/RobotoMono.ttf'),26);mono32.set_variation_by_axes([600])
index={str(cp):i for i,cp in enumerate(sorted(cp_set))}
(out/'heading.bin').write_bytes(b''.join(raster(cp,32,cjk32,mono32) for cp in sorted(cp_set)))
(out/'heading.json').write_text(json.dumps(index))
(out/'manifest.json').write_text(json.dumps({'body_size':24,'heading_size':32,'alpha_bits':4,'ranges':ranges,'shard_glyphs':1024,'glyph_count':count,'font':'Noto Sans SC Medium / Roboto Mono Medium','license':'SIL Open Font License 1.1'},indent=2))
print('Font glyphs',count,'shards',shard+1,'heading',len(index),flush=True)
