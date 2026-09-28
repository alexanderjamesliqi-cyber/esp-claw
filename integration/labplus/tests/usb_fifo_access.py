"""Exercise the compiled P4 FIFO writer against a destructive-read MMIO model."""
from pathlib import Path
import tempfile,subprocess,os
idf=Path(os.environ.get('IDF_PATH','/Users/james/esp32-build/esp-idf-v5.5.4'))
text=(idf/'components/hal/esp32p4/include/hal/usb_serial_jtag_ll.h').read_text()
start=text.index('static inline int usb_serial_jtag_ll_write_txfifo(')
end=text.index('\n}',start)+2
function=text[start:end]
source=r'''
#include <stdint.h>
#include <assert.h>
#include <string.h>
static int pending_rx=16, consumed_rx=0;
static uint8_t sent[16]; static unsigned sent_count;
struct destructive_fifo {
 operator uint32_t() const { if(pending_rx>0){--pending_rx;++consumed_rx;} return 0; }
 void operator=(uint32_t value) { sent[sent_count++]=value; }
};
struct ep { destructive_fifo val; };
struct { ep ep1; struct { bool serial_in_ep_data_free; } ep1_conf; } USB_SERIAL_JTAG;
#define HAL_FORCE_MODIFY_U32_REG_FIELD(reg, field, value) do { uint32_t old=(reg).val; (reg).val=(old&~255u)|(value); } while(0)
'''+function+r'''
int main(){
 USB_SERIAL_JTAG.ep1_conf.serial_in_ep_data_free=true;
 const uint8_t bytes[]={0,1,127,128,255};
 assert(usb_serial_jtag_ll_write_txfifo(bytes,5)==5);
 assert(sent_count==5 && memcmp(sent,bytes,5)==0);
 assert(pending_rx==16 && consumed_rx==0);
 USB_SERIAL_JTAG.ep1_conf.serial_in_ep_data_free=false;
 assert(usb_serial_jtag_ll_write_txfifo(bytes,5)==0);
 assert(sent_count==5 && consumed_rx==0);
}
'''
with tempfile.TemporaryDirectory() as directory:
 p=Path(directory);(p/'test.cpp').write_text(source)
 subprocess.run(['c++','-std=c++17','-Wall','-Werror',str(p/'test.cpp'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
 # Confirm the regression test catches the former destructive read-modify-write.
 old=source.replace('USB_SERIAL_JTAG.ep1.val = buf[i];','HAL_FORCE_MODIFY_U32_REG_FIELD(USB_SERIAL_JTAG.ep1, rdwr_byte, buf[i]);')
 assert old!=source
 (p/'old.cpp').write_text(old)
 subprocess.run(['c++','-std=c++17',str(p/'old.cpp'),'-o',str(p/'old')],check=True)
 assert subprocess.run([str(p/'old')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode!=0
print('PASS P4 FIFO TX preserves pending RX bytes; former RMW implementation fails this test')
