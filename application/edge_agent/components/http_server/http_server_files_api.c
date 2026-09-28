/*
 * SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include "http_server_priv.h"

#include <dirent.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdatomic.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"

static int mkdir_parents(char *path, mode_t mode)
{
    if (!path || path[0] != '/') {
        return -1;
    }
    for (char *p = path + 1; *p; p++) {
        if (*p != '/') {
            continue;
        }
        *p = '\0';
        if (mkdir(path, mode) != 0 && errno != EEXIST) {
            *p = '/';
            return -1;
        }
        *p = '/';
    }
    if (mkdir(path, mode) != 0 && errno != EEXIST) {
        return -1;
    }
    return 0;
}

static esp_err_t files_list_handler(httpd_req_t *req)
{
    char relative_path[HTTP_SERVER_PATH_MAX] = "/";
    if (http_server_query_get(req, "path", relative_path, sizeof(relative_path)) != ESP_OK) {
        strlcpy(relative_path, "/", sizeof(relative_path));
    }

    char full_path[HTTP_SERVER_PATH_MAX];
    if (http_server_resolve_storage_path(relative_path, full_path, sizeof(full_path)) != ESP_OK) {
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid path");
    }

    DIR *dir = opendir(full_path);
    if (!dir) {
        return httpd_resp_send_err(req, HTTPD_404_NOT_FOUND, "Directory not found");
    }

    cJSON *root = cJSON_CreateObject();
    cJSON *entries = cJSON_CreateArray();
    if (!root || !entries) {
        closedir(dir);
        cJSON_Delete(root);
        cJSON_Delete(entries);
        httpd_resp_send_500(req);
        return ESP_ERR_NO_MEM;
    }

    http_server_json_add_string(root, "path", relative_path);
    cJSON_AddItemToObject(root, "entries", entries);

    struct dirent *entry = NULL;
    while ((entry = readdir(dir)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) {
            continue;
        }

        char child_relative[HTTP_SERVER_PATH_MAX];
        char child_full[HTTP_SERVER_PATH_MAX];
        if (!http_server_build_child_relative_path(relative_path, entry->d_name, child_relative, sizeof(child_relative)) ||
            http_server_resolve_storage_path(child_relative, child_full, sizeof(child_full)) != ESP_OK) {
            continue;
        }

        struct stat st = {0};
        if (stat(child_full, &st) != 0) {
            continue;
        }

        cJSON *item = cJSON_CreateObject();
        if (!item) {
            continue;
        }

        http_server_json_add_string(item, "name", entry->d_name);
        http_server_json_add_string(item, "path", child_relative);
        cJSON_AddBoolToObject(item, "is_dir", S_ISDIR(st.st_mode));
        cJSON_AddNumberToObject(item, "size", (double)st.st_size);
        cJSON_AddItemToArray(entries, item);
    }

    closedir(dir);
    return http_server_send_json_response(req, root);
}

static esp_err_t file_download_handler(httpd_req_t *req)
{
    const char *relative_path = req->uri + strlen("/files");
    if (!http_server_path_is_safe(relative_path)) {
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid path");
    }

    char full_path[HTTP_SERVER_PATH_MAX];
    if (http_server_resolve_storage_path(relative_path, full_path, sizeof(full_path)) != ESP_OK) {
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid path");
    }

    struct stat st = {0};
    if (stat(full_path, &st) != 0 || S_ISDIR(st.st_mode)) {
        return httpd_resp_send_err(req, HTTPD_404_NOT_FOUND, "File not found");
    }

    FILE *file = fopen(full_path, "rb");
    if (!file) {
        return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Failed to open file");
    }

    char *scratch = http_server_alloc_scratch_buffer();
    if (!scratch) {
        fclose(file);
        httpd_resp_send_500(req);
        return ESP_ERR_NO_MEM;
    }

    httpd_resp_set_type(req, "application/octet-stream");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store, max-age=0");
    while (!feof(file)) {
        size_t read_bytes = fread(scratch, 1, HTTP_SERVER_SCRATCH_SIZE, file);
        if (read_bytes == 0) {
            /* fread returned 0: either clean EOF or a hard read error, which
             * also leaves feof() false and would otherwise spin forever and pin
             * this worker plus its scratch buffer. On a genuine read error,
             * leave the chunked stream unterminated and return ESP_FAIL so the
             * server aborts the connection: the client then sees a broken
             * transfer instead of a cleanly finished but silently truncated
             * file. (Headers may already be on the wire; aborting is still the
             * most honest signal we can give.) Clean EOF just ends the loop. */
            if (ferror(file)) {
                free(scratch);
                fclose(file);
                return ESP_FAIL;
            }
            break;
        }
        if (httpd_resp_send_chunk(req, scratch, read_bytes) != ESP_OK) {
            free(scratch);
            fclose(file);
            return ESP_FAIL;
        }
    }

    free(scratch);
    fclose(file);
    return httpd_resp_send_chunk(req, NULL, 0);
}

