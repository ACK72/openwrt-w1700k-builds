/* Run the production diagnostic code with scheduling boundary mocks. */
void run_case(int mode, u32 *out)
{
	struct mt76_dev *dev = &device.mt76;
	struct mt76_sta_diag_data *d = &dev->sta_diag.data;
	struct napi_struct *napi = &dev->napi[0];
	u64 start;

	mt76_sta_diag_key.count = mt76_sta_diag_mutex = 0;
	memset(&device, 0, sizeof(device));
	clock_ns = 1000000;
	clock_reads = errors = prep_calls = dispatches = 0;
	poll_on_dispatch = false;
	immediate_start = 0;
	if (mode != 4)
		mt76_sta_diag_set(dev, 1);
	clock_reads = 0;

	switch (mode) {
	case 0: /* Rejected while disabled, then a fresh admission much later. */
	case 6: /* The old code reproduces the inflated wait with the same inputs. */
		napi->state = DISABLED;
		if (mode == 6) legacy_napi_schedule(dev, 0);
		else mt76_napi_schedule(dev, 0);
		clock_ns = 101000000;
		napi->state = 0;
		if (mode == 6) legacy_napi_schedule(dev, 0);
		else mt76_napi_schedule(dev, 0);
		clock_ns += 100000;
		mt76_sta_diag_poll_begin(dev, 0);
		break;
	case 1: /* Rejected duplicate must retain first admission and MISSED. */
		mt76_napi_schedule(dev, 0);
		clock_ns = 2000000;
		mt76_napi_schedule(dev, 0);
		clock_ns = 4000000;
		mt76_sta_diag_poll_begin(dev, 0);
		break;
	case 2: /* Disable cancels an accepted instance before its poll starts. */
		mt76_napi_schedule(dev, 0);
		napi->state = 0; /* Reenabled by the driver after cancellation. */
		clock_ns = 101000000;
		mt76_napi_schedule(dev, 0);
		clock_ns += 100000;
		mt76_sta_diag_poll_begin(dev, 0);
		break;
	case 3: /* Threaded poll may start as soon as dispatch is called. */
		poll_on_dispatch = true;
		mt76_napi_schedule(dev, 0);
		break;
	case 4: /* Recording disabled: normal scheduling, no clock/diag lock. */
		mt76_napi_schedule(dev, 0);
		mt76_napi_schedule(dev, 0);
		break;
	case 5: /* Budget repoll remains measurable without a second IRQ. */
		mt76_napi_schedule(dev, 0);
		start = mt76_sta_diag_poll_begin(dev, 0);
		clock_ns += 100000;
		mt76_sta_diag_poll_end(dev, 0, start, 64, 64);
		clock_ns += 200000;
		mt76_sta_diag_poll_begin(dev, 0);
		break;
	}
	out[0] = errors;
	out[1] = prep_calls;
	out[2] = dispatches;
	out[3] = d->wait_max_us[0];
	out[4] = napi->state;
	out[5] = d->head;
	out[6] = clock_reads;
	out[7] = d->polls[0];
	out[8] = !!immediate_start;
	out[9] = d->budget_hits[0];
	out[10] = !!d->queued_ns[0];
}
