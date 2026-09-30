/* Factory-only image. No provisioning code is linked into the product firmware. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "spark_identity.h"
#include "esp_console.h"
#include "esp_mac.h"
#include "esp_random.h"
#include "esp_chip_info.h"
#include "bootloader_random.h"
#include "mbedtls/ecp.h"
#include "mbedtls/base64.h"
#include "mbedtls/platform_util.h"
#include "hal/efuse_ll.h"
#include "soc/soc_caps.h"

static int rng(void *ctx,unsigned char *out,size_t size){(void)ctx;esp_fill_random(out,size);return 0;}
static void identity_json(void)
{
    spark_identity_handle_t identity=NULL;cJSON *info=NULL;
    if(spark_identity_create(&identity)==ESP_OK && spark_identity_get_info(identity,&info)==ESP_OK){
        char *text=cJSON_PrintUnformatted(info);if(text){printf("SPARK_FACTORY:%s\n",text);free(text);}cJSON_Delete(info);
    }else puts("FACTORY_ERROR: protected identity unavailable");
    spark_identity_delete(identity);
}
static int inspect(int argc,char **argv)
{
    (void)argc;(void)argv;uint8_t mac[6];esp_chip_info_t chip;esp_chip_info(&chip);
    if(esp_efuse_mac_get_default(mac)!=ESP_OK)return 1;
    printf("DEVICE:%02x%02x%02x%02x%02x%02x REV:%d KEY0_UNUSED:%d\n",mac[0],mac[1],mac[2],mac[3],mac[4],mac[5],chip.revision,esp_efuse_key_block_unused(SPARK_IDENTITY_BLOCK));
    identity_json();return 0;
}
static int provision(int argc,char **argv)
{
    uint8_t mac[6],secret[32];char expected[13];esp_chip_info_t chip;esp_chip_info(&chip);
    if(esp_efuse_mac_get_default(mac)!=ESP_OK)return 1;
    snprintf(expected,sizeof(expected),"%02x%02x%02x%02x%02x%02x",mac[0],mac[1],mac[2],mac[3],mac[4],mac[5]);
    if(argc!=3 || strcmp(argv[1],expected)!=0 || strcmp(argv[2],"CONFIRM_EFUSE")!=0 || chip.revision<300){puts("FACTORY_ERROR: require matching MAC, rev >= 3.0 and CONFIRM_EFUSE");return 1;}
    /* Restart after enrollment/power loss recovers the same identity; never rotate it. */
    if(!esp_efuse_key_block_unused(SPARK_IDENTITY_BLOCK)){identity_json();return 1;}
    mbedtls_ecp_keypair *key=calloc(1,sizeof(*key));if(!key)return 1;
    mbedtls_ecp_keypair_init(key);
    int rc=mbedtls_ecp_gen_key(MBEDTLS_ECP_DP_SECP256R1,key,rng,NULL);
    if(rc==0)rc=mbedtls_mpi_write_binary_le(&key->MBEDTLS_PRIVATE(d),secret,sizeof(secret));
#if SOC_ECDSA_SUPPORT_CURVE_SPECIFIC_KEY_PURPOSES && EFUSE_LL_HAS_ECDSA_KEY_P192
    const esp_efuse_purpose_t purpose=ESP_EFUSE_KEY_PURPOSE_ECDSA_KEY_P256;
#else
    const esp_efuse_purpose_t purpose=ESP_EFUSE_KEY_PURPOSE_ECDSA_KEY;
#endif
    if(rc==0)rc=esp_efuse_write_key(SPARK_IDENTITY_BLOCK,purpose,secret,sizeof(secret));
    mbedtls_platform_zeroize(secret,sizeof(secret));
    mbedtls_ecp_keypair_free(key);free(key);
    if(rc!=0){puts("FACTORY_ERROR: provisioning failed; quarantine device and inspect efuses");return 1;}
    identity_json();return 0;
}
static int sign_challenge(int argc,char **argv)
{
    if(argc!=2)return 1;
    unsigned char *message=calloc(1,385);size_t size=0;
    if(!message)return 1;
    int rc=mbedtls_base64_decode(message,384,&size,(unsigned char*)argv[1],strlen(argv[1]));
    spark_identity_handle_t identity=NULL;cJSON *proof=NULL;
    if(rc==0 && size>0 && strlen((char*)message)==size && spark_identity_create(&identity)==ESP_OK && spark_identity_sign(identity,(char*)message,&proof)==ESP_OK){
        char *text=cJSON_PrintUnformatted(proof);
        if(text){printf("SPARK_PROOF:%s\n",text);free(text);}else rc=1;
    }else rc=1;
    cJSON_Delete(proof);spark_identity_delete(identity);free(message);return rc;
}
void app_main(void)
{
    /* This image has no ADC/radio users. Enable a true entropy source for key generation. */
    bootloader_random_enable();
    esp_console_repl_t *repl=NULL;
    esp_console_repl_config_t cfg=ESP_CONSOLE_REPL_CONFIG_DEFAULT();cfg.prompt="factory> ";cfg.task_stack_size=12288;cfg.max_cmdline_length=1024;
    esp_console_dev_usb_serial_jtag_config_t dev=ESP_CONSOLE_DEV_USB_SERIAL_JTAG_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_console_new_repl_usb_serial_jtag(&dev,&cfg,&repl));
    const esp_console_cmd_t status={.command="identity",.help="Read factory public identity; never exposes private key",.func=inspect};
    const esp_console_cmd_t burn={.command="provision",.help="One-time KEY0 burn: provision <MAC> CONFIRM_EFUSE",.func=provision};
    const esp_console_cmd_t sign={.command="sign",.help="Sign a base64 factory challenge with the protected key",.func=sign_challenge};
    ESP_ERROR_CHECK(esp_console_cmd_register(&sign));
    ESP_ERROR_CHECK(esp_console_cmd_register(&status));ESP_ERROR_CHECK(esp_console_cmd_register(&burn));
    ESP_ERROR_CHECK(esp_console_start_repl(repl));
}
