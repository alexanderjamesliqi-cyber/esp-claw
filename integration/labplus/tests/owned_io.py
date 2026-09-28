from pathlib import Path
import tempfile,subprocess
root=Path(__file__).resolve().parents[3]
src=root/'components/claw_capabilities/cap_mpy/src'
test=r'''
#include "mpy_owned_io.h"
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
static int polls;
void cap_mpy_poll_hook(void) { polls++; }
int main(void) {
 char buffer[8192];
 int foreign=open("/dev/null",O_RDONLY);assert(foreign>=0);
 assert(cap_mpy_owned_read(foreign,buffer,1)==-1 && errno==EBADF);
 assert(cap_mpy_owned_write(foreign,buffer,1)==-1 && errno==EBADF);
 assert(cap_mpy_owned_close(foreign)==-1 && fcntl(foreign,F_GETFD)>=0);
 for(int n=0;n<1000;n++) {
  int a=cap_mpy_owned_open("/dev/null",O_RDONLY),b=cap_mpy_owned_open("/dev/null",O_RDONLY);
  DIR *d=cap_mpy_owned_opendir(".");assert(a>=0&&b>=0&&d);
  assert(cap_mpy_owned_open("/dev/null",O_RDONLY)==-1&&errno==EMFILE);
  assert(cap_mpy_owned_opendir(".")==NULL&&errno==EMFILE);
  assert(cap_mpy_owned_closedir(NULL)==-1);
  assert(cap_mpy_owned_read(a,buffer,sizeof(buffer))==0);
  assert(cap_mpy_owned_readdir(d)!=NULL);
  cap_mpy_owned_io_close_all();cap_mpy_owned_io_close_all();
  assert(fcntl(a,F_GETFD)==-1&&fcntl(b,F_GETFD)==-1);
  assert(fcntl(foreign,F_GETFD)>=0);
 }
 assert(polls>=4000);
 int w=cap_mpy_owned_open("/dev/null",O_WRONLY);assert(w>=0);
 assert(cap_mpy_owned_write(w,buffer,sizeof(buffer))==4096);
 cap_mpy_owned_io_close_all();close(foreign);return 0;
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d);(p/'test.c').write_text(test)
 subprocess.run(['cc','-Wall','-Werror','-I'+str(src),str(p/'test.c'),str(src/'mpy_owned_io.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
print('PASS 1000 mixed file/directory ownership cycles, quota, VM cleanup, foreign descriptor protection')
