#pragma once
#include <dirent.h>
#include <sys/types.h>
int cap_mpy_owned_open(const char *path, int flags, ...);
int cap_mpy_owned_close(int fd);
DIR *cap_mpy_owned_opendir(const char *path);
int cap_mpy_owned_closedir(DIR *dir);
void cap_mpy_owned_io_close_all(void);
ssize_t cap_mpy_owned_read(int fd, void *buffer, size_t size);
ssize_t cap_mpy_owned_write(int fd, const void *buffer, size_t size);
struct dirent *cap_mpy_owned_readdir(DIR *dir);
