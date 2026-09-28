"""Regression coverage for accepted admission versus rejected scheduling attempts."""
import ctypes
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from test_recovery import ROOT, compile_harness, function, inner_patch, patch_side
import test_sta_control as sta_control

SCHEDULING_MOCK = r'''
static inline u64 mt76_sta_diag_poll_begin(struct mt76_dev *dev, int qid);
enum { SCHEDULED = 1, DISABLED = 2, MISSED = 4 };
static u32 prep_calls, dispatches;
static bool poll_on_dispatch;
static u64 immediate_start;
static bool napi_schedule_prep(struct napi_struct *napi)
{
    prep_calls++;
    if (napi->state & DISABLED) return false;
    if (napi->state & SCHEDULED) { napi->state |= MISSED; return false; }
    napi->state |= SCHEDULED;
    return true;
}
static void __napi_schedule(struct napi_struct *napi)
{
    dispatches++;
    if (!(napi->state & SCHEDULED)) errors++;
    if (poll_on_dispatch)
        immediate_start = mt76_sta_diag_poll_begin(&device.mt76, 0);
}
'''

class NapiAdmission(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        patch = inner_patch('0019-wifi-add-opt-in-sta-control-diagnostics.patch',
            'package/kernel/mt76/patches/9999-zz-sta-control-diagnostics.patch')
        cls.temp = tempfile.TemporaryDirectory(prefix='w1700k-napi-admission-')
        folder=Path(cls.temp.name)
        # Share the diagnostic boundary environment; extract real current functions.
        sta_control.StaControl.setUpClass()
        try: shutil.copytree(sta_control.StaControl.temp.name, folder, dirs_exist_ok=True)
        finally: sta_control.StaControl.tearDownClass()
        p=folder/'diag_functions.h';s=p.read_text()
        p.write_text(s+function(patch_side(patch,'mt76.h'),'mt76_napi_schedule')+'''
/* Pre-admission implementation, retained only to reproduce the regression. */
static void legacy_diag_schedule(struct mt76_dev *dev, int qid) {
    struct mt76_sta_diag *diag = &dev->sta_diag;
    unsigned long flags;
    if (!READ_ONCE(diag->enabled)) return;
    spin_lock_irqsave(&diag->lock, flags);
    if (diag->enabled && !diag->data.queued_ns[qid])
        diag->data.queued_ns[qid] = ktime_get_ns();
    spin_unlock_irqrestore(&diag->lock, flags);
}
static void legacy_napi_schedule(struct mt76_dev *dev, int qid) {
    legacy_diag_schedule(dev, qid);
    if (napi_schedule_prep(&dev->napi[qid])) __napi_schedule(&dev->napi[qid]);
}
''')
        p=folder/'test.c';s=p.read_text()
        s=s.replace('struct mt76_dev {','struct napi_struct { unsigned int state; };\nstruct mt76_dev {\n\tstruct napi_struct napi[__MT_RXQ_MAX];')
        s=s.replace('#include "diag_functions.h"',SCHEDULING_MOCK+'\n#include "diag_functions.h"')
        s=s.replace('void run_case(', 'void baseline_case(')
        s+='\n'+(ROOT/'tests/napi_admission_harness.c').read_text()
        p.write_text(s)
        cls.lib=compile_harness(folder,'napi_admission')

    @classmethod
    def tearDownClass(cls):
        if os.name=='nt':
            import _ctypes
            _ctypes.FreeLibrary(cls.lib._handle)
        cls.lib=None;cls.temp.cleanup()

    def case(self, mode):
        result=(ctypes.c_uint32*24)();self.lib.run_case(mode,result)
        self.assertEqual(result[0],0,'Unbalanced diagnostic lock or dispatch without ownership')
        return list(result)

    def test_disabled_request_does_not_inflate_later_admission(self):
        old,new=self.case(6),self.case(0)
        self.assertEqual(old[3],100100)
        self.assertEqual(new[3],100)
        self.assertEqual(old[1:3],new[1:3])
        self.assertEqual(new[1:3],[2,1])

    def test_duplicate_preserves_first_admission_and_missed_bit(self):
        r=self.case(1)
        self.assertEqual(r[1:6],[2,1,3000,5,1])

    def test_fresh_admission_replaces_pre_disable_timestamp(self):
        self.assertEqual(self.case(2)[1:4],[2,2,100])

    def test_timestamp_precedes_immediate_threaded_dispatch(self):
        r=self.case(3)
        self.assertEqual(r[1:4],[1,1,0])
        self.assertEqual([r[7],r[8],r[10]],[1,1,0])

    def test_recording_disabled_keeps_scheduler_semantics_without_clock_reads(self):
        r=self.case(4)
        self.assertEqual(r[1:8],[2,1,0,5,0,0,0])

    def test_budget_repoll_timing_survives_without_new_admission(self):
        r=self.case(5)
        self.assertEqual([r[2],r[3],r[7],r[9],r[10]],[1,200,2,1,0])
