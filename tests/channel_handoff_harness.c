/* Run the patched channel body, checking the worker handoff to recovery. */
typedef unsigned int u32;
typedef __SIZE_TYPE__ size_t;
typedef _Bool bool;
#define true 1
#define false 0
#define EIO 5
#define HZ 100
#define MT76_RESET 0
#define MT76_MCU_RESET 1
#define MT_DFS_STATE_UNKNOWN 0
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define wait_event_timeout(...) 0
struct ieee80211_channel { int center_freq; };
struct cfg80211_chan_def { struct ieee80211_channel *chan; int width; };
struct mt76_channel_state { int dummy; };
struct mt76_dev;
struct mt76_phy {
    struct mt76_dev *dev;
    struct cfg80211_chan_def chandef, main_chandef;
    struct mt76_channel_state *chan_state;
    unsigned long state;
    bool offchannel;
    int dfs_state;
};
struct driver { int (*set_channel)(struct mt76_phy *phy); };
struct mt76_dev { struct mt76_phy phy, *phys[3]; int tx_worker, tx_wait; struct driver *drv; };
static int mode, parks, unparks, errors, calls;
static struct mt76_channel_state new_state;
void *memset(void *p,int v,size_t n) {volatile unsigned char *b=p;while(n--)*b++=v;return p;}
static int test_bit(int n,unsigned long *v) {return !!(*v & (1ul<<n));}
static void set_bit(int n,unsigned long *v) {*v |= 1ul<<n;}
static void clear_bit(int n,unsigned long *v) {*v &= ~(1ul<<n);}
static void mt76_worker_disable(int *w) {if(!*w)errors++;*w=0;parks++;}
static void mt76_worker_enable(int *w) {if(*w)errors++;*w=1;unparks++;}
static void mt76_worker_schedule(int *w) {}
static void mt76_txq_schedule_pending(struct mt76_phy *p) {}
static void mt76_update_survey(struct mt76_phy *p) {}
static struct mt76_channel_state *mt76_channel_state(struct mt76_phy *p,struct ieee80211_channel *c) {return &new_state;}
static int set_channel(struct mt76_phy *p) {
    calls++;
    if(mode==2 || mode==4)set_bit(MT76_MCU_RESET,&p->dev->phy.state);
    return mode==1 || mode==2 ? -5 : 0;
}
#include "channel_function.h"
int run_case(int code,u32 *out) {
    struct ieee80211_channel old={2412},next={2437};
    struct mt76_channel_state old_state={0};
    struct driver drv={set_channel};
    struct mt76_dev d={0};struct mt76_phy others[2]={{0}};
    struct mt76_phy *p=&d.phy;
    struct cfg80211_chan_def target={&next,2};
    int i,ret,all_reset=1;
    mode=code;parks=unparks=errors=calls=0;d.tx_worker=1;d.drv=&drv;
    d.phys[0]=p;d.phys[1]=&others[0];d.phys[2]=&others[1];
    p->dev=&d;p->chandef.chan=p->main_chandef.chan=&old;p->chan_state=&old_state;
    if(code==3)set_bit(MT76_MCU_RESET,&p->state);
    ret=__mt76_set_channel(p,&target,false);
    for(i=0;i<3;i++)if(!test_bit(MT76_RESET,&d.phys[i]->state))all_reset=0;
    out[0]=-ret;out[1]=parks;out[2]=unparks;out[3]=errors;out[4]=calls;
    out[5]=all_reset;out[6]=d.tx_worker;
    out[7]=p->chandef.chan==&old && p->main_chandef.chan==&old && p->chan_state==&old_state;
    out[8]=test_bit(MT76_RESET,&p->state);
    return 0;
}
