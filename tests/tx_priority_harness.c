/* Execute the patched worker and schedule_all with a congested shared ring.
 * Hardware completion and mac80211's data scheduler are boundary mocks.
 * This verifies ordering, not RF reception or an actual disconnect cause.
 */
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define MT_TXQ_BK 3
struct mt76_dev;
struct mt76_phy {
	struct mt76_dev *dev;
	int hw, id, pending, sent;
};
struct mt76_dev {
	struct mt76_phy phy;
	struct mt76_phy *phys[3];
};
static int slots[3], shared, data_frames;
static void mt76_txq_schedule_pending(struct mt76_phy *phy)
{
	int ring = shared && phy->id ? 1 : phy->id;
	while (phy->pending && slots[ring]) {
		phy->pending--;
		phy->sent++;
		slots[ring]--;
	}
}
static void mt76_txq_schedule(struct mt76_phy *phy, int qid)
{
	/* The device-wide scheduler has a backlogged 5 GHz data TXQ. */
	data_frames += slots[1];
	slots[1] = 0;
}
#include "priority_functions.h"
int run_case(int mode, unsigned *out)
{
	struct mt76_dev dev = {0};
	struct mt76_phy p1 = {&dev, 0, 1, 0, 0};
	struct mt76_phy p2 = {&dev, 0, 2, 1, 0};
	int i;
	dev.phy.dev = &dev;
	dev.phys[0] = &dev.phy;
	dev.phys[1] = &p1;
	dev.phys[2] = &p2;
	shared = mode != 1;
	data_frames = 0;
	if (mode == 2)
		dev.phys[1] = 0;
	if (mode == 3) {
		dev.phys[2] = 0;
		dev.phy.pending = 1;
	}
	if (mode == 4)
		p2.pending = 0;
	for (i = 0; i < 10; i++) {
		/* Eight descriptors become free at each simulated completion. */
		slots[0] = slots[1] = slots[2] = mode == 5 ? 0 : 8;
		mt76_tx_worker_run(&dev);
	}
	out[0] = p2.sent;
	out[1] = data_frames;
	out[2] = dev.phy.sent;
	return 0;
}
