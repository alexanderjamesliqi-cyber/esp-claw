/*
 * SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Async job management for cap_mpy - mirrors cap_lua_async architecture.
 * Phase 1: simplified implementation with basic job queue.
 */
#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "esp_attr.h"
#include "esp_check.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_random.h"
#include "freertos/FreeRTOS.h"
#include "freertos/idf_additions.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

#include "py/gc.h"
#include "py/lexer.h"
#include "py/parse.h"
#include "py/compile.h"
#include "py/mpstate.h"
#include "py/runtime.h"
#include "py/stackctrl.h"

#include "cap_mpy.h"

static const char *TAG = "cap_mpy_async";

#define CAP_MPY_MAX_JOBS          8
#define CAP_MPY_MAX_CONCURRENT    1
#define CAP_MPY_OUTPUT_SIZE       (4 * 1024)
#define CAP_MPY_STOP_WAIT_MS      2000
#define CAP_MPY_TASK_STACK_SIZE   (16 * 1024)
#define CAP_MPY_JOB_EVENT_OBSERVER_MAX 8
#define CAP_MPY_GC_HEAP_SIZE_DEFAULT  (128 * 1024)

typedef struct {
    bool used;
    cap_mpy_job_status_t status;
    char job_id[CAP_MPY_JOB_ID_LEN];
    char name[CAP_MPY_JOB_NAME_MAX];
    char exclusive[CAP_MPY_JOB_EXCLUSIVE_MAX];
    char path[CAP_MPY_JOB_PATH_MAX];
    char *args_json;
    char *summary;
    uint32_t timeout_ms;
    time_t created_at;
    time_t started_at;
    time_t finished_at;
    TaskHandle_t task_handle;
    volatile bool stop_requested;
    void *gc_heap;       /* Per-job GC heap */
    size_t gc_heap_size;
} cap_mpy_job_record_t;

typedef struct {
    bool used;
    cap_mpy_job_event_cb_t cb;
    void *user_ctx;
} cap_mpy_job_event_observer_t;

static EXT_RAM_BSS_ATTR cap_mpy_job_record_t s_jobs[CAP_MPY_MAX_JOBS];
static SemaphoreHandle_t s_job_lock;
static portMUX_TYPE s_job_lock_init_mux=portMUX_INITIALIZER_UNLOCKED;
static bool ensure_job_lock(void)
{
    SemaphoreHandle_t created=xSemaphoreCreateMutex();
    portENTER_CRITICAL(&s_job_lock_init_mux);
    if (!s_job_lock) {s_job_lock=created;created=NULL;}
    portEXIT_CRITICAL(&s_job_lock_init_mux);
    if (created) vSemaphoreDelete(created);
    return s_job_lock!=NULL;
}
static SemaphoreHandle_t s_event_lock;
static size_t s_running_jobs;
static bool s_started;
static cap_mpy_job_event_observer_t s_event_observers[CAP_MPY_JOB_EVENT_OBSERVER_MAX];

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

static const char *s_status_names[] = {
    "queued", "running", "done", "failed", "timeout", "stopped"
};

static const char *cap_mpy_status_name(cap_mpy_job_status_t s)
{
    if (s <= CAP_MPY_JOB_STOPPED) {
        return s_status_names[s];
    }
    return "unknown";
}

static bool cap_mpy_is_terminal(cap_mpy_job_status_t s)
{
    return s >= CAP_MPY_JOB_DONE;
}

static void cap_mpy_gen_job_id(char *buf, size_t size)
{
    snprintf(buf, size, "%08x", (unsigned)esp_random());
}

static void cap_mpy_clear_slot(cap_mpy_job_record_t *job)
{
    if (!job) return;
    free(job->args_json);
    free(job->summary);
    if (job->gc_heap) {
        heap_caps_free(job->gc_heap);
    }
    memset(job, 0, sizeof(*job));
}

/* ------------------------------------------------------------------ */
/*  Job task                                                           */
/* ------------------------------------------------------------------ */

