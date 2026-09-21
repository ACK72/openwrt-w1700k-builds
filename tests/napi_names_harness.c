/* SPDX-License-Identifier: GPL-2.0-only */
/* The kernel keeps kthread full_name separately from task comm. */
typedef unsigned int u32;
#define NULL ((void *)0)
#define IFNAMSIZ 16
#define NAPI_POLL_WEIGHT 64
#define NETDEV_NAPI_THREADED_DISABLED 0
enum { NAPI_STATE_LISTED, NAPI_STATE_SCHED, NAPI_STATE_NPSVC, NAPI_STATE_NO_BUSY_POLL };
struct task_struct { char comm[16]; char full_name[64]; };
struct net_device {
    int locked, threaded, napi_defer_hard_irqs, gro_flush_timeout;
    char name[IFNAMSIZ];
};
struct napi_struct {
    struct task_struct *thread;
    struct net_device *dev;
    unsigned long state;
    int weight, list_owner, napi_id, irq;
    int (*poll)(struct napi_struct *, int);
    void *skb;
    char thread_name[IFNAMSIZ];
};
struct airoha_eth;
struct airoha_qdma { struct airoha_eth *eth; };
struct airoha_eth { struct airoha_qdma qdma[2]; struct net_device *napi_dev; };
static u32 *output;
static int fail_thread;
static struct task_struct task;
static int same(const char *a, const char *b) {
    while (*a && *a == *b) { a++; b++; }
    return *a == *b;
}
static int strscpy(char *to, const char *from, unsigned long long size) {
    int i = 0;
    while (i + 1 < size && from[i]) { to[i] = from[i]; i++; }
    to[i] = 0;
    return i;
}
static void netdev_lock(struct net_device *dev) {
    if (dev->locked) output[0]++;
    dev->locked = 1; output[1]++;
}
static void netdev_unlock(struct net_device *dev) {
    if (!dev->locked) output[0]++;
    dev->locked = 0; output[2]++;
}
static void netdev_assert_locked(struct net_device *dev) {
    if (!dev->locked) output[0]++;
}
static void set_bit(int bit, unsigned long *state) { *state |= 1ul << bit; }
static int test_and_set_bit(int bit, unsigned long *state) {
    int old = !!(*state & (1ul << bit)); set_bit(bit, state); return old;
}
#define WARN_ON(x) (x)
#define INIT_LIST_HEAD(...) ((void)0)
#define INIT_HLIST_NODE(...) ((void)0)
#define hrtimer_setup(...) ((void)0)
#define gro_init(...) ((void)0)
#define netdev_err_once(...) ((void)0)
#define READ_ONCE(x) (x)
#define napi_set_defer_hard_irqs(...) ((void)0)
#define napi_set_gro_flush_timeout(...) ((void)0)
#define napi_get_frags_check(...) ((void)0)
#define IS_ERR(x) ((long long)(x) < 0)
#define PTR_ERR(x) ((int)(long long)(x))
#define pr_err(...) ((void)0)
static void netif_napi_dev_list_add(struct net_device *dev, struct napi_struct *n) { n->napi_id = 7; }
static int napi_get_threaded_config(struct net_device *dev, struct napi_struct *n) { return dev->threaded; }
static void netif_napi_set_irq_locked(struct napi_struct *n, int irq) {
    netdev_assert_locked(n->dev); n->irq = irq;
}
static int napi_threaded_poll(void *unused) { return 0; }
static struct task_struct *kthread_run(int (*poll)(void *), struct napi_struct *n, const char *fmt, ...) {
    __builtin_va_list args;
    netdev_assert_locked(n->dev);
    if (poll != napi_threaded_poll) output[0]++;
    output[3]++;
    if (fail_thread) return (struct task_struct *)-12;
    __builtin_va_start(args, fmt);
    const char *name = __builtin_va_arg(args, const char *);
    if (same(fmt, "%s")) {
        strscpy(task.full_name, name, sizeof(task.full_name));
    } else if (same(fmt, "napi/%s-%d")) {
        int id = __builtin_va_arg(args, int);
        if (!same(name, "dummy") || id != 7) output[0]++;
        strscpy(task.full_name, "napi/dummy-7", sizeof(task.full_name));
    } else {
        output[0]++;
    }
    __builtin_va_end(args);
    strscpy(task.comm, task.full_name, sizeof(task.comm));
    return &task;
}
static int snprintf(char *to, unsigned long long size, const char *fmt, ...) {
    const char prefix[] = "napi/qdma";
    __builtin_va_list args;
    __builtin_va_start(args, fmt);
    int qdma = __builtin_va_arg(args, int);
    int type = __builtin_va_arg(args, int);
    int id = __builtin_va_arg(args, int);
    __builtin_va_end(args);
    if (!same(fmt, "napi/qdma%d-%c%d") || size != IFNAMSIZ) output[0]++;
    int n = 0;
    while (prefix[n]) { to[n] = prefix[n]; n++; }
    to[n++] = '0' + qdma; to[n++] = '-'; to[n++] = type;
    if (id >= 10) to[n++] = '0' + id / 10;
    to[n++] = '0' + id % 10; to[n] = 0;
    return n;
}
#include "napi_names_functions.h"
static int rx_poll(struct napi_struct *n, int budget) { return 0; }
static int tx_poll(struct napi_struct *n, int budget) { return 0; }

