"""Execute the patched registration and creation path, including procfs names."""
import ctypes
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from test_recovery import ROOT, compile_harness, function, inner_patch, patch_side


class NapiNames(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patch = inner_patch('0018-airoha-name-qdma-napi-threads.patch',
            'target/linux/airoha/patches-6.18/9999-airoha-name-qdma-napi-threads.patch')
        cls.core = patch_side(cls.patch, 'net/core/dev.c')
        cls.header = patch_side(cls.patch, 'include/linux/netdevice.h')
        cls.driver = patch_side(cls.patch, 'drivers/net/ethernet/airoha/airoha_eth.c')
        cls.temp = tempfile.TemporaryDirectory(prefix='w1700k-napi-names-')
        folder = Path(cls.temp.name)
        code = ''.join(function(cls.core, name) for name in (
            'napi_kthread_create', 'netif_napi_add_weight_named_locked', 'netif_napi_add_weight_locked'))
        code += 'static inline void\n' + function(cls.header, 'netif_napi_add_weight_named')
        code += function(cls.driver, 'airoha_qdma_add_napi')
        (folder / 'napi_names_functions.h').write_text(code, newline='\n')
        shutil.copyfile(ROOT / 'tests/napi_names_harness.c', folder / 'test.c')
        cls.lib = compile_harness(folder, 'napi_names')

    @classmethod
    def tearDownClass(cls):
        if os.name == 'nt':
            import _ctypes
            _ctypes.FreeLibrary(cls.lib._handle)
        cls.lib = None
        cls.temp.cleanup()

    def test_declared_exported_api_and_no_late_rename(self):
        self.assertNotIn('set_task_comm(', self.patch)
        self.assertIn('void netif_napi_add_weight_named_locked(', self.header)
        self.assertIn('EXPORT_SYMBOL_GPL(netif_napi_add_weight_named_locked);', self.core)
        self.assertIn('EXPORT_SYMBOL(netif_napi_add_weight_locked);', self.core)

    def test_registration_creation_and_recreation(self):
        for mode in range(77):
            with self.subTest(mode=mode):
                out = (ctypes.c_uint32 * 29)()
                self.lib.run_case(mode, out)
                locks = 2 if mode in (71, 72, 73, 74) else 1
                calls = 2 if mode in (72, 73) else 1
                self.assertEqual(list(out[:4]), [0, locks, locks, calls])
                self.assertEqual(out[4], 64)
                self.assertEqual(out[5], int(mode < 68 and mode % 34 >= 32))
                self.assertEqual(out[6], 1, 'poll callback changed')
                self.assertEqual(out[7], int(mode not in (72, 76)), 'thread failure behavior changed')
                self.assertEqual(out[8], int(mode != 76))
                self.assertEqual(out[9], 1, 'IRQ initialization changed')
                if mode < 68:
                    qdma, ring = divmod(mode, 34)
                    expected = f'napi/qdma{qdma}-' + (f'r{ring}' if ring < 32 else f't{ring - 32}')
                else:
                    expected = {68: 'napi/dummy-7', 69: 'napi/dummy-7',
                        70: '0123456789abcde', 71: 'deferred', 72: 'retry',
                        73: 'recreated', 74: 'original', 75: '%s%d%n', 76: ''}[mode]
                self.assertEqual(bytes(out[10:26]).split(b'\0', 1)[0].decode(), expected)
                self.assertEqual(list(out[26:]), [0, 0, 1])
