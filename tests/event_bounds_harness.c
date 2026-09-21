/* Exercise the actual event parsers with bounded buffers and malformed lengths. */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef __SIZE_TYPE__ size_t;
#define __packed __attribute__((packed))
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define le16_to_cpu(x) (x)
#define le32_to_cpu(x) (x)
#define IEEE80211_NUM_ACS 4
#define IEEE80211_AC_BE 0
#define IEEE80211_AC_BK 1
#define IEEE80211_AC_VI 2
#define IEEE80211_AC_VO 3
#define IEEE80211_IFACE_ITER_RESUME_ALL 0
#define UNI_ALL_STA_TXRX_RATE 0
#define UNI_ALL_STA_TXRX_ADM_STAT 1
#define UNI_ALL_STA_TXRX_MSDU_COUNT 2
#define UNI_ALL_STA_TXRX_AIR_TIME 3
#define dev_err(...) ((void)0)
void *memset(void *p,int v,size_t n) { volatile unsigned char *s=p;while(n--) *s++=v;return p; }
struct sk_buff { unsigned char *data; unsigned int len; };
struct mt7996_mcu_rxd { u8 bytes[32]; };
struct all_sta_trx_rate { u16 wlan_idx;u8 reserved[14]; } __packed;
struct mt7996_mcu_all_sta_info_event {
    u8 rsv[4];u16 tag,len;u8 more,rsv2;u16 sta_num;u8 rsv3[4];
    union {
        struct all_sta_trx_rate rate[0];
        struct {u16 wlan_idx;u8 rsv[2];u32 tx_bytes[4],rx_bytes[4];} __packed adm_stat[0];
        struct {u16 wlan_idx;u8 rsv[2];u32 tx_msdu_cnt,rx_msdu_cnt;} __packed msdu_cnt[0];
        struct {u16 wlan_idx;u8 rsv[2];u32 tx[4],rx[4];} __packed airtime[0];
    } __packed;
} __packed;
struct mt76_phy { int x; };
struct mt7996_dev { struct {struct mt76_phy *phys[3]; int dev;} mt76; };
struct mt76_wcid { int rate;struct {u32 tx_bytes,rx_bytes,tx_packets,rx_packets;} stats; };
struct ieee80211_sta { int x; };
struct tlv {u16 tag,len;u8 data[0];} __packed;
struct mt7996_mcu_countdown_notify {u8 omac_idx,count,csa_failure_reason,rsv;} __packed;
struct mt7996_mcu_countdown_data {struct mt76_phy *mphy;u8 omac_idx;};
static int looked_up, callback;
static struct mt76_wcid wcid;
static struct ieee80211_sta sta;
static void *skb_pull(struct sk_buff *s,size_t n) {if(s->len<n)return 0;s->len-=n;return s->data+=n;}
static struct mt76_wcid *mt76_wcid_ptr(struct mt7996_dev *d,u16 idx) {looked_up++;return &wcid;}
static int mt7996_mcu_update_tx_gi(int *r,struct all_sta_trx_rate *a) {return 0;}
static struct ieee80211_sta *wcid_to_sta(struct mt76_wcid *w) {return &sta;}
static u8 mt76_connac_lmac_mapping(u8 ac) {return ac;}
static void ieee80211_sta_register_airtime(struct ieee80211_sta *s,u8 tid,u32 tx,u32 rx) { }
static void mt7996_mcu_csa_finish(void) { }
static void mt7996_mcu_cca_finish(void) { }
static void *mt76_hw(struct mt7996_dev *d) {return d;}
static void ieee80211_iterate_active_interfaces_atomic(void *hw,int f,void (*fn)(void),void *data) {callback++;}
#include "event_functions.h"
int run_case(int code,u32 *out) {
    unsigned char data[256]={0};struct sk_buff skb={data,sizeof(data)};
    struct mt7996_dev d={0};struct mt76_phy phy={0};
    unsigned int head=sizeof(struct mt7996_mcu_rxd),elem;
    struct mt7996_mcu_all_sta_info_event *r=(void *)(data+head);
    int tag=code%10, mode=code/10;
    looked_up=callback=0;d.mt76.phys[0]=&phy;
    if(code<100) {
        r->tag=tag;r->sta_num=1;
        elem=tag==0?sizeof(r->rate[0]):tag==1?sizeof(r->adm_stat[0]):tag==2?sizeof(r->msdu_cnt[0]):sizeof(r->airtime[0]);
        skb.len=head+sizeof(*r)+elem;
        if(mode==1)skb.len=head-1;
        if(mode==2)skb.len=head+sizeof(*r)-1;
        if(mode==3)skb.len--;
        if(mode==4)r->sta_num=65535;
        if(mode==5)r->sta_num=0;
        mt7996_mcu_rx_all_sta_info_event(&d,&skb);
    } else {
        struct tlv *t=(void *)(data+head+4);
        int n=code-100;
        t->tag=0;t->len=8;skb.len=head+4+8;
        if(n==1)skb.len=head+3;
        if(n==2)t->len=0;
        if(n==3)t->len=3;
        if(n==4)t->len=9;
        if(n==5)t->len=4;
        if(n==6){t->tag=99;t->len=4;t=(void *)((char *)t+4);t->tag=1;t->len=8;skb.len+=4;}
        if(n==7){data[head]=3;}
        if(n==8){t->tag=1;}
        mt7996_mcu_ie_countdown(&d,&skb);
    }
    out[0]=looked_up;out[1]=callback;
    return 0;
}
