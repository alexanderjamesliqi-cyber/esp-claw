/* Serial transport only. The existing product service owns all program mutations. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "cJSON.h"
#include "claw_paths.h"
#include "esp_console.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "mbedtls/base64.h"

#define STUDIO_REQUEST_MAX 1024
#define STUDIO_RESPONSE_MAX 16384
#define STUDIO_WAIT_MS 10000

typedef struct {
    char request[128];
    char temporary[128];
    char response[128];
    unsigned char decoded[STUDIO_REQUEST_MAX + 1];
} studio_transaction_t;

static int studio_command(int argc, char **argv)
{
    if (argc != 2 || strlen(argv[1]) > 1400) { puts("studio requires one base64 request"); return 1; }
    studio_transaction_t *tx = calloc(1, sizeof(*tx));
    if (!tx) return 1;
    cJSON *request = NULL;
    FILE *file = NULL;
    char *response = NULL;
    unsigned char *encoded = NULL;
    int result = 1;
    size_t size = 0;
    if (mbedtls_base64_decode(tx->decoded, STUDIO_REQUEST_MAX, &size,
                             (const unsigned char *)argv[1], strlen(argv[1])) != 0) goto done;
    tx->decoded[size] = 0;
    request = cJSON_Parse((char *)tx->decoded);
    if (!request || !cJSON_IsString(cJSON_GetObjectItemCaseSensitive(request, "id")) ||
        !cJSON_IsString(cJSON_GetObjectItemCaseSensitive(request, "op"))) goto done;
    if (claw_paths_join(CLAW_PATH_DATA, "labplus/studio-request.json", tx->request, sizeof(tx->request)) != ESP_OK ||
        claw_paths_join(CLAW_PATH_DATA, "labplus/studio-request.tmp", tx->temporary, sizeof(tx->temporary)) != ESP_OK ||
        claw_paths_join(CLAW_PATH_DATA, "labplus/studio-response.json", tx->response, sizeof(tx->response)) != ESP_OK) goto done;
    /* Never overwrite or replay an outstanding operation after a timeout. */
    if (access(tx->request, F_OK) == 0) { puts("studio request still pending"); goto done; }
    unlink(tx->response);
    file = fopen(tx->temporary, "wb");
    if (!file) goto done;
    bool written = fwrite(tx->decoded, 1, size, file) == size;
    int closed = fclose(file); file = NULL;
    if (!written || closed != 0 || rename(tx->temporary, tx->request) != 0) goto done;
    for (int elapsed = 0; elapsed < STUDIO_WAIT_MS; elapsed += 20) {
        file = fopen(tx->response, "rb");
        if (file) break;
        vTaskDelay(pdMS_TO_TICKS(20));
    }
    if (!file) { puts("studio response timeout; check device before retry"); goto done; }
    if (fseek(file, 0, SEEK_END) != 0) goto done;
    long length = ftell(file);
    if (length < 1 || length > STUDIO_RESPONSE_MAX || fseek(file, 0, SEEK_SET) != 0) goto done;
    response = malloc((size_t)length);
    encoded = malloc(((size_t)length + 2) / 3 * 4 + 1);
    if (!response || !encoded || fread(response, 1, length, file) != (size_t)length) goto done;
    if (mbedtls_base64_encode(encoded, ((size_t)length + 2) / 3 * 4 + 1, &size,
                             (unsigned char *)response, length) != 0) goto done;
    printf("\nSPARK_STUDIO:%s\n", encoded);
    unlink(tx->response);
    result = 0;
done:
    if (file) fclose(file);
    cJSON_Delete(request); free(response); free(encoded); free(tx);
    return result;
}

void app_claw_studio_register(void)
{
    const esp_console_cmd_t cmd = {.command="studio", .help="Studio program library protocol", .func=studio_command};
    ESP_ERROR_CHECK(esp_console_cmd_register(&cmd));
}
