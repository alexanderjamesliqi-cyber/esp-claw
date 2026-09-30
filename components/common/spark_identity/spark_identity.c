#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include "spark_identity.h"
#include "esp_mac.h"
#include "esp_random.h"
#include "mbedtls/pk.h"
#include "mbedtls/ecdsa.h"
#include "spark_factory_ca.h"
#include "mbedtls/sha256.h"
#include "mbedtls/base64.h"
#include "ecdsa/ecdsa_alt.h"
#include "soc/soc_caps.h"

struct spark_identity { mbedtls_pk_context key; char id[13]; };
static int hardware_random(void *ctx, unsigned char *out, size_t n) { (void)ctx; esp_fill_random(out,n); return 0; }
esp_err_t spark_identity_create(spark_identity_handle_t *out)
{
    if (!out) return ESP_ERR_INVALID_ARG;
    *out = NULL;
#if CONFIG_MBEDTLS_HARDWARE_ECDSA_SIGN && SOC_ECDSA_SUPPORT_EXPORT_PUBKEY
    if (!esp_efuse_get_key_dis_read(SPARK_IDENTITY_BLOCK) ||
        !esp_efuse_get_key_dis_write(SPARK_IDENTITY_BLOCK) ||
        !esp_efuse_get_keypurpose_dis_write(SPARK_IDENTITY_BLOCK)) return ESP_ERR_INVALID_STATE;
    spark_identity_handle_t h = calloc(1,sizeof(*h));
    if (!h) return ESP_ERR_NO_MEM;
    uint8_t mac[6];
    if (esp_efuse_mac_get_default(mac) != ESP_OK) {free(h); return ESP_FAIL;}
    snprintf(h->id,sizeof(h->id),"%02x%02x%02x%02x%02x%02x",mac[0],mac[1],mac[2],mac[3],mac[4],mac[5]);
    mbedtls_pk_init(&h->key);
    esp_ecdsa_pk_conf_t cfg = {.grp_id=MBEDTLS_ECP_DP_SECP256R1,.efuse_block=SPARK_IDENTITY_BLOCK,.load_pubkey=true,.use_km_key=false};
    if (esp_ecdsa_set_pk_context(&h->key,&cfg) != 0) {spark_identity_delete(h);return ESP_ERR_INVALID_STATE;}
    *out=h;return ESP_OK;
#else
    return ESP_ERR_NOT_SUPPORTED;
#endif
}
void spark_identity_delete(spark_identity_handle_t h) {if(h){mbedtls_pk_free(&h->key);free(h);}}
esp_err_t spark_identity_get_info(spark_identity_handle_t h,cJSON **out)
{
    if(!h||!out)return ESP_ERR_INVALID_ARG;
    unsigned char *pem=calloc(1,256);
    if(!pem)return ESP_ERR_NO_MEM;
    if(mbedtls_pk_write_pubkey_pem(&h->key,pem,256)!=0){free(pem);return ESP_FAIL;}
    cJSON *info=cJSON_CreateObject();
    if(!info || !cJSON_AddStringToObject(info,"deviceId",h->id) ||
       !cJSON_AddStringToObject(info,"algorithm",SPARK_IDENTITY_ALGORITHM) ||
       !cJSON_AddBoolToObject(info,"efuseProtected",true) ||
       !cJSON_AddStringToObject(info,"publicKey",(char*)pem)){cJSON_Delete(info);free(pem);return ESP_ERR_NO_MEM;}
    unsigned char certificate[64],encoded[89];size_t length=0;
    if(esp_efuse_get_key_dis_write(EFUSE_BLK_KEY1) && esp_efuse_get_key_dis_write(EFUSE_BLK_KEY2) &&
       esp_efuse_get_keypurpose_dis_write(EFUSE_BLK_KEY1) && esp_efuse_get_keypurpose_dis_write(EFUSE_BLK_KEY2) &&
       esp_efuse_get_key_purpose(EFUSE_BLK_KEY1)==ESP_EFUSE_KEY_PURPOSE_USER && esp_efuse_get_key_purpose(EFUSE_BLK_KEY2)==ESP_EFUSE_KEY_PURPOSE_USER &&
       esp_efuse_read_block(EFUSE_BLK_KEY1,certificate,0,256)==ESP_OK && esp_efuse_read_block(EFUSE_BLK_KEY2,certificate+32,0,256)==ESP_OK &&
       mbedtls_base64_encode(encoded,sizeof(encoded),&length,certificate,64)==0){
        if(!cJSON_AddStringToObject(info,"certificate",(char*)encoded)){cJSON_Delete(info);free(pem);return ESP_ERR_NO_MEM;}
    }
    free(pem);*out=info;return ESP_OK;
}
esp_err_t spark_identity_sign(spark_identity_handle_t h,const char *message,cJSON **out)
{
    if(!h||!message||!out||strlen(message)>384)return ESP_ERR_INVALID_ARG;
    char prefix[96];snprintf(prefix,sizeof(prefix),"SPARK-AI-V1\nspark.mpython.cn\n%s\n",h->id);
    if(strncmp(message,prefix,strlen(prefix))!=0)return ESP_ERR_INVALID_ARG;
    unsigned char digest[32],signature[80],encoded[112];size_t length=0,encoded_len=0;
    if(mbedtls_sha256((const unsigned char*)message,strlen(message),digest,0)!=0)return ESP_FAIL;
    if(mbedtls_pk_sign(&h->key,MBEDTLS_MD_SHA256,digest,sizeof(digest),signature,sizeof(signature),&length,hardware_random,NULL)!=0)return ESP_FAIL;
    if(mbedtls_base64_encode(encoded,sizeof(encoded),&encoded_len,signature,length)!=0)return ESP_FAIL;
    cJSON *proof=cJSON_CreateObject();
    if(!proof || !cJSON_AddStringToObject(proof,"deviceId",h->id) || !cJSON_AddStringToObject(proof,"signature",(char*)encoded)){cJSON_Delete(proof);return ESP_ERR_NO_MEM;}
    *out=proof;return ESP_OK;
}

