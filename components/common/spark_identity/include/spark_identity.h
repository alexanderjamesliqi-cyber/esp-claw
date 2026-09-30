#pragma once
#include "esp_err.h"
#include "cJSON.h"
#include "esp_efuse.h"
/* Fixed reserved production identity slot. Never use it for another purpose. */
#define SPARK_IDENTITY_BLOCK EFUSE_BLK_KEY0
#define SPARK_IDENTITY_ALGORITHM "ECDSA-P256-SHA256"
typedef struct spark_identity *spark_identity_handle_t;
esp_err_t spark_identity_create(spark_identity_handle_t *out);
void spark_identity_delete(spark_identity_handle_t identity);
esp_err_t spark_identity_get_info(spark_identity_handle_t identity, cJSON **out);
esp_err_t spark_identity_sign(spark_identity_handle_t identity, const char *message, cJSON **out);

/* Blocking network operation: call only from a worker task. Caller frees authorization. */
esp_err_t spark_relay_authorize(const char *body, char digest_hex[65], char **authorization);

esp_err_t spark_identity_verify_certificate(spark_identity_handle_t identity,const unsigned char signature[64]);
