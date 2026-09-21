/* Mock kernel boundaries around the actual patched mt7996 recovery functions.
 * This verifies sequencing/ownership, not DMA hardware or firmware behaviour.
 */
typedef unsigned int u32;
typedef __SIZE_TYPE__ size_t;
void *memset(void *p, int v, size_t n) {
    volatile unsigned char *s=p;
    while(n--) *s++=v;
    return p;
}
typedef _Bool bool;
#define true 1
#define false 0
#define NULL ((void *)0)
#define ETIMEDOUT 110
#define EIO 5
#define MT76_RESET 0
#define MT76_MCU_RESET 1
#define MT76_STATE_MCU_RUNNING 2
#define MT76_STATE_RUNNING 3
#define MT76_HWRRO_V3 3
#define MT7996_WTBL_STA 100
#define MT7996_WATCHDOG_TIME 100
#define MT_MCU_CMD_WA_WDT 1
#define MT_MCU_CMD_WDT_MASK 3
#define MT_MCU_CMD_STOP_DMA 4
#define MT_MCU_CMD_RESET_DONE 8
#define MT_MCU_CMD_RECOVERY_DONE 16
#define MT_MCU_CMD_NORMAL_STATE 32
#define MT_MCU_INT_EVENT_DMA_STOPPED 1
#define MT_MCU_INT_EVENT_DMA_INIT 2
#define MT_MCU_INT_EVENT_RESET_DONE 3
#define MT_INT1_MASK_CSR 0
#define MT_INT1_SOURCE_CSR 1
#define MT_PCIE_MAC_INT_ENABLE 2
#define MT_PCIE1_MAC_INT_ENABLE 3
#define MT_INT_MASK_CSR 4
#define MT_INT_SOURCE_CSR 5
#define MT_INT_TX_DONE_BAND2 6
#define MT_INT_PCIE1_MASK_CSR 7
#define MT_INT_TX_RX_DONE_EXT 8
#define MT_WFDMA0_MCU_HOST_INT_ENA 9
#define MT_INT_MCU_CMD 10
#define MT_MCU_INT_EVENT 11
#define MT_RRO_3_0_EMU_CONF 12
#define MT_RRO_3_0_EMU_CONF_EN_MASK 13
#define IEEE80211_IFACE_SKIP_SDATA_NOT_IN_DRIVER 0
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define container_of(p,t,m) ((t *)((char *)(p)-(size_t)&((t *)0)->m))
#define LIST_HEAD(n) int n=0
#define INIT_LIST_HEAD(p) ((void)0)
#define list_empty(p) 1
#define list_first_entry(p,t,m) ((t *)0)
#define list_del_init(p) ((void)0)
#define list_splice_init(a,b) ((void)0)
#define kfree(p) ((void)0)
#define spin_lock_bh(p) ((void)0)
#define spin_unlock_bh(p) ((void)0)
#define local_bh_disable() ((void)0)
#define local_bh_enable() ((void)0)
#define mt76_wr(...) ((void)0)
#define mt76_clear(...) ((void)0)
#define mt76_set(...) ((void)0)
#define dev_err(...) ((void)0)
#define dev_info(...) ((void)0)
#define wake_up(p) ((void)0)
#define tasklet_schedule(p) ((void)0)
#define dev_is_pci(p) 1
#define wiphy_name(p) "mock"
struct work_struct { int unused; };
struct ieee80211_hw { int wiphy; };
struct mt76_queue { int ndesc, kind; };
struct mt76_phy { unsigned long state; struct work_struct mac_work; };
struct mt7996_phy { struct mt76_phy *mt76; int omac_mask; };
struct mt76_dev {
    struct mt76_phy phy;
    struct mt76_phy *phys[3];
    struct { int irqmask, wed, wed_hif2; } mmio;
    struct { int wait; } mcu;
    struct { int idx; } global_wcid;
    int mutex, tx_worker, napi[5], tx_napi, bus_hung, token, wcid_mask;
    int irq_tasklet, hwrro_mode, dev;
    struct ieee80211_hw *hw;
    struct mt76_queue q_rx[5];
};
struct mt7996_dev {
    union { struct mt76_dev mt76; struct { struct mt76_phy mphy; }; };
    struct mt7996_phy phy[3];
    struct { bool hw_full_reset, hw_init_done, restart, failed;
             u32 state, wa_reset_count, wm_reset_count; } recovery;
    struct { struct work_struct work; int lock, poll_list; } wed_rro;
    struct work_struct reset_work;
    int hif2, mld_idx_mask, mld_remap_idx_mask, sta_rc_list, twt_list;
};
struct mt7996_wed_rro_session_id { int list; };
static int fault, issues, stopped, wakes, restarted, dma_resets, fw_attempts;
static int npu_stops, npu_inits, reclaimed, scans, rocs, beacon_grace, scheduled;
static struct mt7996_dev *active;
static int wed_mode;
#define mt7996_for_each_phy(d,p) for ((p)=(d)->phy;(p)<(d)->phy+3;(p)++)
#define mt76_for_each_q_rx(d,i) for ((i)=0;(i)<5;(i)++)
static struct ieee80211_hw *mt76_hw(struct mt7996_dev *d) { return d->mt76.hw; }
static void set_bit(int b,unsigned long *v) { *v |= 1ul<<b; }
static void clear_bit(int b,unsigned long *v) { *v &= ~(1ul<<b); }
static int test_bit(int b,unsigned long *v) { return !!(*v & (1ul<<b)); }
static void atomic_set(int *p,int v) { *p=v; }
static void mutex_lock(int *p) { if ((*p)++) issues++; }
static void mutex_unlock(int *p) { if (--*p) issues++; }
static int mtk_wed_device_active(int *p) { return wed_mode; }
static int mt76_npu_device_active(struct mt76_dev *d) { return !wed_mode; }
static int mt76_queue_is_npu_txfree(struct mt76_queue *q) { return q->kind==2; }
static int mt76_queue_is_wed_rro(struct mt76_queue *q) { return q->kind==1; }
static int mt76_queue_is_wed_rro_ind(struct mt76_queue *q) { return q->kind==1; }
static int mt76_queue_is_wed_rro_msdu_pg(struct mt76_queue *q) { return 0; }
static void napi_disable(int *n) { if (*n!=1) issues++; *n=0; }
static void napi_enable(int *n) { if (*n!=0) issues++; *n=1; }
static void napi_schedule(int *n) { if (*n!=1) issues++; }
static void mt76_worker_disable(int *w) { if(!*w)issues++; *w=0; }
static void mt76_worker_enable(int *w) { *w=1; }
static void ieee80211_stop_queues(struct ieee80211_hw *hw) { stopped=1; }
static void ieee80211_wake_queues(struct ieee80211_hw *hw) { wakes++; stopped=0; }
static void ieee80211_restart_hw(struct ieee80211_hw *hw) { restarted++; }
static void mt7996_irq_disable(struct mt7996_dev *d,u32 m) { }
static void mt7996_irq_enable(struct mt7996_dev *d,u32 m) { }
static void mt76_npu_disable_irqs(struct mt76_dev *d) { }
static void cancel_work_sync(struct work_struct *w) { }
static void cancel_delayed_work_sync(struct work_struct *w) { }
static void mt76_abort_scan(struct mt76_dev *d) { scans++; }
static void mt76_abort_roc(struct mt76_phy *p) { rocs++; }
static void mt76_txq_schedule_all(struct mt76_phy *p) { }
static int mt7996_npu_hw_stop(struct mt7996_dev *d) {
    mutex_lock(&d->mt76.mutex); npu_stops++;
    if (!stopped || d->mt76.tx_worker) issues++;
    mutex_unlock(&d->mt76.mutex); return fault==1 ? -110 : 0;
}
static void mt7996_dma_reset(struct mt7996_dev *d,bool force) {
    dma_resets++; if (!npu_stops || fault==1) issues++;
}
static void mt7996_tx_token_put(struct mt7996_dev *d) {
    reclaimed++; if (!npu_stops || fault==1) issues++;
}
static void idr_init(int *p) { }
static int mt7996_mcu_init_firmware(struct mt7996_dev *d) {
    fw_attempts++; return fault==2 ? -110 : 0;
}
static int __mt7996_npu_hw_init(struct mt7996_dev *d) {
    npu_inits++; return fault==3 ? -5 : 0;
}
static void mtk_wed_device_stop(int *w) { }
static void mtk_wed_device_start(int *w,int m) { }
static void mtk_wed_device_start_hw_rro(int *w,int m,bool r) { }
static int mt7996_has_hwrro(struct mt7996_dev *d) { return 1; }
static void mt7996_rro_hw_init(struct mt7996_dev *d) { }
static void mt76_queue_rx_reset(struct mt7996_dev *d,int i) { }
static int mt7996_mcu_set_eeprom(struct mt7996_dev *d) { return fault==4?-5:0; }
static void mt7996_mac_init(struct mt7996_dev *d) { }
static void mt7996_init_txpower(struct mt7996_phy *p) { }
static int mt7996_txbf_init(struct mt7996_dev *d) { return fault==5?-5:0; }
static int mt7996_run(struct mt7996_phy *p) { return fault==6?-5:0; }
static void mt7996_mac_reset_sta_iter(void) { }
static void mt7996_mac_reset_vif_iter(void) { }
static void ieee80211_iterate_stations_atomic(struct ieee80211_hw *h,void (*fn)(void),void *d) { }
static void ieee80211_iterate_active_interfaces_atomic(struct ieee80211_hw *h,int f,void (*fn)(void),void *d) { }
static void mt76_reset_device(struct mt76_dev *d) { }
static int mt76_wcid_alloc(int mask,int n) { return 0; }
static int mt7996_wait_reset_state(struct mt7996_dev *d,int state) {
    if ((fault==7 && state==MT_MCU_CMD_RESET_DONE) ||
        (fault==8 && state==MT_MCU_CMD_RECOVERY_DONE) ||
        (fault==9 && state==MT_MCU_CMD_NORMAL_STATE)) return 0;
    return 1;
}
static void mt7996_dma_start(struct mt7996_dev *d,bool a,bool b) { }
static int is_mt7996(struct mt76_dev *d) { return 1; }
static void mt76_beacon_mon_reset(struct mt76_phy *p) { beacon_grace++; }
static void mt7996_update_beacons(struct mt7996_dev *d) { }
static void ieee80211_queue_delayed_work(struct ieee80211_hw *h,struct work_struct *w,int t) { scheduled++; }
#include "recovery_functions.h"

