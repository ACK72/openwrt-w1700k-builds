/* SPDX-License-Identifier: GPL-2.0-only */
typedef unsigned int u32;
#define NULL ((void *)0)
#define IFNAMSIZ 16
#define NAPI_POLL_WEIGHT 64
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#ifndef CONFIG_ARCH_AIROHA
#define CONFIG_ARCH_AIROHA 1
#endif
#define IS_ENABLED(x) (x)
#include "rxq_enum.h"
struct napi_struct { int weight; int (*poll)(struct napi_struct *, int); char name[IFNAMSIZ]; };
struct net_device { char name[IFNAMSIZ]; int threaded; };
struct mt76_dev { int chip; struct net_device *napi_dev; struct napi_struct napi[__MT_RXQ_MAX]; };
static int is_mt7996(struct mt76_dev *dev) { return dev->chip == 0x7996; }
static u32 calls, named;
static int same(const char *a, const char *b) {
    while (*a && *a == *b) { a++; b++; }
    return *a == *b;
}
static int snprintf(char *out, unsigned long long size, const char *format, ...) {
    __builtin_va_list args;
    __builtin_va_start(args, format);
    const char *phy=__builtin_va_arg(args, const char *);
    const char *role=__builtin_va_arg(args, const char *);
    __builtin_va_end(args);
    const char *parts[] = { "napi/", phy, "-", role };
    unsigned long long len=0;
    if (!same(format,"napi/%s-%s")) return 999;
    for (unsigned int p=0;p<ARRAY_SIZE(parts);p++)
        for (const char *s=parts[p];*s;s++,len++)
            if (len+1<size) out[len]=*s;
    if (size) out[len<size?len:size-1]=0;
    return len;
}
static void netif_napi_add_weight_named(struct net_device *dev, struct napi_struct *n,
                                      int (*poll)(struct napi_struct *, int), int weight, const char *name) {
    calls++; named++; n->weight=weight; n->poll=poll;
    for (int i=0;i<IFNAMSIZ;i++) { n->name[i]=name[i]; if (!name[i]) break; }
}
static void netif_napi_add(struct net_device *dev, struct napi_struct *n,
                           int (*poll)(struct napi_struct *, int)) {
    calls++; n->weight=NAPI_POLL_WEIGHT; n->poll=poll; n->name[0]=0;
}
#include "wifi_napi_functions.h"
static int rx_poll(struct napi_struct *n, int budget) { return budget; }
static int npu_poll(struct napi_struct *n, int budget) { return budget; }

void run_case(int mode, u32 *out) {
    struct mt76_dev dev;
    struct net_device net;
    for (unsigned int i=0;i<sizeof(dev);i++) ((volatile char *)&dev)[i]=0;
    for (unsigned int i=0;i<sizeof(net);i++) ((volatile char *)&net)[i]=0;
    const char *phy = mode==22 ? "phy12345678" : mode==21 ? "phy10" : "phy0";
    for (int i=0;phy[i];i++) net.name[i]=phy[i];
    int q=mode<21 ? mode : MT_RXQ_NPU0;
    dev.chip=mode==24 ? 0x7990 : 0x7996;
    dev.napi_dev=&net; net.threaded=mode!=23; calls=named=0;
    int (*poll)(struct napi_struct *, int) = q>=MT_RXQ_NPU0 ? npu_poll : rx_poll;
    mt76_rx_napi_add(&dev, q, poll);
    /* The caller's netdev name may change; registered queue identity is copied. */
    net.name[0]='X';
    out[0]=calls; out[1]=named; out[2]=dev.napi[q].weight;
    out[3]=dev.napi[q].poll==poll; out[4]=net.threaded;
    for (int i=0;i<IFNAMSIZ;i++) out[5+i]=(unsigned char)dev.napi[q].name[i];
}
