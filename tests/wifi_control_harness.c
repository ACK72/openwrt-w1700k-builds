/* Mock RF/mac80211 boundaries for actual scan and ROC completion functions. */
typedef unsigned int u32;
typedef __SIZE_TYPE__ size_t;
typedef _Bool bool;
#define true 1
#define false 0
#define NULL ((void *)0)
#define HZ 1000
#define MT76_MCU_RESET 0
#define MT76_SCANNING 1
#define IEEE80211_CHAN_NO_IR 1
#define IEEE80211_CHAN_RADAR 2
#define max_t(t,a,b) ((a)>(b)?(a):(b))
#define msecs_to_jiffies(n) (n)
#define container_of(p,t,m) ((t *)((char *)(p)-(size_t)&((t *)0)->m))
#define lockdep_assert_held(p) ((void)0)
#define mutex_lock(p) ((void)0)
#define mutex_unlock(p) ((void)0)
#define spin_lock_bh(p) ((void)0)
#define spin_unlock_bh(p) ((void)0)
#define local_bh_disable() ((void)0)
#define local_bh_enable() ((void)0)
void *memset(void *p,int v,size_t n) { volatile unsigned char *s=p; while(n--) *s++=v; return p; }
struct work_struct { int unused; };
struct delayed_work { struct work_struct work; };
struct ieee80211_channel { int flags; };
struct cfg80211_chan_def { struct ieee80211_channel *chan; };
struct cfg80211_ssid { int unused; };
struct cfg80211_scan_request {
    int n_channels,n_ssids,duration;
    struct ieee80211_channel **channels;
    struct cfg80211_ssid *ssids;
};
struct cfg80211_scan_info { bool aborted; };
struct mt76_dev;
struct mt76_vif_data { void *roc_phy; };
struct mt76_vif_link { struct mt76_vif_data *mvif; };
struct mt76_phy {
    struct mt76_dev *dev;
    unsigned long state;
    int hw,num_sta;
    bool offchannel;
    struct cfg80211_chan_def main_chandef;
    void *chanctx,*roc_vif;
    struct mt76_vif_link *roc_link;
};
struct mt76_dev {
    struct mt76_phy phy;
    int mutex,scan_lock;
    struct delayed_work scan_work;
    struct {
        struct mt76_phy *phy;
        struct cfg80211_scan_request *req;
        struct ieee80211_channel *chan;
        struct mt76_vif_link *mlink;
        void *vif;
        int chan_idx;
        bool beacon_wait,beacon_received;
    } scan;
};
static int fail_channel,rf_calls,scan_done,aborted,roc_done,probes,queued,put_links,notify;
static int test_bit(int bit,unsigned long *v) { return !!(*v & (1ul<<bit)); }
static void clear_bit(int bit,unsigned long *v) { *v &= ~(1ul<<bit); }
static int __mt76_set_channel(struct mt76_phy *p,struct cfg80211_chan_def *c,bool off) {
    rf_calls++; if(fail_channel) return -5; p->offchannel=off; return 0;
}
static int mt76_set_channel(struct mt76_phy *p,struct cfg80211_chan_def *c,bool off) { return __mt76_set_channel(p,c,off); }
static void mt76_offchannel_notify(struct mt76_phy *p,bool off) { notify++; }
static void mt76_put_vif_phy_link(struct mt76_phy *p,void *v,struct mt76_vif_link *l) { put_links++; }
static void ieee80211_scan_completed(int hw,struct cfg80211_scan_info *info) { scan_done++;aborted=info->aborted; }
static void ieee80211_remain_on_channel_expired(int hw) { roc_done++; }
static bool mt76_offchannel_chandef(struct mt76_phy *p,struct ieee80211_channel *c,struct cfg80211_chan_def *d) {d->chan=c;return true;}
static void mt76_scan_send_probe(struct mt76_dev *d,struct cfg80211_ssid *s) { probes++; }
static void ieee80211_queue_delayed_work(int hw,struct delayed_work *w,int duration) { queued++; }
#include "control_functions.h"
int run_case(int code,u32 *out) {
    struct mt76_dev d={0}; struct ieee80211_channel ch={0};
    struct ieee80211_channel *chs[1]={&ch}; struct cfg80211_ssid ssid={0};
    struct cfg80211_scan_request req={1,1,10,chs,&ssid};
    struct mt76_vif_data mvif={0}; struct mt76_vif_link link={&mvif};
    fail_channel=rf_calls=scan_done=aborted=roc_done=probes=queued=put_links=notify=0;
    d.phy.dev=&d; d.phy.main_chandef.chan=&ch;d.phy.offchannel=true;
    d.scan.phy=&d.phy;d.scan.req=&req;d.scan.mlink=&link;d.scan.vif=&d;
    d.phy.state=1ul<<MT76_SCANNING;
    if(code==0 || code==5 || code==6) d.phy.state|=1ul<<MT76_MCU_RESET;
    if(code==2 || code==3 || code==4) fail_channel=1;
    if(code<3) {
        mt76_scan_complete(&d,false); mt76_scan_complete(&d,false);
    } else if(code<6) {
        if(code==4) {d.scan.chan=&ch; d.phy.num_sta=1;}
        mt76_scan_work(&d.scan_work.work);
    } else {
        d.phy.chanctx=&d; d.phy.roc_link=&link;d.phy.roc_vif=&d;mvif.roc_phy=&d.phy;
        if(code==8) d.phy.roc_vif=NULL;
        mt76_roc_complete(&d.phy); mt76_roc_complete(&d.phy);
    }
    out[0]=rf_calls;out[1]=scan_done;out[2]=aborted;out[3]=roc_done;
    out[4]=probes;out[5]=queued;out[6]=put_links;out[7]=d.scan.phy!=NULL;
    return 0;
}
