/* The single VM owns these resources under s_vm_lock. Reserve SD descriptors
 * for the display, bridge and HTTP service (the board mount permits eight).
 * Cleanup is independent of GC/finalisers, including forced VM abort. */
#include "mpy_owned_io.h"
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdbool.h>
#include <unistd.h>
#define USER_IO_LIMIT 3
static struct { bool used; int fd; DIR *dir; } owned[USER_IO_LIMIT];
static int vacant(void)
{
    for (int i=0;i<USER_IO_LIMIT;i++) if (!owned[i].used) return i;
    errno=EMFILE;return -1;
}
int cap_mpy_owned_open(const char *path,int flags,...)
{
    int slot=vacant();if (slot<0) return -1;
    int mode=0;
    if (flags&O_CREAT) {va_list args;va_start(args,flags);mode=va_arg(args,int);va_end(args);}
    int fd=open(path,flags,mode);
    if (fd>=0) {owned[slot].used=true;owned[slot].fd=fd;owned[slot].dir=NULL;}
    return fd;
}
int cap_mpy_owned_close(int fd)
{
    for (int i=0;i<USER_IO_LIMIT;i++) if (owned[i].used && !owned[i].dir && owned[i].fd==fd) {
        int result=close(fd);owned[i].used=false;return result;
    }
    /* A forged open(integer) must not close another service's descriptor. */
    errno=EBADF;return -1;
}
DIR *cap_mpy_owned_opendir(const char *path)
{
    int slot=vacant();if (slot<0) return NULL;
    DIR *dir=opendir(path);
    if (dir) {owned[slot].used=true;owned[slot].dir=dir;owned[slot].fd=-1;}
    return dir;
}
int cap_mpy_owned_closedir(DIR *dir)
{
    if (!dir) {errno=EBADF;return -1;}
    for (int i=0;i<USER_IO_LIMIT;i++) if (owned[i].used && owned[i].dir==dir) {
        int result=closedir(dir);owned[i].used=false;owned[i].dir=NULL;return result;
    }
    errno=EBADF;return -1;
}
void cap_mpy_owned_io_close_all(void)
{
    for (int i=0;i<USER_IO_LIMIT;i++) if (owned[i].used) {
        if (owned[i].dir) closedir(owned[i].dir);else close(owned[i].fd);
        owned[i].used=false;owned[i].dir=NULL;
    }
}

/* Only Python POSIX I/O is redirected here. Poll outside filesystem calls,
 * after their internal locks are released. The port has no Python threads.
 * Small native chunks bound how long a healthy SD operation delays stop. */
extern void cap_mpy_poll_hook(void);
#define USER_IO_CHUNK 4096
static bool owns_fd(int fd)
{
    for (int i=0;i<USER_IO_LIMIT;i++) if (owned[i].used && !owned[i].dir && owned[i].fd==fd) return true;
    errno=EBADF;return false;
}
ssize_t cap_mpy_owned_read(int fd,void *buffer,size_t size)
{
    if (!owns_fd(fd)) return -1;
    cap_mpy_poll_hook();
    ssize_t result=read(fd,buffer,size>USER_IO_CHUNK ? USER_IO_CHUNK : size);
    int saved_errno=errno;cap_mpy_poll_hook();errno=saved_errno;return result;
}
ssize_t cap_mpy_owned_write(int fd,const void *buffer,size_t size)
{
    if (!owns_fd(fd)) return -1;
    cap_mpy_poll_hook();
    ssize_t result=write(fd,buffer,size>USER_IO_CHUNK ? USER_IO_CHUNK : size);
    int saved_errno=errno;cap_mpy_poll_hook();errno=saved_errno;return result;
}
struct dirent *cap_mpy_owned_readdir(DIR *dir)
{
    for (int i=0;i<USER_IO_LIMIT;i++) if (owned[i].used && owned[i].dir==dir && dir) {
        cap_mpy_poll_hook();struct dirent *entry=readdir(dir);
        int saved_errno=errno;cap_mpy_poll_hook();errno=saved_errno;return entry;
    }
    errno=EBADF;return NULL;
}
