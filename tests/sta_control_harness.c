/* Host boundary mocks: production functions are extracted from the patches. */
typedef unsigned char u8;
typedef unsigned short u16;
typedef signed short s16;
typedef unsigned int u32;
typedef signed int s32;
typedef unsigned long long u64;
typedef _Bool bool;
#define true 1
#define false 0
#define NULL ((void *)0)
#define __MT_RXQ_MAX 8
#define EINVAL 22
#define ECANCELED 125
#define NSEC_PER_USEC 1000
#define U32_MAX 0xffffffffU
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x, v) ((x) = (v))
#define unlikely(x) (x)
#define min_t(t, a, b) ((t)(a) < (t)(b) ? (t)(a) : (t)(b))
#define max(a, b) ((a) > (b) ? (a) : (b))
#define div_u64(a, b) ((a) / (b))
typedef int spinlock_t;
struct mt76_dev;
struct dentry;
#include "diag_types.h"

struct work_struct { int unused; };
struct delayed_work { struct work_struct work; };
struct mt76_phy {
	struct mt76_dev *dev;
	void *priv, *hw;
	u32 state, band_idx, mac_work_count;
	struct delayed_work mac_work;
};
struct mt76_dev {
	struct mt76_sta_diag sta_diag;
	struct mt76_phy phy;
	int mutex;
	struct { int wed; } mmio;
};
struct mt7996_dev {
	struct mt76_dev mt76;
	unsigned long sta_poll_next;
	bool sta_poll_valid;
};
struct mt7996_phy { struct mt7996_dev *dev; struct mt76_phy *mt76; };

static u64 clock_ns;
static u32 clock_reads, errors, calls[5], radio_updates, surveys, beacons, queued;
static int command_error[5];
static unsigned long jiffies, response_ticks;
static struct mt7996_dev device;
static struct mt76_phy radios[3];
static struct mt7996_phy phys[3];

void *memset(void *dst, int value, unsigned long long size)
{
	u8 *p = dst;
	while (size--)
		*p++ = value;
	return dst;
}
static u64 ktime_get_ns(void) { clock_reads++; return clock_ns; }
static void lock(int *p) { if (*p) errors++; *p += 1; }
static void unlock(int *p) { if (*p != 1) errors++; *p -= 1; }
#define spin_lock_irqsave(p, f) do { (f) = 0; lock(p); } while (0)
#define spin_unlock_irqrestore(p, f) do { (void)(f); unlock(p); } while (0)
static void mutex_lock(int *p) { lock(p); }
static void mutex_unlock(int *p) { unlock(p); }
#define lockdep_assert_held(p) do { if (*(p) != 1) errors++; } while (0)
#define EXPORT_SYMBOL_GPL(x)
#include "diag_functions.h"

#define MT7996_WATCHDOG_TIME 10UL
#define MT76_MCU_RESET 1
#define test_bit(n, p) (!!(*(p) & (1U << (n))))
#define time_before(a, b) ((long)((a) - (b)) < 0)
#define container_of(p, t, m) ((t *)((char *)(p) - __builtin_offsetof(t, m)))
enum { UNI_ALL_STA_TXRX_RATE, UNI_ALL_STA_TXRX_AIR_TIME, UNI_PER_STA_RSSI,
	UNI_ALL_STA_TXRX_ADM_STAT, UNI_ALL_STA_TXRX_MSDU_COUNT };
static int mtk_wed_device_active(int *wed) { return *wed; }
static void mt76_update_survey(struct mt76_phy *phy)
{ (void)phy; surveys++; }
static void mt7996_mac_update_stats(struct mt7996_phy *phy)
{ (void)phy; radio_updates++; }
static int mt7996_mcu_get_all_sta_info(struct mt7996_phy *phy, int tag)
{
	lockdep_assert_held(&phy->dev->mt76.mutex);
	calls[tag]++;
	return command_error[tag];
}
static int mt7996_mcu_get_per_sta_info(struct mt7996_phy *phy, int tag)
{
	lockdep_assert_held(&phy->dev->mt76.mutex);
	calls[tag]++;
	jiffies += response_ticks;
	clock_ns += response_ticks * 10000000ULL;
	return command_error[tag];
}
static void mt76_beacon_mon_check(struct mt76_phy *phy)
{ if (phy->dev->mutex) errors++; beacons++; }
static void mt76_tx_status_check(struct mt76_dev *dev, bool flush)
{ (void)dev; (void)flush; }
static void ieee80211_queue_delayed_work(void *hw, struct delayed_work *work,
				       unsigned long delay)
{ (void)hw; (void)work; if (delay != MT7996_WATCHDOG_TIME) errors++; queued++; }
#include "poll_functions.h"

static void work(int band)
{
	radios[band].mac_work_count = 4;
	mt7996_mac_work(&radios[band].mac_work.work);
}