static esp_err_t files_upload_receive(httpd_req_t *req)
{
    char relative_path[HTTP_SERVER_PATH_MAX] = {0};
    if (http_server_query_get(req, "path", relative_path, sizeof(relative_path)) != ESP_OK) {
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Missing path");
    }
    if (req->content_len <= 0 || req->content_len > HTTP_SERVER_UPLOAD_MAX_SIZE) {
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid upload size");
    }

    char full_path[HTTP_SERVER_PATH_MAX];
    if (http_server_resolve_storage_path(relative_path, full_path, sizeof(full_path)) != ESP_OK) {
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid path");
    }

    char parent_path[HTTP_SERVER_PATH_MAX];
    strlcpy(parent_path, full_path, sizeof(parent_path));
    char *slash = strrchr(parent_path, '/');
    if (!slash || slash == parent_path) {
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid path");
    }
    *slash = '\0';

    struct stat st = {0};
    if (stat(parent_path, &st) != 0 || !S_ISDIR(st.st_mode)) {
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Parent directory not found");
    }

    if (stat(full_path, &st) == 0 && !S_ISREG(st.st_mode)) {
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Destination is not a file");
    }

    /* Receive into a private sibling. A dropped connection must not truncate
     * or unlink an existing user program. FAT rename cannot replace a file,
     * so the final commit retains the old file until the new rename succeeds. */
    char staging_path[HTTP_SERVER_PATH_MAX];
    char backup_path[HTTP_SERVER_PATH_MAX];
    int path_len = snprintf(staging_path, sizeof(staging_path), "%s/.claw-upload-XXXXXX", parent_path);
    if (path_len < 0 || (size_t)path_len + 9 >= sizeof(staging_path)) {
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Upload path too long");
    }
    int fd = mkstemp(staging_path);
    FILE *file = fd >= 0 ? fdopen(fd, "wb") : NULL;
    if (!file) {
        if (fd >= 0) { close(fd); unlink(staging_path); }
        return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Failed to create file");
    }

    char *scratch = http_server_alloc_scratch_buffer();
    if (!scratch) {
        fclose(file);
        unlink(staging_path);
        httpd_resp_send_500(req);
        return ESP_ERR_NO_MEM;
    }

    int remaining = req->content_len;
    unsigned idle_timeouts = 0;
    TickType_t started = xTaskGetTickCount();
    while (remaining > 0) {
        int chunk = remaining > HTTP_SERVER_SCRATCH_SIZE ? HTTP_SERVER_SCRATCH_SIZE : remaining;
        int received = httpd_req_recv(req, scratch, chunk);
        /* One bounded retry covers a radio scan/retransmission pause. A slow
         * or disconnected client still has a finite deadline. */
        bool within_deadline = xTaskGetTickCount() - started < pdMS_TO_TICKS(30000);
        if (received == HTTPD_SOCK_ERR_TIMEOUT && idle_timeouts++ == 0 && within_deadline) {
            continue;
        }
        if (!within_deadline || received <= 0 || fwrite(scratch, 1, received, file) != (size_t)received) {
            free(scratch);
            fclose(file);
            unlink(staging_path);
            return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Upload failed");
        }
        remaining -= received;
    }

    free(scratch);
    bool written = fflush(file) == 0 && fsync(fileno(file)) == 0;
    if (fclose(file) != 0) written = false;
    if (!written) {
        unlink(staging_path);
        return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Failed to save file");
    }
    strlcpy(backup_path, staging_path, sizeof(backup_path));
    strlcat(backup_path, ".previous", sizeof(backup_path));
    bool had_original = stat(full_path, &st) == 0;
    if (had_original && (!S_ISREG(st.st_mode) || access(backup_path, F_OK) == 0 || rename(full_path, backup_path) != 0)) {
        unlink(staging_path);
        return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Failed to preserve original file");
    }
    if (rename(staging_path, full_path) != 0) {
        if (had_original) (void)rename(backup_path, full_path);
        unlink(staging_path);
        return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Failed to commit upload");
    }
    if (had_original) unlink(backup_path);
    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store, max-age=0");
    return httpd_resp_sendstr(req, "{\"ok\":true}");
}

