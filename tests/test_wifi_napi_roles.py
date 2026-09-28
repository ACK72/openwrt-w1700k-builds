"""Run actual mt76 named-registration code; kernel lifetime is covered in test_napi_names."""
import ctypes
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from test_recovery import ROOT, compile_harness, function, inner_patch, patch_side


class WifiNapiRoles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inner = inner_patch('0021-wifi-name-napi-by-rx-queue-role.patch',
            'package/kernel/mt76/patches/9999-zzzz-mt76-napi-roles.patch')
        cls.source = patch_side(cls.inner, 'dma.c')
        cls.temp = tempfile.TemporaryDirectory(prefix='w1700k-wifi-napi-')
        folder = Path(cls.temp.name)
        # Independent enum ABI fixture; the driver uses symbolic enum members.
        roles = ['MAIN','MCU','MCU_WA','BAND1','BAND1_WA','MAIN_WA','BAND2','BAND2_WA',
                 'RRO_BAND0','RRO_BAND1','RRO_BAND2','MSDU_PAGE_BAND0','MSDU_PAGE_BAND1',
                 'MSDU_PAGE_BAND2','TXFREE_BAND0','TXFREE_BAND1','TXFREE_BAND2',
                 'RRO_IND','RRO_RXDMAD_C','NPU0','NPU1']
        (folder/'rxq_enum.h').write_text('enum mt76_rxq_id { '+','.join('MT_RXQ_'+r for r in roles)+', __MT_RXQ_MAX };\n')
        (folder/'wifi_napi_functions.h').write_text(
            '#if IS_ENABLED(CONFIG_ARCH_AIROHA)\n'+function(cls.source,'mt76_rx_queue_role')+
            '#endif\n'+function(cls.source,'mt76_rx_napi_add'))
        shutil.copyfile(ROOT/'tests/wifi_napi_harness.c', folder/'test.c')
        cls.lib = compile_harness(folder, 'wifi_napi')
        original=(folder/'test.c').read_text()
        (folder/'test.c').write_text('#define CONFIG_ARCH_AIROHA 0\n'+original)
        cls.other = compile_harness(folder, 'other_platform')
        (folder/'test.c').write_text(original)

    @classmethod
    def tearDownClass(cls):
        if os.name=='nt':
            import _ctypes
            for lib in (cls.lib,cls.other): _ctypes.FreeLibrary(lib._handle)
        cls.lib=cls.other=None
        cls.temp.cleanup()

    def case(self,mode,lib=None):
        out=(ctypes.c_uint32*21)()
        (lib or self.lib).run_case(mode,out)
        return list(out[:5]), bytes(out[5:]).split(b'\0',1)[0].decode()

    def test_all_queue_roles_preserve_callback_weight_and_threaded_mode(self):
        roles=['rx0','wm','wa','rx1','wa1','wa0','rx2','wa2','rro0','rro1','rro2',
               'pg0','pg1','pg2','tf0','tf1','tf2','ind','rxd','npu0','npu1']
        names=[]
        for q,role in enumerate(roles):
            with self.subTest(queue=q):
                stats,name=self.case(q)
                self.assertEqual(stats,[1,1,64,1,1])
                self.assertEqual(name,'napi/phy0-'+role)
                names.append(name)
        self.assertEqual(len(set(names)),21)

    def test_long_phy_name_falls_back_without_ambiguous_truncation(self):
        self.assertEqual(self.case(21),([1,1,64,1,1],'napi/phy10-npu0'))
        self.assertEqual(self.case(22),([1,0,64,1,1],''))

    def test_registration_does_not_enable_threaded_mode(self):
        self.assertEqual(self.case(23)[0],[1,1,64,1,0])

    def test_other_chip_retains_generic_names(self):
        self.assertEqual(self.case(24),([1,0,64,1,1],''))

    def test_non_airoha_registration_has_no_named_api_dependency(self):
        for q in (0,1,16,19,20):
            self.assertEqual(self.case(q,self.other),([1,0,64,1,1],''))

    def test_both_dma_and_npu_registration_use_queue_identity(self):
        dma=function(self.source,'mt76_dma_rx_queue_init')
        npu=function(patch_side(self.inner,'npu.c'),'mt76_npu_rx_queue_init')
        self.assertIn('mt76_rx_napi_add(dev, qid, poll);',dma)
        self.assertIn('mt76_rx_napi_add(dev, qid, mt76_npu_rx_poll);',npu)
        self.assertLess(npu.index('mt76_rx_napi_add'),npu.index('napi_enable'))
        self.assertNotIn('set_task_comm',self.inner)