/* Verify the manufacturer's compact P1363 certificate before a factory burn. */
esp_err_t spark_identity_verify_certificate(spark_identity_handle_t h,const unsigned char signature[64])
{
    if(!h||!signature)return ESP_ERR_INVALID_ARG;
    unsigned char der[128],digest[32];size_t size=0;
    unsigned char *encoded=calloc(1,173);if(!encoded)return ESP_ERR_NO_MEM;
    int length=mbedtls_pk_write_pubkey_der(&h->key,der,sizeof(der));
    if(length<=0){free(encoded);return ESP_FAIL;}
    if(mbedtls_base64_encode(encoded,173,&size,der+sizeof(der)-length,length)!=0){free(encoded);return ESP_FAIL;}
    char *message=calloc(1,256);if(!message){free(encoded);return ESP_ERR_NO_MEM;}
    snprintf(message,256,"SPARK-CERT-V1\nspark.mpython.cn\n%s\n%s",h->id,encoded);free(encoded);
    int rc=mbedtls_sha256((unsigned char*)message,strlen(message),digest,0);free(message);
    mbedtls_pk_context *authority=calloc(1,sizeof(*authority));
    if(!authority)return ESP_ERR_NO_MEM;
    mbedtls_pk_init(authority);
    if(rc==0)rc=mbedtls_pk_parse_public_key(authority,(const unsigned char*)SPARK_FACTORY_CA_PEM,sizeof(SPARK_FACTORY_CA_PEM));
    mbedtls_mpi r,s;mbedtls_mpi_init(&r);mbedtls_mpi_init(&s);
    if(rc==0)rc=mbedtls_mpi_read_binary(&r,signature,32);
    if(rc==0)rc=mbedtls_mpi_read_binary(&s,signature+32,32);
    if(rc==0){mbedtls_ecp_keypair *key=mbedtls_pk_ec(*authority);rc=mbedtls_ecdsa_verify(&key->MBEDTLS_PRIVATE(grp),digest,32,&key->MBEDTLS_PRIVATE(Q),&r,&s);}
    mbedtls_mpi_free(&r);mbedtls_mpi_free(&s);mbedtls_pk_free(authority);free(authority);
    return rc==0?ESP_OK:ESP_ERR_INVALID_ARG;
}