static void cap_mpy_job_task(void *arg)
{
    cap_mpy_job_record_t *job = (cap_mpy_job_record_t *)arg;
    char *output = NULL;
    esp_err_t result=ESP_ERR_NO_MEM;

    output = calloc(1, CAP_MPY_OUTPUT_SIZE);
    if (!output) {
        ESP_LOGE(TAG, "Failed to allocate output buffer");
        goto finish;
    }

    if (xSemaphoreTake(s_job_lock,pdMS_TO_TICKS(1000))==pdTRUE) {
        job->status=CAP_MPY_JOB_RUNNING;job->started_at=time(NULL);
        xSemaphoreGive(s_job_lock);
    }
    result=cap_mpy_run_controlled(job->path,job->timeout_ms,&job->stop_requested,output,CAP_MPY_OUTPUT_SIZE);
finish:
    /* Update job status */
    if (s_job_lock && xSemaphoreTake(s_job_lock, pdMS_TO_TICKS(1000)) == pdTRUE) {
        if (job->stop_requested) {
            job->status = CAP_MPY_JOB_STOPPED;
        } else if (result==ESP_ERR_TIMEOUT) {
            job->status = CAP_MPY_JOB_TIMEOUT;
        } else if (result!=ESP_OK) {
            job->status = CAP_MPY_JOB_FAILED;
        } else {
            job->status = CAP_MPY_JOB_DONE;
        }
        job->finished_at = time(NULL);
        job->task_handle = NULL;
        if (output && output[0]) {
            free(job->summary);
            job->summary = strdup(output);
        }
        if (s_running_jobs > 0) s_running_jobs--;
        xSemaphoreGive(s_job_lock);
    }

    free(output);
    vTaskDelete(NULL);
}

/* ------------------------------------------------------------------ */
/*  Public async API                                                   */
/* ------------------------------------------------------------------ */

esp_err_t cap_mpy_run_script_async(const char *path, const char *args_json,
                                   uint32_t timeout_ms, const char *name,
                                   const char *exclusive, bool replace,
                                   char *output, size_t output_size)
{
    if (!path || !path[0] || !output || output_size == 0) {
        return ESP_ERR_INVALID_ARG;
    }
    output[0] = '\0';

    if (!ensure_job_lock()) return ESP_ERR_NO_MEM;

    /* Find a free slot */
    int slot = -1;
    if (xSemaphoreTake(s_job_lock, pdMS_TO_TICKS(1000)) != pdTRUE) {
        return ESP_ERR_TIMEOUT;
    }

    for (int i = 0; i < CAP_MPY_MAX_JOBS; i++) {
        if (!s_jobs[i].used || cap_mpy_is_terminal(s_jobs[i].status)) {
            slot = i;
            break;
        }
    }

    if (slot < 0) {
        xSemaphoreGive(s_job_lock);
        snprintf(output, output_size, "Error: job slots full (%d/%d)", CAP_MPY_MAX_JOBS, CAP_MPY_MAX_JOBS);
        return ESP_ERR_NO_MEM;
    }

    if (s_running_jobs >= CAP_MPY_MAX_CONCURRENT) {
        xSemaphoreGive(s_job_lock);
        snprintf(output, output_size, "Error: concurrency limit (%d/%d)", CAP_MPY_MAX_CONCURRENT, CAP_MPY_MAX_CONCURRENT);
        return ESP_ERR_NO_MEM;
    }

    /* Set up the job */
    cap_mpy_clear_slot(&s_jobs[slot]);
    s_jobs[slot].used = true;
    s_jobs[slot].status = CAP_MPY_JOB_QUEUED;
    strlcpy(s_jobs[slot].path, path, sizeof(s_jobs[slot].path));
    if (name) strlcpy(s_jobs[slot].name, name, sizeof(s_jobs[slot].name));
    if (exclusive) strlcpy(s_jobs[slot].exclusive, exclusive, sizeof(s_jobs[slot].exclusive));
    if (args_json) s_jobs[slot].args_json = strdup(args_json);
    s_jobs[slot].timeout_ms = timeout_ms;
    s_jobs[slot].created_at = time(NULL);
    s_jobs[slot].stop_requested = false;
    s_jobs[slot].gc_heap = NULL;
    cap_mpy_gen_job_id(s_jobs[slot].job_id, sizeof(s_jobs[slot].job_id));
    s_running_jobs++;

    char job_id_copy[CAP_MPY_JOB_ID_LEN];
    strlcpy(job_id_copy, s_jobs[slot].job_id, sizeof(job_id_copy));
    xSemaphoreGive(s_job_lock);

    /* Create task */
    TaskHandle_t task = NULL;
    BaseType_t xret = xTaskCreatePinnedToCore(
        cap_mpy_job_task, "cap_mpy_job",
        CAP_MPY_TASK_STACK_SIZE,
        &s_jobs[slot],
        4, &task, tskNO_AFFINITY);

    if (xret != pdPASS) {
        if (xSemaphoreTake(s_job_lock, pdMS_TO_TICKS(1000)) == pdTRUE) {
            s_jobs[slot].status = CAP_MPY_JOB_FAILED;
            s_jobs[slot].finished_at = time(NULL);
            if (s_running_jobs > 0) s_running_jobs--;
            xSemaphoreGive(s_job_lock);
        }
        snprintf(output, output_size, "Error: failed to create task");
        return ESP_ERR_NO_MEM;
    }

    if (xSemaphoreTake(s_job_lock, pdMS_TO_TICKS(1000)) == pdTRUE) {
        if (!strcmp(s_jobs[slot].job_id,job_id_copy) && !cap_mpy_is_terminal(s_jobs[slot].status)) s_jobs[slot].task_handle = task;
        xSemaphoreGive(s_job_lock);
    }

    snprintf(output, output_size,
             "Started Python job %s (name=%s, exclusive=%s, timeout=%u) for %s",
             job_id_copy,
             name ? name : "(unnamed)",
             exclusive ? exclusive : "none",
             (unsigned)timeout_ms, path);
    return ESP_OK;
}

