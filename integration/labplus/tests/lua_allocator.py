from pathlib import Path
import subprocess,tempfile
root=Path(__file__).resolve().parents[3]
s=(root/'components/claw_capabilities/cap_lua/src/cap_lua_runtime.c').read_text()
a=s.index('#define CAP_LUA_VM_MEMORY_LIMIT');b=s.index('static const char *TAG',a)
source='''#include <stdlib.h>
#include <stdint.h>
#include <assert.h>
static int fail_alloc;
static void *heap_caps_realloc(void *p,size_t n,uint32_t c) { (void)c;return fail_alloc ? NULL:realloc(p,n); }
#define heap_caps_free free
'''+s[a:b]+'''
int main(void) {
 cap_lua_allocator_t a={0};
 for(int i=0;i<10000;i++) {
  void *p=cap_lua_bounded_alloc(&a,NULL,6,64);assert(p && a.used==64);
  p=cap_lua_bounded_alloc(&a,p,64,1024);assert(p && a.used==1024);
  fail_alloc=1;assert(!cap_lua_bounded_alloc(&a,p,1024,2048));assert(a.used==1024);fail_alloc=0;
  assert(!cap_lua_bounded_alloc(&a,NULL,0,CAP_LUA_VM_MEMORY_LIMIT));
  cap_lua_bounded_alloc(&a,p,1024,0);assert(a.used==0);
 }
 assert(!cap_lua_bounded_alloc(&a,NULL,0,CAP_LUA_VM_MEMORY_LIMIT+1));
 return 0;
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d)/'test.c';p.write_text(source);exe=Path(d)/'test'
 subprocess.run(['cc','-Wall','-Werror','-fsanitize=undefined',str(p),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
print('PASS: real Lua allocator, 10000 allocate/reallocate/free cycles, rollback on failure and hard budget')
