import ctypes
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from test_recovery import ROOT, compile_harness, function, inner_patch, patch_side


class ControlFramePriority(unittest.TestCase):
    def test_congested_shared_ring_and_uncongested_controls(self):
        inner = inner_patch(
            '0010-wifi-service-pending-frames-before-data.patch',
            'package/kernel/mt76/patches/9999-z-mt76-pending-before-data.patch')
        for new in (False, True):
            source = patch_side(inner, 'tx.c', new=new)
            with tempfile.TemporaryDirectory(prefix='w1700k-tx-priority-') as tmp:
                folder = Path(tmp)
                (folder/'priority_functions.h').write_text(
                    function(source, 'mt76_txq_schedule_all') +
                    function(source, 'mt76_tx_worker_run'))
                shutil.copyfile(ROOT/'tests/tx_priority_harness.c', folder/'test.c')
                lib = compile_harness(folder, 'priority')
                try:
                    for mode in range(6):
                        with self.subTest(patched=new, mode=mode):
                            out = (ctypes.c_uint32*3)()
                            lib.run_case(mode, out)
                            expected_sent = int(mode == 1 or (new and mode in (0, 2)))
                            self.assertEqual(out[0], expected_sent)
                            self.assertEqual(out[2], int(mode == 3))
                            expected_data = 0 if mode == 5 else 80 - int(new and mode in (0, 2))
                            self.assertEqual(out[1], expected_data,
                                             'Use all slots not consumed by control frames')
                finally:
                    if os.name == 'nt':
                        import _ctypes
                        _ctypes.FreeLibrary(lib._handle)
                    lib = None