esp_err_t cap_mpy_stop_job(const char *id_or_name, uint32_t wait_ms,
                           char *output, size_t output_size)
{
    if (!id_or_name || !id_or_name[0]) {
        if (output && output_size > 0) snprintf(output, output_size, "Error: missing job id");
        return ESP_ERR_INVALID_ARG;
    }

    if (!s_job_lock || xSemaphoreTake(s_job_lock, pdMS_TO_TICKS(1000)) != pdTRUE) {
        return ESP_ERR_TIMEOUT;
    }

    int slot = -1;
    for (int i = 0; i < CAP_MPY_MAX_JOBS; i++) {
        if (s_jobs[i].used && !cap_mpy_is_terminal(s_jobs[i].status)) {
            if (strcmp(s_jobs[i].job_id, id_or_name) == 0 ||
                (s_jobs[i].name[0] && strcmp(s_jobs[i].name, id_or_name) == 0)) {
                slot = i;
                break;
            }
        }
    }

    if (slot < 0) {
        xSemaphoreGive(s_job_lock);
        if (output && output_size > 0) snprintf(output, output_size, "Error: job not found: %s", id_or_name);
        return ESP_ERR_NOT_FOUND;
    }

    s_jobs[slot].stop_requested = true;
    char jid[CAP_MPY_JOB_ID_LEN];
    strlcpy(jid, s_jobs[slot].job_id, sizeof(jid));
    xSemaphoreGive(s_job_lock);

    if (wait_ms == 0) wait_ms = CAP_MPY_STOP_WAIT_MS;
    vTaskDelay(pdMS_TO_TICKS(wait_ms));

    if (output && output_size > 0) {
        snprintf(output, output_size, "OK: stop requested for job %s", jid);
    }
    return ESP_OK;
}

esp_err_t cap_mpy_stop_all_jobs(const char *exclusive_filter, uint32_t wait_ms,
                                char *output, size_t output_size)
{
    int stopped = 0;
    if (!s_job_lock || xSemaphoreTake(s_job_lock, pdMS_TO_TICKS(1000)) != pdTRUE) {
        return ESP_ERR_TIMEOUT;
    }

    for (int i = 0; i < CAP_MPY_MAX_JOBS; i++) {
        if (!s_jobs[i].used || cap_mpy_is_terminal(s_jobs[i].status)) continue;
        if (exclusive_filter && exclusive_filter[0] &&
            strcmp(s_jobs[i].exclusive, exclusive_filter) != 0) continue;
        s_jobs[i].stop_requested = true;
        stopped++;
    }
    xSemaphoreGive(s_job_lock);

    if (wait_ms > 0) vTaskDelay(pdMS_TO_TICKS(wait_ms));

    if (output && output_size > 0) {
        snprintf(output, output_size, "Stop requested for %d job(s)", stopped);
    }
    return ESP_OK;
}