/* A slow request body must not monopolize the HTTP server's dispatcher.
 * One permanent worker bounds stack/FD use and serializes file replacements. */
static QueueHandle_t s_upload_queue;
static atomic_uint s_upload_pending;
static void files_upload_worker(void *arg)
{
    (void)arg;
    for (;;) {
        httpd_req_t *req = NULL;
        if (xQueueReceive(s_upload_queue, &req, portMAX_DELAY) != pdTRUE) continue;
        httpd_handle_t server = req->handle;
        int socket = httpd_req_to_sockfd(req);
        /* End this upload connection explicitly; rejected partial bodies must
         * never be parsed as a following keep-alive request. */
        httpd_resp_set_hdr(req, "Connection", "close");
        files_upload_receive(req);
        httpd_req_async_handler_complete(req);
        atomic_fetch_sub(&s_upload_pending, 1);
        httpd_sess_trigger_close(server, socket);
    }
}
static esp_err_t files_upload_unavailable(httpd_req_t *req, const char *message)
{
    httpd_resp_set_status(req, "503 Service Unavailable");
    httpd_resp_set_hdr(req, "Connection", "close");
    return httpd_resp_sendstr(req, message);
}
static esp_err_t files_upload_handler(httpd_req_t *req)
{
    if (!s_upload_queue) {
        s_upload_queue = xQueueCreate(1, sizeof(httpd_req_t *));
        if (!s_upload_queue) return files_upload_unavailable(req, "Upload worker unavailable");
        if (xTaskCreate(files_upload_worker, "file_upload", 8192, NULL, 3, NULL) != pdPASS) {
            vQueueDelete(s_upload_queue);s_upload_queue = NULL;
            return files_upload_unavailable(req, "Upload worker unavailable");
        }
    }
    /* One active request and one queued request; additional callers get 503. */
    unsigned pending = atomic_load(&s_upload_pending);
    if (pending >= 2) {
        files_upload_unavailable(req, "Another upload is in progress");
        return ESP_FAIL; /* Close without waiting for its unread body. */
    }
    atomic_fetch_add(&s_upload_pending, 1);
    httpd_req_t *copy = NULL;
    if (httpd_req_async_handler_begin(req, &copy) != ESP_OK) {
        atomic_fetch_sub(&s_upload_pending, 1);
        return files_upload_unavailable(req, "Upload allocation failed");
    }
    if (xQueueSend(s_upload_queue, &copy, 0) != pdTRUE) {
        files_upload_unavailable(copy, "Upload queue unavailable");
        httpd_req_async_handler_complete(copy);
        atomic_fetch_sub(&s_upload_pending, 1);
        return ESP_FAIL;
    }
    return ESP_OK;
}

static int rmdir_recursive(const char *path)
{
    DIR *dir = opendir(path);
    if (!dir) return -1;

    struct dirent *entry;
    while ((entry = readdir(dir)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) {
            continue;
        }
        char child[HTTP_SERVER_PATH_MAX];
        strlcpy(child, path, sizeof(child));
        strlcat(child, "/", sizeof(child));
        strlcat(child, entry->d_name, sizeof(child));

        struct stat st = {0};
        if (stat(child, &st) != 0) { closedir(dir); return -1; }

        int rc = S_ISDIR(st.st_mode) ? rmdir_recursive(child) : unlink(child);
        if (rc != 0) { closedir(dir); return -1; }
    }
    closedir(dir);
    return rmdir(path);
}

