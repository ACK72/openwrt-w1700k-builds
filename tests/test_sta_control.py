"""Exercise real diagnostic and polling code with clock/MCU boundary mocks."""
import ctypes
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from test_recovery import ROOT, compile_harness, function, inner_patch, patch_side


class StaControl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        diag = inner_patch('0019-wifi-add-opt-in-sta-control-diagnostics.patch',
            'package/kernel/mt76/patches/9999-zz-sta-control-diagnostics.patch')
        poll = inner_patch('0020-wifi-coalesce-device-wide-sta-polling.patch',
            'package/kernel/mt76/patches/9999-zzz-mt7996-device-sta-poll.patch')
        cls.temp = tempfile.TemporaryDirectory(prefix='w1700k-sta-control-')
        folder = Path(cls.temp.name)
        (folder/'diag_types.h').write_text(patch_side(diag, 'sta_diag.h'), newline='\n')
        source = patch_side(diag, 'sta_diag.c')
        funcs = 'static void\n' + function(source, 'mt76_sta_diag_store')
        for name in ('mt76_sta_diag_event', 'mt76_sta_diag_schedule',
                     'mt76_sta_diag_poll_begin', 'mt76_sta_diag_poll_end',
                     'mt76_sta_diag_set', 'mt76_sta_diag_get'):
            funcs += function(source, name)
        header = patch_side(diag, 'mt76.h')
        (folder/'diag_functions.h').write_text(
            function(header, 'mt76_sta_diag_clock') +
            function(header, 'mt76_sta_diag_us') + funcs, newline='\n')
        source = patch_side(poll, 'mt7996/mac.c')
        (folder/'poll_functions.h').write_text(
            function(source, 'mt7996_mac_sta_poll') +
            function(source, 'mt7996_mac_work'), newline='\n')
        shutil.copyfile(ROOT/'tests/sta_control_harness.c', folder/'test.c')
        cls.lib = compile_harness(folder, 'sta_control')

    @classmethod
    def tearDownClass(cls):
        if os.name == 'nt':
            import _ctypes
            _ctypes.FreeLibrary(cls.lib._handle)
        cls.lib = None
        cls.temp.cleanup()

    def run_mode(self, mode):
        result = (ctypes.c_uint32 * 24)()
        self.lib.run_case(mode, result)
        self.assertEqual(result[0], 0, 'Locking or response ownership invariant')
        return list(result)

    def test_disabled_diagnostics_do_not_read_clock_or_change_state(self):
        r = self.run_mode(0)
        self.assertEqual(r[1:5], [0, 0, 0, 0])

    def test_ring_wrap_preserves_latest_events_and_rejects_invalid_control(self):
        r = self.run_mode(1)
        self.assertEqual(r[1:6], [300, 44, 299, 1, 1])

    def test_disable_freezes_snapshot_and_reenable_starts_new_session(self):
        r = self.run_mode(2)
        self.assertEqual(r[1:7], [1, 1, 0, 0, 0, 1])

    def test_napi_first_schedule_budget_repoll_and_slow_execution(self):
        r = self.run_mode(3)
        self.assertEqual(r[1:8], [2, 1, 3000, 2500, 3, 0, 1])

    def test_short_polls_update_counters_without_flooding_ring(self):
        r = self.run_mode(4)
        self.assertEqual(r[1:6], [1, 0, 100, 200, 0])

    def test_time_conversion_handles_absent_backwards_and_long_spans(self):
        self.assertEqual(self.run_mode(5)[1:5], [0, 0, 1, 0xffffffff])

    def test_three_phys_share_global_queries_but_keep_radio_counters(self):
        r = self.run_mode(10)
        self.assertEqual(r[1:9], [1, 1, 1, 3, 3, 3, 0, 3])

    def test_remaining_phy_takes_over_at_deadline(self):
        r = self.run_mode(11)
        self.assertEqual(r[1:5], [2, 2, 2, 2])

    def test_slow_response_uses_completion_deadline(self):
        r = self.run_mode(12)
        self.assertEqual(r[1:5], [2, 2, 2, 2])

    def test_errors_back_off_and_next_period_retries(self):
        r = self.run_mode(13)
        self.assertEqual(r[1:6], [2, 2, 2, 1, 1])

    def test_wed_global_queries_are_preserved_once_per_period(self):
        r = self.run_mode(14)
        self.assertEqual(r[1:6], [1, 1, 1, 1, 1])

    def test_mcu_reset_skips_work_and_recovery_can_resume(self):
        r = self.run_mode(15)
        self.assertEqual(r[1:7], [0, 0, 0, 1, 1, 1])

    def test_jiffies_wrap_and_zero_deadline_are_valid(self):
        self.assertEqual(self.run_mode(16)[1:4], [2, 2, 2])
        self.assertEqual(self.run_mode(17)[1:4], [2, 2, 2])

    def test_first_error_is_reported_without_rewriting_mcu_semantics(self):
        self.assertEqual(self.run_mode(18)[1:5], [1, 1, 1, 1])