esp_err_t cap_mpy_list_jobs(const char *status, char *output, size_t output_size)
{
    if (!output || output_size == 0) return ESP_ERR_INVALID_ARG;
    output[0] = '\0';

    if (!s_job_lock || xSemaphoreTake(s_job_lock, pdMS_TO_TICKS(1000)) != pdTRUE) {
        snprintf(output, output_size, "Error: lock timeout");
        return ESP_ERR_TIMEOUT;
    }

    size_t off = 0;
    int shown = 0;
    time_t now = time(NULL);

    for (int i = 0; i < CAP_MPY_MAX_JOBS && off < output_size - 1; i++) {
        if (!s_jobs[i].used) continue;
        if (status && status[0] && strcmp(status, "all") != 0 &&
            strcmp(cap_mpy_status_name(s_jobs[i].status), status) != 0) continue;

        int runtime_s = s_jobs[i].started_at ? (int)(now - s_jobs[i].started_at) : 0;
        int written = snprintf(output + off, output_size - off,
                               "%s | %s | name=%s | exclusive=%s | runtime=%ds | path=%s\n",
                               s_jobs[i].job_id,
                               cap_mpy_status_name(s_jobs[i].status),
                               s_jobs[i].name[0] ? s_jobs[i].name : "(unnamed)",
                               s_jobs[i].exclusive[0] ? s_jobs[i].exclusive : "none",
                               runtime_s, s_jobs[i].path);
        if (written < 0 || (size_t)written >= output_size - off) break;
        off += (size_t)written;
        shown++;
    }

    xSemaphoreGive(s_job_lock);
    if (shown == 0) snprintf(output, output_size, "(no Python jobs)");
    return ESP_OK;
}

size_t cap_mpy_get_active_job_count(void)
{
    size_t count = 0;
    if (!s_job_lock) return 0;
    if (xSemaphoreTake(s_job_lock, pdMS_TO_TICKS(200)) != pdTRUE) return 0;
    for (int i = 0; i < CAP_MPY_MAX_JOBS; i++) {
        if (s_jobs[i].used && !cap_mpy_is_terminal(s_jobs[i].status)) count++;
    }
    xSemaphoreGive(s_job_lock);
    return count;
}

esp_err_t cap_mpy_register_job_event_cb(cap_mpy_job_event_cb_t cb, void *user_ctx)
{
    if (!cb) return ESP_ERR_INVALID_ARG;
    if (!s_event_lock) {
        s_event_lock = xSemaphoreCreateMutex();
        if (!s_event_lock) return ESP_ERR_NO_MEM;
    }
    if (xSemaphoreTake(s_event_lock, pdMS_TO_TICKS(1000)) != pdTRUE) return ESP_ERR_TIMEOUT;
    for (int i = 0; i < CAP_MPY_JOB_EVENT_OBSERVER_MAX; i++) {
        if (!s_event_observers[i].used) {
            s_event_observers[i].used = true;
            s_event_observers[i].cb = cb;
            s_event_observers[i].user_ctx = user_ctx;
            xSemaphoreGive(s_event_lock);
            return ESP_OK;
        }
    }
    xSemaphoreGive(s_event_lock);
    return ESP_ERR_NO_MEM;
}

esp_err_t cap_mpy_unregister_job_event_cb(cap_mpy_job_event_cb_t cb, void *user_ctx)
{
    if (!cb || !s_event_lock) return ESP_ERR_INVALID_ARG;
    if (xSemaphoreTake(s_event_lock, pdMS_TO_TICKS(1000)) != pdTRUE) return ESP_ERR_TIMEOUT;
    for (int i = 0; i < CAP_MPY_JOB_EVENT_OBSERVER_MAX; i++) {
        if (s_event_observers[i].used && s_event_observers[i].cb == cb &&
            s_event_observers[i].user_ctx == user_ctx) {
            memset(&s_event_observers[i], 0, sizeof(s_event_observers[i]));
            xSemaphoreGive(s_event_lock);
            return ESP_OK;
        }
    }
    xSemaphoreGive(s_event_lock);
    return ESP_ERR_NOT_FOUND;
}
