/* Real pending helpers, data burst and worker; hardware/mac80211 are mocks.
 * Test admission, list integrity, FIFO and fairness, not RF or PCIe timing.
 */
#define NULL ((void *)0)
#define bool int
#define true 1
#define false 0
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define MT_TXQ_FREE_THR 32
#define MT_MAX_NON_AQL_PKT 16
#define MT76_RESET 0
#define MT_WCID_FLAG_PS 0
#define MT_DRV_HW_MGMT_TXQ 1
#define MT_DRV_HW_PS_BUFFERING 2
#define IEEE80211_TX_CTL_HW_80211_ENCAP 1
#define MT_WCID_TX_INFO_SET 1
void *memset(void *ptr, int value, __SIZE_TYPE__ n) {
    volatile unsigned char *p = ptr;
    while (n--) *p++ = value;
    return ptr;
}
#define READ_ONCE(x) (x)
#define min_t(t,a,b) ((t)(a) < (t)(b) ? (t)(a) : (t)(b))
#define max_t(t,a,b) ((t)(a) > (t)(b) ? (t)(a) : (t)(b))
enum mt76_txq_id { MT_TXQ_BE, MT_TXQ_BK = 3, MT_TXQ_PSD };
struct list_head { struct list_head *next, *prev; };
#define LIST_HEAD(n) struct list_head n = { &(n), &(n) }
static void INIT_LIST_HEAD(struct list_head *h) { h->next = h->prev = h; }
static int list_empty(struct list_head *h) { return h->next == h; }
static void list_add_tail(struct list_head *n, struct list_head *h) {
    n->next = h; n->prev = h->prev; h->prev->next = n; h->prev = n;
}
static void list_del_init(struct list_head *n) {
    n->next->prev = n->prev; n->prev->next = n->next; INIT_LIST_HEAD(n);
}
static void list_move(struct list_head *n, struct list_head *h) {
    list_del_init(n);
    n->next = h->next; n->prev = h; h->next->prev = n; h->next = n;
}
static void list_splice(struct list_head *src, struct list_head *dst) {
    struct list_head *first = src->next, *last = src->prev, *next = dst->next;
    if (list_empty(src)) return;
    first->prev = dst; dst->next = first; last->next = next; next->prev = last;
}
static void list_splice_init(struct list_head *src, struct list_head *dst) {
    list_splice(src, dst); INIT_LIST_HEAD(src);
}
#define list_first_entry(h,t,m) ((t *)((char *)(h)->next - __builtin_offsetof(t,m)))
static unsigned lock_errors, locks, bh_depth, rcu_depth;
static void spin_lock(int *lock) { if (*lock) lock_errors++; *lock = 1; locks++; }
static void spin_unlock(int *lock) { if (!*lock) lock_errors++; *lock = 0; locks--; }
static void local_bh_disable(void) { bh_depth++; }
static void local_bh_enable(void) { bh_depth--; }
static void rcu_read_lock(void) { rcu_depth++; }
static void rcu_read_unlock(void) { rcu_depth--; }
struct ieee80211_hdr { int frame_control; };
struct ieee80211_tx_info { int flags; struct { void *vif; int rates[4]; } control; };
struct sk_buff {
    struct ieee80211_hdr hdr;
    struct ieee80211_tx_info info;
    void *data;
    int qid, seq, regular;
    struct sk_buff *next;
};
struct sk_buff_head { int lock; struct sk_buff *head, *tail; };
struct ieee80211_sta { int unused; };
struct ieee80211_txq { struct ieee80211_sta *sta; void *vif; };
struct mt76_txq { struct ieee80211_txq txq; int remaining; };
struct mt76_wcid {
    int tx_info, non_aql_packets, sent, expect, enqueued;
    unsigned long flags;
    struct sk_buff_head tx_pending, tx_offchannel;
    struct list_head tx_list;
};
struct mt76_queue {
    int lock, stopped, blocked, queued, ndesc;
    bool tx_pending_last;
    unsigned short tx_pending_budget;
};
struct mt76_dev;
struct mt76_phy {
    struct mt76_dev *dev;
    int hw, id, offchannel, tx_lock;
    unsigned long state;
    struct mt76_queue *q_tx[5];
    struct mt76_wcid wcid[2], data_wcid;
    struct mt76_txq data_txq;
    struct list_head tx_list;
};
struct driver { int drv_flags; };
struct queue_ops { void (*kick)(struct mt76_dev *, struct mt76_queue *); };
struct mt76_dev {
    struct mt76_phy phy;
    struct mt76_phy *phys[3];
    struct driver *drv;
    struct queue_ops *queue_ops;
    int tx_worker;
    unsigned char tx_pending_head;
};
struct mt76_tx_pending { int budget; bool reserve, deferred; };
static unsigned regular[3], sent[3], payload, fifo_errors, list_errors;
static unsigned schedules, data_calls, max_pending_pass, max_pending_single;
static unsigned frame_id, self_wake, completion_each, inject, data_fail;
static struct sk_buff packets[8192], data_packet;
static void add(struct mt76_phy *, int, int, int, int);
#define IEEE80211_SKB_CB(s) (&(s)->info)
static int skb_get_queue_mapping(struct sk_buff *s) { return s->qid; }
static int ieee80211_is_data_present(int fc) { return fc == 1; }
static int ieee80211_is_bufferable_mmpdu(struct sk_buff *s) { return 0; }
static int ieee80211_is_deauth(int fc) { return 0; }
static int ieee80211_is_disassoc(int fc) { return 0; }
static int test_bit(int b, unsigned long *s) { return !!(*s & (1ul << b)); }
static int atomic_read(int *x) { return *x; }
static struct mt76_wcid *mt76_wcid_primary(struct mt76_wcid *w) { return w; }
static struct ieee80211_txq *mtxq_to_txq(struct mt76_txq *t) { return &t->txq; }
static int mt76_txq_get_qid(struct ieee80211_txq *t) { return MT_TXQ_BE; }
static int ieee80211_txq_aql_pending(int hw, struct ieee80211_txq *t) { return 0; }
static void ieee80211_get_tx_rates(void *v, struct ieee80211_sta *s, struct sk_buff *b, int *r, int n) { }
static void ieee80211_sta_eosp(struct ieee80211_sta *s) { }
static struct sk_buff *mt76_txq_dequeue(struct mt76_phy *p, struct mt76_txq *t) {
    if (!t->remaining) return NULL;
    t->remaining--; data_packet.regular = 1; return &data_packet;
}
static struct sk_buff *skb_peek(struct sk_buff_head *h) { return h->head; }
static int skb_queue_empty(struct sk_buff_head *h) { return !h->head; }
static void __skb_unlink(struct sk_buff *s, struct sk_buff_head *h) {
    h->head = s->next; if (!h->head) h->tail = NULL;
}
static struct ieee80211_sta *wcid_to_sta(struct mt76_wcid *w) { return NULL; }
static void kick(struct mt76_dev *d, struct mt76_queue *q) { }
static void mt76_worker_schedule(int *worker) { self_wake = 1; schedules++; }
static int __mt76_tx_queue_skb(struct mt76_phy *p, int qid, struct sk_buff *s,
                             struct mt76_wcid *w, struct ieee80211_sta *sta, bool *stop) {
    struct mt76_queue *q = p->q_tx[qid];
    if (s->regular && data_fail) return -1;
    if (q->queued + MT_TXQ_FREE_THR >= q->ndesc) list_errors++;
    q->queued++;
    if (s->regular) regular[p->id]++;
    else {
        sent[p->id]++; w->sent++;
        if (s->seq != w->expect++) fifo_errors++;
        payload += ieee80211_is_data_present(s->hdr.frame_control);
        if (inject) { inject = 0; add(p, 0, 1, 0, 0); add(p, 1, 1, 1, 0); }
    }
    if (completion_each) q->queued--;
    return 0;
}
#include "burst_functions.h"
static void mt76_txq_schedule(struct mt76_phy *p, enum mt76_txq_id qid) {
    int i;
    data_calls++;
    if (qid) return;
    for (i = 0; i < 3; i++) {
        struct mt76_phy *t = p->dev->phys[i];
        if (!t || t->hw != p->hw || t->offchannel || test_bit(MT76_RESET, &t->state)) continue;
        if (!mt76_txq_stopped(t->q_tx[0]))
            mt76_txq_send_burst(t, t->q_tx[0], &t->data_txq, &t->data_wcid);
    }
}
#include "priority_functions.h"
static void add(struct mt76_phy *p, int wi, int n, int data, int offchannel) {
    struct mt76_wcid *w = &p->wcid[wi];
    struct sk_buff_head *h = offchannel ? &w->tx_offchannel : &w->tx_pending;
    while (n--) {
        struct sk_buff *s = &packets[frame_id++];
        s->hdr.frame_control = data; s->data = &s->hdr; s->info.flags = 0;
        s->qid = 0; s->seq = w->enqueued++; s->regular = 0; s->next = NULL;
        if (h->tail) h->tail->next = s; else h->head = s;
        h->tail = s;
    }
    if (list_empty(&w->tx_list)) list_add_tail(&w->tx_list, &p->tx_list);
}
static void check_lists(struct mt76_phy *p) {
    struct list_head *n;
    int seen[2] = {0}, len = 0, j;
    for (n = p->tx_list.next; n != &p->tx_list && len < 10; n = n->next) {
        if (n->next->prev != n || n->prev->next != n) list_errors++;
        len++;
        for (j = 0; j < 2; j++) if (n == &p->wcid[j].tx_list) seen[j]++;
    }
    if (len > 2) list_errors++;
    for (j = 0; j < 2; j++) {
        int nonempty = !skb_queue_empty(&p->wcid[j].tx_pending) || !skb_queue_empty(&p->wcid[j].tx_offchannel);
        /* Concurrent enqueue may leave an empty WCID linked until next pass. */
        if (seen[j] > 1 || (nonempty && seen[j] != 1)) list_errors++;
    }
}
int run_case(int mode, unsigned *out) {
    struct mt76_dev dev = {0};
    struct mt76_phy p1 = {0}, p2 = {0};
    struct mt76_phy *phys[3] = {&dev.phy, &p1, &p2};
    struct mt76_queue rings[3] = {{0}};
    struct driver drv = {MT_DRV_HW_MGMT_TXQ};
    struct queue_ops ops = {kick};
    int i, j, step, passes = 10, capacity = 8, follow_wake = 0, loops = 0;
    dev.drv = &drv; dev.queue_ops = &ops;
    frame_id = schedules = self_wake = payload = fifo_errors = list_errors = 0;
    completion_each = inject = data_fail = data_calls = max_pending_pass = max_pending_single = 0;
    lock_errors = locks = bh_depth = rcu_depth = 0;
    for (i = 0; i < 3; i++) {
        regular[i] = sent[i] = 0;
        phys[i]->id = i; phys[i]->dev = &dev; dev.phys[i] = phys[i];
        INIT_LIST_HEAD(&phys[i]->tx_list);
        for (j = 0; j < 2; j++) INIT_LIST_HEAD(&phys[i]->wcid[j].tx_list);
        phys[i]->data_wcid.tx_info = MT_WCID_TX_INFO_SET;
        rings[i].ndesc = 512;
        for (j = 0; j < 5; j++) phys[i]->q_tx[j] = &rings[i == 2 ? 1 : i];
    }
    p1.data_txq.remaining = 4096;
    switch (mode) {
    case 0: add(&p2, 0, 1, 0, 0); break;
    case 1: add(&p1, 0, 80, 1, 0); add(&p2, 0, 1, 0, 0); break;
    case 2: add(&p2, 0, 80, 1, 0); break;
    case 3: add(&p1, 0, 80, 0, 0); add(&p2, 0, 80, 0, 0); break;
    case 4: add(&p2, 0, 80, 0, 0); p2.state = 1; break;
    case 5: add(&p2, 0, 80, 0, 0); p2.offchannel = 1; break;
    case 6: add(&p2, 0, 1, 0, 1); p2.offchannel = 1; break;
    case 7: add(&p2, 0, 80, 0, 0); capacity = 0; break;
    case 8: add(&p2, 0, 400, 1, 0); capacity = 480; passes = 1; follow_wake = 1; p1.data_txq.remaining = 0; break;
    case 9: break;
    case 10: case 11: case 12:
        add(&p1, 0, 80, 0, 0); add(&p2, 0, 80, 0, 0);
        capacity = 1; passes = mode == 10 ? 18 : 54;
        if (mode == 12) dev.phy.data_txq.remaining = 4096;
        break;
    case 13: add(&p1, 0, 80, 1, 0); add(&p2, 0, 80, 1, 0); p1.data_txq.remaining = 0; break;
    case 14: add(&p1, 0, 80, 1, 0); add(&p1, 1, 80, 1, 0); break;
    case 15: add(&p2, 0, 60, 1, 0); add(&p2, 0, 1, 0, 0); passes = 20; break;
    case 16: dev.phys[1] = NULL; p2.data_txq.remaining = 4096; add(&p2, 0, 1, 0, 0); break;
    case 17: dev.phys[2] = NULL; add(&dev.phy, 0, 1, 0, 0); break;
    case 18:
        p1.hw = 1; p2.hw = 2;
        for (i = 0; i < 5; i++) p2.q_tx[i] = &rings[2];
        add(&p2, 0, 80, 1, 0); add(&p1, 0, 1, 0, 0); break;
    case 19:
        dev.phys[1] = dev.phys[2] = NULL;
        dev.phy.data_txq.remaining = 4096; add(&dev.phy, 0, 80, 1, 0); break;
    case 20: add(&p2, 0, 80, 1, 0); rings[1].blocked = 1; break;
    case 21: add(&p2, 0, 80, 1, 0); p1.state = p2.state = dev.phy.state = 1; break;
    case 22: add(&p2, 0, 1, 0, 0); inject = 1; break;
    case 23: add(&p2, 0, 400, 1, 0); completion_each = 1; p1.data_txq.remaining = 0; capacity = 480; passes = 1; follow_wake = 1; break;
    case 24: add(&p2, 0, 80, 1, 0); p1.data_wcid.non_aql_packets = MT_MAX_NON_AQL_PKT; break;
    case 25: add(&p2, 0, 80, 1, 0); data_fail = 1; break;
    case 26: rings[1].tx_pending_last = 1; capacity = 1; passes = 3; break;
    case 27: add(&p2, 0, 400, 1, 0); capacity = 480; passes = 1; break;
    }
    for (step = 0; step < passes; step++) {
        int free = ((mode == 11 || mode == 12) && step % 3) ? 0 : capacity;
        for (i = 0; i < 3; i++) rings[i].queued = 512 - MT_TXQ_FREE_THR - (i == 0 && mode == 12 ? 8 : free);
        if (mode == 26 && step == 1) add(&p2, 0, 1, 0, 0);
        do {
            unsigned before = sent[0] + sent[1] + sent[2], saved[3];
            for (i = 0; i < 3; i++) saved[i] = sent[i];
            self_wake = 0;
            if (mode == 27) mt76_txq_schedule_pending(&p2);
            else mt76_tx_worker_run(&dev);
            loops++;
            if (sent[0] + sent[1] + sent[2] - before > max_pending_pass)
                max_pending_pass = sent[0] + sent[1] + sent[2] - before;
            for (i = 0; i < 3; i++) {
                if (sent[i] - saved[i] > max_pending_single) max_pending_single = sent[i] - saved[i];
                check_lists(phys[i]);
            }
        } while (follow_wake && self_wake && loops < 100);
    }
    for (i = 0; i < 3; i++) { out[i] = regular[i]; out[i+3] = sent[i]; }
    out[6] = payload; out[7] = schedules; out[8] = data_calls;
    out[9] = fifo_errors; out[10] = list_errors; out[11] = max_pending_pass;
    out[12] = max_pending_single; out[13] = loops;
    out[14] = p1.wcid[0].sent; out[15] = p1.wcid[1].sent;
    out[16] = p2.wcid[0].sent; out[17] = p2.wcid[1].sent;
    out[18] = lock_errors + locks + bh_depth + rcu_depth;
    return 0;
}