#ifdef _WIN32
__declspec(dllexport)
#endif
void run_case(int mode, u32 *out)
{
	struct mt76_dev *dev = &device.mt76;
	struct mt76_sta_diag_data *d = &dev->sta_diag.data;
	u64 start, before;
	int i;

	memset(&device, 0, sizeof(device));
	memset(radios, 0, sizeof(radios));
	memset(phys, 0, sizeof(phys));
	memset(calls, 0, sizeof(calls));
	memset(command_error, 0, sizeof(command_error));
	memset(out, 0, 24 * sizeof(*out));
	errors = clock_reads = radio_updates = surveys = beacons = queued = 0;
	jiffies = response_ticks = 0;
	clock_ns = 1000000000ULL;
	for (i = 0; i < 3; i++) {
		radios[i].dev = dev;
		radios[i].priv = &phys[i];
		radios[i].band_idx = i;
		phys[i].dev = &device;
		phys[i].mt76 = &radios[i];
	}
	if (mode == 0) {
		start = mt76_sta_diag_clock(dev);
		mt76_sta_diag_event(dev, 1, 2, 0, 1, 2, 3, 4);
		mt76_sta_diag_schedule(dev, 0);
		mt76_sta_diag_poll_end(dev, 0, mt76_sta_diag_poll_begin(dev, 0), 64, 64);
		out[1] = start; out[2] = clock_reads; out[3] = d->head; out[4] = d->polls[0];
	} else if (mode == 1) {
		mt76_sta_diag_set(dev, 1);
		for (i = 0; i < 300; i++)
			mt76_sta_diag_event(dev, 1, 2, 0, i, 0, 0, -i);
		out[1] = d->head; out[2] = d->entries[44].a;
		out[3] = d->entries[43].a;
		out[4] = mt76_sta_diag_set(dev, 2) == -EINVAL;
		mt76_sta_diag_get(dev, &before); out[5] = before;
	} else if (mode == 2) {
		mt76_sta_diag_set(dev, 1);
		start = mt76_sta_diag_poll_begin(dev, 0);
		mt76_sta_diag_event(dev, 1, 2, 0, 0, 0, 0, 0);
		out[1] = d->head;
		mt76_sta_diag_set(dev, 0);
		mt76_sta_diag_event(dev, 1, 2, 0, 0, 0, 0, 0);
		out[2] = d->head;
		clock_ns += 10000000;
		mt76_sta_diag_set(dev, 1);
		mt76_sta_diag_poll_end(dev, 0, start, 64, 64);
		mt76_sta_diag_event(dev, 5, -1, start, 1, 2, 3, -1);
		out[3] = d->head; out[4] = d->polls[0]; out[5] = d->budget_hits[0];
		out[6] = dev->sta_diag.enabled;
	} else if (mode == 3 || mode == 4) {
		mt76_sta_diag_set(dev, 1);
		mt76_sta_diag_schedule(dev, 0);
		clock_ns += mode == 3 ? 1000000 : 100000;
		mt76_sta_diag_schedule(dev, 0); /* preserve first enqueue timestamp */
		if (mode == 3) clock_ns += 2000000;
		start = mt76_sta_diag_poll_begin(dev, 0);
		clock_ns += mode == 3 ? 2500000 : 200000;
		mt76_sta_diag_poll_end(dev, 0, start, mode == 3 ? 64 : 10, 64);
		if (mode == 3) {
			clock_ns += 2100000;
			start = mt76_sta_diag_poll_begin(dev, 0);
			clock_ns += 100000;
			mt76_sta_diag_poll_end(dev, 0, start, 1, 64);
		}
		out[1] = d->polls[0]; out[2] = d->budget_hits[0];
		out[3] = d->wait_max_us[0]; out[4] = d->run_max_us[0];
		out[5] = d->head; out[6] = d->queued_ns[0];
		out[7] = d->entries[0].event == MT76_DIAG_NAPI_WAIT;
	} else if (mode == 5) {
		out[1] = mt76_sta_diag_us(0, 10000);
		out[2] = mt76_sta_diag_us(2000, 1000);
		out[3] = mt76_sta_diag_us(1000, 2000);
		out[4] = mt76_sta_diag_us(1, (u64)U32_MAX * 2000);
	} else if (mode == 10) {
		work(0); work(1); work(2);
		out[4] = radio_updates; out[5] = surveys; out[6] = beacons;
		out[7] = clock_reads; out[8] = queued;
	} else if (mode == 11) {
		work(0); jiffies = 49; work(2);
		out[4] = calls[0];
		jiffies = 50; work(2); work(1); out[4] += calls[0] == 2;
	} else if (mode == 12) {
		response_ticks = 100; work(0);
		jiffies = 149; work(1); out[4] = calls[0];
		jiffies = 150; work(2); out[4] += calls[0] == 2;
	} else if (mode == 13 || mode == 18) {
		mt76_sta_diag_set(dev, 1);
		command_error[2] = -5;
		if (mode == 18) command_error[0] = -12;
		work(0); work(1); work(2);
		for (i = 0; i < (int)d->head; i++)
			if (d->entries[i].event == MT76_DIAG_STA_POLL)
				out[4] = d->entries[i].result == (mode == 18 ? -12 : -5);
		if (mode == 13) {
			jiffies = 50; command_error[2] = 0; work(2);
			out[5] = calls[0] == 2;
		}
	} else if (mode == 14) {
		dev->mmio.wed = 1; work(0); work(1); work(2);
		out[4] = calls[3]; out[5] = calls[4];
	} else if (mode == 15) {
		dev->phy.state = 1U << MT76_MCU_RESET;
		work(0); work(1); work(2);
		out[1] = calls[0]; out[2] = beacons; out[3] = queued;
		dev->phy.state = 0; work(2);
		out[4] = calls[0]; out[5] = beacons; out[6] = queued;
	} else if (mode == 16 || mode == 17) {
		jiffies = mode == 16 ? ~0UL - 24 : ~0UL - 49;
		work(0); work(1);
		jiffies = mode == 16 ? 24 : ~0UL; work(2);
		jiffies = mode == 16 ? 25 : 0; work(2);
	}
	if (mode >= 10 && mode != 15) {
		out[1] = calls[0]; out[2] = calls[1]; out[3] = calls[2];
	}
	out[0] = errors + !!dev->mutex + !!dev->sta_diag.lock;
}
