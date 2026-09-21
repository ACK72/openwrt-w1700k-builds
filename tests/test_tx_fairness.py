"""Execute real pending-list, regular burst and worker code with boundary mocks."""
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_recovery import ROOT, compile_harness, function, inner_patch, patch_side


class PendingFrameFairness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temps, cls.libs = [], []
        inner = inner_patch('0010-wifi-service-pending-frames-before-data.patch',
                            'package/kernel/mt76/patches/9999-z-mt76-pending-before-data.patch')
        for new in (False, True):
            source = patch_side(inner, 'tx.c', new=new)
            temp = tempfile.TemporaryDirectory(prefix='w1700k-tx-fairness-')
            cls.temps.append(temp)
            folder = Path(temp.name)
            (folder / 'burst_functions.h').write_text(
                'static bool\n' + function(source, 'mt76_txq_stopped') +
                'static int\n' + function(source, 'mt76_txq_send_burst'))
            names = ['mt76_txq_schedule_pending_wcid']
            if new:
                names.append('__mt76_txq_schedule_pending')
            names += ['mt76_txq_schedule_pending', 'mt76_txq_schedule_all']
            if new:
                names.append('mt76_txq_schedule_shared')
            names.append('mt76_tx_worker_run')
            prefixes = {'mt76_txq_schedule_pending_wcid': 'static int\n',
                        '__mt76_txq_schedule_pending': 'static void\n',
                        'mt76_txq_schedule_shared': 'static void\n'}
            (folder / 'priority_functions.h').write_text(
                ''.join(prefixes.get(n, '') + function(source, n) for n in names))
            shutil.copyfile(ROOT / 'tests/tx_fairness_harness.c', folder / 'test.c')
            try:
                cls.libs.append(compile_harness(folder, 'priority'))
            except subprocess.CalledProcessError as e:
                raise RuntimeError(e.stderr.decode(errors='replace')) from e

    @classmethod
    def tearDownClass(cls):
        if os.name == 'nt':
            import _ctypes
            for lib in cls.libs:
                _ctypes.FreeLibrary(lib._handle)
        cls.libs.clear()
        for temp in cls.temps:
            temp.cleanup()

    def run_case(self, mode, new=True):
        out = (ctypes.c_uint32 * 19)()
        self.libs[int(new)].run_case(mode, out)
        r = list(out)
        self.assertEqual(r[9:11], [0, 0], 'FIFO order or WCID list corruption')
        self.assertEqual(r[18], 0, 'Unbalanced/reentrant locking, BH or RCU')
        if new and mode not in (18, 19, 27):
            self.assertLessEqual(r[12], 32, 'Pending budget exceeded across pre/post phases')
        return r

    def test_single_probe_gets_slot_without_reducing_total_work(self):
        old, new = self.run_case(0, False), self.run_case(0)
        self.assertEqual(old[1:3] + old[5:6], [80, 0, 0])
        self.assertEqual([new[1], new[5]], [79, 1])

    def test_payload_backlogs_preserve_regular_and_secondary_progress(self):
        for mode in (1, 2, 3):
            with self.subTest(mode=mode):
                r = self.run_case(mode)
                self.assertEqual(r[1] + r[4] + r[5], 80, 'Available ring space must be used')
                self.assertGreaterEqual(r[1], 40)
                self.assertGreater(r[5], 0)
                if mode != 2:
                    self.assertGreater(r[4], 0)
        self.assertEqual(self.run_case(1)[5], 1)

    def test_one_slot_and_empty_wakeups_do_not_bias_phy_or_data(self):
        for mode in (10, 11, 12):
            with self.subTest(mode=mode):
                r = self.run_case(mode)
                self.assertEqual(r[1], 9)
                self.assertEqual(r[4] + r[5], 9)
                self.assertGreaterEqual(min(r[4], r[5]), 4)
        self.assertEqual(self.run_case(12)[0], 54 * 8, 'Independent ring remains unconstrained')

    def test_no_regular_data_does_not_strand_reserved_capacity(self):
        for mode in (13, 24, 25):
            with self.subTest(mode=mode):
                r = self.run_case(mode)
                self.assertEqual(r[1], 0)
                self.assertEqual(r[4] + r[5], 80)

    def test_budget_yields_then_reschedules_without_lost_wakeup(self):
        for mode in (8, 23):
            with self.subTest(mode=mode):
                r = self.run_case(mode)
                self.assertEqual(r[5], 400)
                self.assertEqual(r[13], 13)
                self.assertEqual(r[7], 12)
                self.assertEqual(r[12], 32)

    def test_wcid_rotation_and_frame_fifo(self):
        r = self.run_case(14)
        self.assertEqual(r[1] + r[4], 80)
        self.assertGreater(min(r[14], r[15]), 0)
        self.assertEqual(self.run_case(15)[5], 61)

    def test_reset_offchannel_and_blocked_queues(self):
        for mode in (4, 5, 7, 20, 21):
            with self.subTest(mode=mode):
                r = self.run_case(mode)
                self.assertEqual(sum(r[3:6]), 0)
                self.assertEqual(r[7], 0, 'Do not self-poll stalled/reset/offchannel queues')
        r = self.run_case(6)
        self.assertEqual([r[1], r[5]], [79, 1])

    def test_missing_phys_and_concurrent_enqueue_do_not_corrupt_lists(self):
        self.assertEqual(self.run_case(16)[5], 1)
        self.assertEqual(self.run_case(17)[3], 1)
        r = self.run_case(22)
        self.assertEqual(r[16:18], [2, 1])

    def test_separate_hw_and_single_phy_preserve_legacy_behavior(self):
        for mode in (18, 19):
            with self.subTest(mode=mode):
                self.assertEqual(self.run_case(mode), self.run_case(mode, False))

    def test_regular_burst_clears_admission_credit(self):
        r = self.run_case(26)
        self.assertEqual([r[1], r[5]], [2, 1])

    def test_exported_drain_for_channel_and_reset_callers_is_unchanged(self):
        old, new = self.run_case(27, False), self.run_case(27)
        self.assertEqual(old, new)
        self.assertEqual(new[5], 400)
        self.assertEqual(new[7], 0)

    def test_empty_pending_path_keeps_full_capacity_and_avoids_duplicate_data_pass(self):
        old, new = self.run_case(9, False), self.run_case(9)
        self.assertEqual(new[1], old[1])
        self.assertEqual(new[1], 80)
        self.assertEqual([old[8], new[8]], [80, 40])
