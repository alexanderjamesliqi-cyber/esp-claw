#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include "spark_identity.h"
#include "esp_http_client.h"
#include "esp_crt_bundle.h"
#include "mbedtls/sha256.h"
#include "mbedtls/base64.h"

typedef struct { char data[2048]; size_t used; } challenge_buffer_t;
static esp_err_t collect(esp_http_client_event_t *event)
{
    challenge_buffer_t *buffer=event->user_data;
    if(event->event_id==HTTP_EVENT_ON_DATA){
        if(event->data_len<0 || buffer->used+(size_t)event->data_len>=sizeof(buffer->data))return ESP_ERR_INVALID_SIZE;
        memcpy(buffer->data+buffer->used,event->data,event->data_len);buffer->used+=event->data_len;buffer->data[buffer->used]=0;
    }
    return ESP_OK;
}
esp_err_t spark_relay_authorize(const char *body,char digest_hex[65],char **authorization)
{
    if(!body||!digest_hex||!authorization)return ESP_ERR_INVALID_ARG;
    *authorization=NULL;
    unsigned char digest[32];
    if(mbedtls_sha256((const unsigned char*)body,strlen(body),digest,0)!=0)return ESP_FAIL;
    for(size_t i=0;i<32;i++)snprintf(digest_hex+i*2,3,"%02x",digest[i]);
    spark_identity_handle_t identity=NULL;
    esp_err_t err=spark_identity_create(&identity);
    if(err!=ESP_OK)return err;
    cJSON *info=NULL,*request=NULL,*challenge=NULL,*proof=NULL;
    char *payload=NULL,*proof_text=NULL;esp_http_client_handle_t client=NULL;
    challenge_buffer_t *buffer=calloc(1,sizeof(*buffer));
    if(!buffer){err=ESP_ERR_NO_MEM;goto done;}
    if((err=spark_identity_get_info(identity,&info))!=ESP_OK)goto done;
    request=cJSON_CreateObject();
    if(!request || !cJSON_AddStringToObject(request,"deviceId",cJSON_GetObjectItemCaseSensitive(info,"deviceId")->valuestring) || !cJSON_AddStringToObject(request,"requestHash",digest_hex)) {err=ESP_ERR_NO_MEM;goto done;}
    payload=cJSON_PrintUnformatted(request);
    if(!payload){err=ESP_ERR_NO_MEM;goto done;}
    esp_http_client_config_t *cfg=calloc(1,sizeof(*cfg));
    if(!cfg){err=ESP_ERR_NO_MEM;goto done;}
    cfg->url="https://spark.mpython.cn/v1/auth/challenge";cfg->timeout_ms=10000;
    cfg->crt_bundle_attach=esp_crt_bundle_attach;cfg->event_handler=collect;cfg->user_data=buffer;
    cfg->disable_auto_redirect=true;
    client=esp_http_client_init(cfg);free(cfg);
    if(!client){err=ESP_FAIL;goto done;}
    esp_http_client_set_method(client,HTTP_METHOD_POST);
    esp_http_client_set_header(client,"Content-Type","application/json");
    esp_http_client_set_post_field(client,payload,strlen(payload));
    err=esp_http_client_perform(client);
    if(err!=ESP_OK || esp_http_client_get_status_code(client)!=200){err=ESP_FAIL;goto done;}
    challenge=cJSON_Parse(buffer->data);
    cJSON *message=cJSON_GetObjectItemCaseSensitive(challenge,"message"),*id=cJSON_GetObjectItemCaseSensitive(challenge,"id");
    if(!cJSON_IsString(message)||!cJSON_IsString(id)||strlen(id->valuestring)!=32){err=ESP_FAIL;goto done;}
    err=spark_identity_sign(identity,message->valuestring,&proof);
    if(err!=ESP_OK)goto done;
    if(!cJSON_AddStringToObject(proof,"challengeId",id->valuestring)){err=ESP_ERR_NO_MEM;goto done;}
    proof_text=cJSON_PrintUnformatted(proof);
    if(!proof_text){err=ESP_ERR_NO_MEM;goto done;}
    size_t size=((strlen(proof_text)+2)/3)*4+8,written=0;
    char *header=calloc(1,size);
    if(!header){err=ESP_ERR_NO_MEM;goto done;}
    memcpy(header,"Bearer ",7);
    if(mbedtls_base64_encode((unsigned char*)header+7,size-7,&written,(const unsigned char*)proof_text,strlen(proof_text))!=0){free(header);err=ESP_FAIL;goto done;}
    *authorization=header;err=ESP_OK;
done:
    if(client)esp_http_client_cleanup(client);
    free(buffer);free(payload);free(proof_text);
    cJSON_Delete(request);cJSON_Delete(info);cJSON_Delete(challenge);cJSON_Delete(proof);
    spark_identity_delete(identity);return err;
}
