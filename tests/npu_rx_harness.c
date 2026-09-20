// SPDX-License-Identifier: GPL-2.0-only
// Kernel interfaces are mocked; the tested dequeue body comes from the patch.
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
typedef uint32_t u32;
typedef uint16_t u16;
#define BIT(n) (UINT32_C(1) << (n))
#define GENMASK(h,l) ((UINT32_MAX >> (31-(h))) & (UINT32_MAX << (l)))
#define FIELD_GET(m,v) (((u32)(v) & (m)) >> __builtin_ctz(m))
// The active CONFIG_NET_AIROHA_NPU path uses the Linux header, not the fallback.
#define NPU_RX_DMA_PKT_COUNT_MASK GENMASK(31,29)
#define NPU_RX_DMA_DESC_CUR_LEN_MASK GENMASK(14,1)
#define NPU_RX_DMA_DESC_DONE_MASK BIT(0)
#define max_t(t,a,b) ((t)(a) > (t)(b) ? (t)(a) : (t)(b))
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define MAX_SKB_FRAGS 17
#define READ_ONCE(x) (*(volatile __typeof__(x) *)&(x))
#define likely(x) (x)
#define unlikely(x) (x)
#define SKB_WITH_OVERHEAD(x) ((x)-384)
#define EINVAL 22
#define ERR_PTR(n) ((void *)(intptr_t)(n))
#define IS_ERR(p) ((uintptr_t)(p) > (uintptr_t)-4096)
#define Q_WRITE(q,r,v) ((void)(v))
struct airoha_npu_rx_dma_desc { u32 ctrl, info, data, addr; uint64_t reserved; };
struct page { unsigned id; };
struct skb_shared_info { int nr_frags; struct page *frags[MAX_SKB_FRAGS]; };
struct sk_buff { struct page *head; struct skb_shared_info shinfo; unsigned len; };
struct mt76_queue_entry { void *buf; uintptr_t dma_addr[2]; u16 dma_len[2]; };
struct mt76_queue { void *desc; struct mt76_queue_entry *entry; int tail,head,queued,ndesc,buf_size; void *page_pool; };
struct mt76_dev { void *dev,*dma_dev; };
static struct airoha_npu_rx_dma_desc descriptors[8];
static struct mt76_queue_entry entries[8];
static struct page pages[8];
static struct sk_buff skbs[32];
static unsigned returned[8], releases,bad_release,bad_sync,syncs,allocs,logs,barriers;
static bool fail_alloc, staged_info;
static struct mt76_queue q;
static struct mt76_dev dev;
void *memset(void *p,int v,size_t n) { unsigned char *b=p; for(size_t i=0;i<n;i++)b[i]=v; return p; }
static void dma_rmb(void) { barriers++; if(staged_info){descriptors[q.tail].info=2u<<29;staged_info=false;} }
#define dev_err_ratelimited(...) ((void)logs++)
static int page_pool_get_dma_dir(void *p) {(void)p; return 2;}
static void dma_sync_single_for_cpu(void *d,uintptr_t addr,unsigned len,int dir) {
    (void)d;(void)len;(void)dir; syncs++; unsigned id=(unsigned)(addr/4096)-1;
    if(id>=8 || returned[id])bad_sync++;
}
static struct sk_buff *napi_build_skb(void *buf,int size) {
    (void)size; if(fail_alloc)return NULL;
    struct sk_buff *s=&skbs[allocs++]; memset(s,0,sizeof(*s));s->head=buf;return s;
}
static void release_page(struct page *p) {if(!p || p->id>=8){bad_release++;return;} if(returned[p->id]++)bad_release++; releases++;}
static void mt76_put_page_pool_buf(void *p,bool direct) {(void)direct;release_page(p);}
static void dev_kfree_skb(struct sk_buff *s) {if(!s)return;release_page(s->head);for(int i=0;i<s->shinfo.nr_frags;i++)release_page(s->shinfo.frags[i]);}
static void __skb_put(struct sk_buff *s,int len) {s->len+=len;}
static void skb_reset_mac_header(struct sk_buff *s) {(void)s;}
static void skb_mark_for_recycle(struct sk_buff *s) {(void)s;}
static struct skb_shared_info *skb_shinfo(struct sk_buff *s){return &s->shinfo;}
static struct page *virt_to_head_page(void *p){return p;}
static void *page_address(struct page *p){return p;}
static void skb_add_rx_frag(struct sk_buff *s,int i,struct page *p,size_t off,int len,int cap){
    (void)off;(void)cap;s->shinfo.frags[i]=p;s->shinfo.nr_frags=i+1;s->len+=len;
}
#include "dequeue.h"
#ifdef _WIN32
__declspec(dllexport)
#endif
void run_case(int c,u32 *out) {
    memset(descriptors,0,sizeof(descriptors));memset(entries,0,sizeof(entries));memset(returned,0,sizeof(returned));
    releases=bad_release=bad_sync=syncs=allocs=logs=barriers=0;fail_alloc=staged_info=false;
    q=(struct mt76_queue){.desc=descriptors,.entry=entries,.tail=0,.head=4,.queued=4,.ndesc=8,.buf_size=2184};
    for(int i=0;i<8;i++){pages[i].id=i;entries[i].buf=&pages[i];entries[i].dma_addr[0]=(i+1)*4096;entries[i].dma_len[0]=1800;}
    int count=1,early=0;u32 info=0;struct sk_buff *s;
    if(c==1 || c==2 || c==3 || c==11 || c==12)count=2;
    if(c==2){q.tail=7;q.head=3;}
    if(c==8){count=7;q.queued=7;q.head=7;}
    for(int i=0;i<count;i++){int at=(q.tail+i)%8;descriptors[at].ctrl=(128<<1)|1;descriptors[at].info=(count<<29)|0x10000000|i;}
    if(c==1)descriptors[1].ctrl&=~1u;
    if(c==3)fail_alloc=true;
    if(c==4)descriptors[0].ctrl=(1801<<1)|1;
    if(c==5)descriptors[0].ctrl=1;
    if(c==6)q.queued=0;
    if(c==7){q.queued=1;descriptors[0].info=7u<<29;}
    if(c==9)entries[0].dma_addr[0]=0;
    if(c==10)entries[0].buf=NULL;
    if(c==11){descriptors[0].info=1u<<29;staged_info=true;}
    if(c==12)descriptors[1].ctrl=(1801<<1)|1;
    if(c==13)q.queued=-1;
    if(c==1){for(int i=0;i<4;i++){s=mt76_npu_dequeue(&dev,&q,&info);if(s || releases || syncs || q.tail || q.queued!=4)early++;}descriptors[1].ctrl|=1;}
    s=mt76_npu_dequeue(&dev,&q,&info);
    out[0]=s && !IS_ERR(s);out[1]=IS_ERR(s);out[2]=q.tail;out[3]=q.queued;
    out[8]=out[0]?s->len:0;out[9]=out[0]?s->shinfo.nr_frags:0;
    if(out[0])dev_kfree_skb(s);
    out[4]=releases;out[5]=bad_release;out[6]=bad_sync;out[7]=syncs;
    out[10]=logs;out[11]=early;out[12]=barriers;out[13]=info;
}