void run_case(int mode, u32 *out) {
    output = out; fail_thread = mode == 72 || mode == 76;
    struct net_device dev;
    struct napi_struct napi;
    struct airoha_eth eth;
    /* Freestanding Windows harness: avoid implicit CRT memset calls. */
    for (unsigned int i = 0; i < sizeof(dev); i++) ((volatile char *)&dev)[i] = 0;
    for (unsigned int i = 0; i < sizeof(napi); i++) ((volatile char *)&napi)[i] = 0;
    for (unsigned int i = 0; i < sizeof(task); i++) ((volatile char *)&task)[i] = 0;
    dev.threaded = mode != 71; strscpy(dev.name, "dummy", sizeof(dev.name));
    for (int i = 0; i < 2; i++) eth.qdma[i].eth = &eth;
    eth.napi_dev = &dev;
    int tx = mode < 68 && mode % 34 >= 32;
    int (*poll)(struct napi_struct *, int) = tx ? tx_poll : rx_poll;
    if (mode < 68) {
        int ring = mode % 34;
        airoha_qdma_add_napi(&eth.qdma[mode / 34], &napi, poll,
                            tx ? 't' : 'r', tx ? ring - 32 : ring);
    } else if (mode == 68) {
        strscpy(napi.thread_name, "stale", sizeof(napi.thread_name));
        netdev_lock(&dev);
        netif_napi_add_weight_locked(&dev, &napi, poll, 64);
        netdev_unlock(&dev);
    } else {
        const char *names[] = {"", "0123456789abcdefghijkl", "deferred", "retry",
                               "recreated", "original", "%s%d%n", "failed"};
        netif_napi_add_weight_named(&dev, &napi, poll, 64, names[mode - 69]);
    }
    if (mode == 71 || mode == 72 || mode == 73) {
        /* Name storage survives the caller and an absent/stopped thread. */
        napi.thread = NULL; fail_thread = 0;
        if (mode == 71) dev.threaded = 1;
        netdev_lock(&dev); napi_kthread_create(&napi); netdev_unlock(&dev);
    }
    if (mode == 74)
        netif_napi_add_weight_named(&dev, &napi, tx_poll, 32, "replacement");
    out[4] = napi.weight;
    out[5] = !!(napi.state & (1ul << NAPI_STATE_NO_BUSY_POLL));
    out[6] = napi.poll == poll;
    out[7] = dev.threaded;
    out[8] = napi.thread != NULL;
    out[9] = napi.irq == -1;
    /* procfs uses full_name, not the shorter mutable task comm. */
    if (napi.thread) for (int i = 0; i < 16; i++) out[10 + i] = task.full_name[i];
    out[26] = dev.locked;
    out[27] = napi.thread_name[15];
    out[28] = (napi.state & 7) == 7;
}
