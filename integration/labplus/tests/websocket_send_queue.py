"""Execute the native enqueue path with a bounded host queue; no network allowed."""
from pathlib import Path
import subprocess,tempfile
root=Path(__file__).resolve().parents[3]
s=(root/'components/lua_modules/lua_module_websocket/src/lua_module_websocket.c').read_text()
body=s[s.index('static int ws_send('):s.index('\nstatic int ws_receive(')]
source=r'''
#include <stdlib.h>
#include <string.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <setjmp.h>
#include <assert.h>
#include <stdio.h>
#define WS_MAX_MESSAGE (256*1024)
#define pdTRUE 1
typedef struct { char *data;size_t len; } ws_message_t;
typedef struct {int count;ws_message_t items[32];} queue_t;
typedef struct {void *client;bool connected,failed;atomic_size_t outgoing_bytes;queue_t *outgoing;} ws_object_t;
typedef struct {ws_object_t *w;const char *data;size_t len;} lua_State;
static jmp_buf error;
static ws_object_t *ws_check(lua_State *L){return L->w;}
static const char *ws_failure(ws_object_t *w){return "disconnected";}
static const char *luaL_checklstring(lua_State *L,int i,size_t *n){*n=L->len;return L->data;}
static int luaL_error(lua_State *L,const char *fmt,...){longjmp(error,1);}
#define luaL_argcheck(L,c,i,m) do{if(!(c))luaL_error(L,m);}while(0)
static void lua_pushboolean(lua_State *L,int b){assert(b);}
static int xQueueSend(queue_t *q,ws_message_t *m,int wait){assert(wait==0);if(q->count==32)return 0;q->items[q->count++]=*m;return 1;}
'''+body+r'''
static void clear(ws_object_t *w){for(int i=0;i<w->outgoing->count;i++)free(w->outgoing->items[i].data);w->outgoing->count=0;atomic_store(&w->outgoing_bytes,0);}
int main(void){
 queue_t q={0};ws_object_t w={.client=&q,.connected=true,.outgoing=&q};lua_State L={.w=&w,.data="abc",.len=3};
 for(int i=0;i<32;i++)assert(ws_send(&L)==1);
 assert(w.outgoing_bytes==96 && q.count==32 && !memcmp(q.items[0].data,"abc",3));
 if(!setjmp(error)){ws_send(&L);assert(!"queue overflow accepted");}
 assert(w.outgoing_bytes==96 && q.count==32);clear(&w);
 L.data=calloc(1,WS_MAX_MESSAGE);L.len=WS_MAX_MESSAGE;
 assert(ws_send(&L)==1 && ws_send(&L)==1);
 if(!setjmp(error)){ws_send(&L);assert(!"byte overflow accepted");}
 assert(w.outgoing_bytes==512*1024 && q.count==2);clear(&w);free((void*)L.data);
 w.failed=true;L.data="abc";L.len=3;
 if(!setjmp(error)){ws_send(&L);assert(!"failed connection accepted");}
 assert(q.count==0);puts("PASS: nonblocking outbound enqueue, copied payload, count/byte bounds, failed connection rejection");
}
'''
with tempfile.TemporaryDirectory() as tmp:
 p=Path(tmp);(p/'test.c').write_text(source)
 subprocess.run(['clang','-std=c11','-fsanitize=undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