static esp_err_t files_delete_handler(httpd_req_t *req)
{
    char relative_path[HTTP_SERVER_PATH_MAX] = {0};
    if (http_server_query_get(req, "path", relative_path, sizeof(relative_path)) != ESP_OK) {
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Missing path");
    }

    char recursive_str[8] = {0};
    http_server_query_get(req, "recursive", recursive_str, sizeof(recursive_str));
    bool recursive = (strcmp(recursive_str, "1") == 0 || strcmp(recursive_str, "true") == 0);

    char full_path[HTTP_SERVER_PATH_MAX];
    if (http_server_resolve_storage_path(relative_path, full_path, sizeof(full_path)) != ESP_OK) {
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid path");
    }

    struct stat st = {0};
    if (stat(full_path, &st) != 0) {
        return httpd_resp_send_err(req, HTTPD_404_NOT_FOUND, "Path not found");
    }

    if (S_ISDIR(st.st_mode)) {
        if (recursive) {
            if (rmdir_recursive(full_path) != 0) {
                return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Recursive delete failed");
            }
        } else {
            DIR *check_dir = opendir(full_path);
            if (check_dir) {
                bool has_children = false;
                struct dirent *de;
                while ((de = readdir(check_dir)) != NULL) {
                    if (strcmp(de->d_name, ".") != 0 && strcmp(de->d_name, "..") != 0) {
                        has_children = true;
                        break;
                    }
                }
                closedir(check_dir);
                if (has_children) {
                    httpd_resp_set_type(req, "application/json");
                    httpd_resp_set_status(req, "409 Conflict");
                    httpd_resp_set_hdr(req, "Cache-Control", "no-store, max-age=0");
                    return httpd_resp_sendstr(req, "{\"error\":\"directory_not_empty\",\"message\":\"Directory is not empty. Use recursive delete to remove all contents.\"}");
                }
            }
            if (rmdir(full_path) != 0) {
                return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Delete failed");
            }
        }
    } else {
        if (unlink(full_path) != 0) {
            return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Delete failed");
        }
    }

    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store, max-age=0");
    return httpd_resp_sendstr(req, "{\"ok\":true}");
}

static esp_err_t files_mkdir_handler(httpd_req_t *req)
{
    cJSON *root = NULL;
    if (http_server_parse_json_body(req, &root) != ESP_OK) {
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid JSON body");
    }

    cJSON *path_item = cJSON_GetObjectItemCaseSensitive(root, "path");
    if (!cJSON_IsString(path_item) || !http_server_path_is_safe(path_item->valuestring)) {
        cJSON_Delete(root);
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid path");
    }

    cJSON *rec_item = cJSON_GetObjectItemCaseSensitive(root, "recursive");
    const bool mk_recursive = cJSON_IsBool(rec_item) && cJSON_IsTrue(rec_item);

    char full_path[HTTP_SERVER_PATH_MAX];
    esp_err_t err = http_server_resolve_storage_path(path_item->valuestring, full_path, sizeof(full_path));
    cJSON_Delete(root);
    if (err != ESP_OK) {
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid path");
    }

    if (mk_recursive) {
        char mkdir_buf[HTTP_SERVER_PATH_MAX];
        strlcpy(mkdir_buf, full_path, sizeof(mkdir_buf));
        if (mkdir_parents(mkdir_buf, 0775) != 0) {
            return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Failed to create directory");
        }
    } else if (mkdir(full_path, 0775) != 0 && errno != EEXIST) {
        return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Failed to create directory");
    }

    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store, max-age=0");
    return httpd_resp_sendstr(req, "{\"ok\":true}");
}

esp_err_t http_server_register_files_routes(httpd_handle_t server)
{
    const httpd_uri_t handlers[] = {
        { .uri = "/api/files", .method = HTTP_GET, .handler = files_list_handler },
        { .uri = "/api/files", .method = HTTP_DELETE, .handler = files_delete_handler },
        { .uri = "/api/files/upload", .method = HTTP_POST, .handler = files_upload_handler },
        { .uri = "/api/files/mkdir", .method = HTTP_POST, .handler = files_mkdir_handler },
        { .uri = "/files/*", .method = HTTP_GET, .handler = file_download_handler },
    };

    for (size_t i = 0; i < sizeof(handlers) / sizeof(handlers[0]); ++i) {
        esp_err_t err = httpd_register_uri_handler(server, &handlers[i]);
        if (err != ESP_OK) {
            return err;
        }
    }
    return ESP_OK;
}
