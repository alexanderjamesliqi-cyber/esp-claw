"""Exercise the actual receive callback's fragment, queue and byte limits."""
from pathlib import Path
import re,subprocess,tempfile
root=Path(__file__).resolve().parents[3]
s=(root/'components/lua_modules/lua_module_websocket/src/lua_module_websocket.c').read_text()
body=s[s.index('#define WS_META'):s.index('\nstatic ws_object_t *ws_check')]
# Host stubs implement a bounded queue; no network or ESP-IDF is involved.
preamble=r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdatomic.h>
#include <assert.h>
#include <stdio.h>
typedef int esp_err_t;
typedef esp_err_t (*lua_websocket_auth_provider_t)(const char *,char *,size_t);
typedef void *SemaphoreHandle_t;
typedef void *esp_websocket_client_handle_t;
typedef void *esp_event_base_t;
typedef struct {int op_code,data_len,payload_offset,payload_len,fin;const char *data_ptr;} esp_websocket_event_data_t;
typedef struct {size_t count;} queue_t;
typedef queue_t *QueueHandle_t;
#define WEBSOCKET_EVENT_CONNECTED 1
#define WEBSOCKET_EVENT_DISCONNECTED 2
#define WEBSOCKET_EVENT_ERROR 3
#define WEBSOCKET_EVENT_DATA 4
#define pdTRUE 1
static int xQueueSend(QueueHandle_t q,void *message,int wait);
'''
end=r'''
static ws_message_t messages[WS_QUEUE_LENGTH];
static int xQueueSend(QueueHandle_t q,void *p,int wait){if(q->count==WS_QUEUE_LENGTH)return 0;messages[q->count++]=*(ws_message_t*)p;return 1;}
static void clear(queue_t *q){for(size_t i=0;i<q->count;i++)free(messages[i].data);q->count=0;}
int main(void){
 queue_t q={0};ws_object_t w={.queue=&q};
 esp_websocket_event_data_t e={.op_code=1,.data_len=3,.payload_len=3,.fin=1,.data_ptr="abc"};
 for(int i=0;i<64;i++)ws_event(&w,NULL,WEBSOCKET_EVENT_DATA,&e);
 assert(!w.failed && q.count==64 && w.queued_bytes==192);
 for(int i=64;i<=WS_QUEUE_LENGTH;i++)ws_event(&w,NULL,WEBSOCKET_EVENT_DATA,&e);
 assert(w.failed && w.failure_reason==2 && q.count==WS_QUEUE_LENGTH);
 clear(&q);memset(&w,0,sizeof(w));w.queue=&q;
 w.queued_bytes=WS_MAX_QUEUED_BYTES-1;
 ws_event(&w,NULL,WEBSOCKET_EVENT_DATA,&e);assert(w.failed && q.count==0 && w.queued_bytes==WS_MAX_QUEUED_BYTES-1);
 memset(&w,0,sizeof(w));w.queue=&q;e.payload_len=6;e.fin=0;
 ws_event(&w,NULL,WEBSOCKET_EVENT_DATA,&e);assert(q.count==0);
 e.payload_offset=3;e.fin=1;e.data_ptr="def";ws_event(&w,NULL,WEBSOCKET_EVENT_DATA,&e);
 assert(q.count==1 && messages[0].len==6 && !memcmp(messages[0].data,"abcdef",6));clear(&q);
 puts("PASS: burst over 32 messages, bounded count/bytes, fragment assembly");
}
'''
with tempfile.TemporaryDirectory() as tmp:
 p=Path(tmp);(p/'test.c').write_text(preamble+body+end)
 subprocess.run(['clang','-std=c11','-fsanitize=undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