int run_case(int code, u32 *out) {
    struct mt7996_dev d={0}; struct mt76_phy other[2]={{0}};
    struct ieee80211_hw hw={0}; int i;
    fault=code%10; wed_mode=code>=20; active=&d;
    issues=stopped=wakes=restarted=dma_resets=fw_attempts=0;
    npu_stops=npu_inits=reclaimed=scans=rocs=beacon_grace=scheduled=0;
    d.mt76.hw=&hw; d.mt76.tx_worker=1; d.mt76.tx_napi=1; d.hif2=1;
    d.mt76.phys[0]=&d.mphy; d.mt76.phys[1]=&other[0]; d.mt76.phys[2]=&other[1];
    for(i=0;i<3;i++) {d.phy[i].mt76=d.mt76.phys[i];set_bit(MT76_STATE_RUNNING,&d.mt76.phys[i]->state);}
    for(i=0;i<5;i++) {d.mt76.q_rx[i].ndesc=16; d.mt76.napi[i]=1;}
    d.mt76.q_rx[1].kind=1; d.mt76.napi[1]=-99;
    d.mt76.q_rx[2].kind=2; d.mt76.napi[2]=-99;
    d.recovery.hw_init_done=true; d.recovery.restart=(code/10)%2==0;
    d.recovery.state=d.recovery.restart?MT_MCU_CMD_WA_WDT:MT_MCU_CMD_STOP_DMA;
    mt7996_mac_reset_work(&d.reset_work);
    out[0]=issues;out[1]=stopped;out[2]=wakes;out[3]=restarted;
    out[4]=dma_resets;out[5]=fw_attempts;out[6]=npu_stops;out[7]=npu_inits;
    out[8]=reclaimed;out[9]=d.mt76.mutex;out[10]=d.mt76.tx_worker;
    out[11]=d.recovery.failed;out[12]=test_bit(MT76_MCU_RESET,&d.mphy.state);
    out[13]=scans;out[14]=rocs;out[15]=beacon_grace;
    out[16]=d.mt76.napi[0]==1 && d.mt76.napi[3]==1 && d.mt76.napi[4]==1 && d.mt76.tx_napi==1;
    return 0;
}
