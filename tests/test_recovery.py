"""Run failure injection through actual recovery C functions from the patch.

Mocks cannot validate DMA ordering, PCIe reset or firmware message semantics.
"""
import ctypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

def inner_patch(outer_name, path):
    text = (ROOT/'patches/w1700k'/outer_name).read_text()
    section = text.split('diff --git a/'+path+' b/'+path+'\n',1)[1]
    section = section.split('\ndiff --git ',1)[0]
    return '\n'.join(s[1:] for s in section.splitlines() if s.startswith('+') and not s.startswith('+++ '))+'\n'

def patch_side(text, file, new=True):
    section = text.split('+++ b/'+file+'\n',1)[1]
    section = re.split(r'\n(?:diff --git |--- a/)',section,maxsplit=1)[0]
    return '\n'.join(s[1:] for s in section.splitlines() if s.startswith(' ') or s.startswith('+' if new else '-'))

def function(source,name):
    m=re.search(r'^.*\b'+name+r'\([^;]*?\)\n\{',source,re.M)
    if not m: raise AssertionError('Complete patched function missing: '+name)
    end=source.index('{',m.start())+1; level=1
    while level:
        level+=(source[end]=='{')-(source[end]=='}'); end+=1
    return source[m.start():end]+'\n'

def compile_harness(folder,name):
    if os.name=='nt':
        clang=ROOT.parent/'.validation/llvm18/bin/clang.exe'
        lld=clang.with_name('lld.exe')
        args=[str(clang),'--target=x86_64-pc-windows-msvc','-ffreestanding','-fno-builtin','-O1','-c',str(folder/'test.c'),'-o',str(folder/'test.obj')]
        subprocess.run(args,check=True,capture_output=True)
        lib=folder/(name+'.dll')
        subprocess.run([str(lld),'-flavor','link','/dll','/noentry','/nodefaultlib','/export:run_case','/out:'+str(lib),str(folder/'test.obj')],check=True,capture_output=True)
    else:
        lib=folder/(name+'.so')
        subprocess.run([os.environ.get('CC','cc'),'-shared','-fPIC','-ffreestanding','-fno-builtin','-O1',str(folder/'test.c'),'-o',str(lib)],check=True,capture_output=True)
    result=ctypes.CDLL(str(lib)); result.run_case.argtypes=[ctypes.c_int,ctypes.POINTER(ctypes.c_uint32)]
    return result

class RecoveryLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='w1700k-recovery-')
        cls.folder=Path(cls.temp.name)
        inner=inner_patch('0009-wifi-fix-channel-and-npu-recovery-lifecycle.patch','package/kernel/mt76/patches/9999-y-mt76-recovery-lifecycle.patch')
        source=patch_side(inner,'mt7996/mac.c')
        names=['mt7996_reset_rx_owned','mt7996_reset_disconnect','mt7996_reset_failed','mt7996_mac_restart','mt7996_mac_full_reset','mt7996_mac_reset_work']
        # Return types on a preceding line are explicitly retained here.
        types=['','static void\n','', 'static int\n','static int\n','']
        (cls.folder/'recovery_functions.h').write_text(''.join(t+function(source,n) for n,t in zip(names,types)))
        shutil.copyfile(ROOT/'tests/recovery_harness.c',cls.folder/'test.c')
        try: cls.lib=compile_harness(cls.folder,'recovery')
        except subprocess.CalledProcessError as e: raise RuntimeError(e.stderr.decode(errors='replace')) from e

    @classmethod
    def tearDownClass(cls):
        if os.name=='nt':
            import _ctypes
            _ctypes.FreeLibrary(cls.lib._handle)
        cls.lib=None; cls.temp.cleanup()

    def run_fault(self,code):
        out=(ctypes.c_uint32*18)(); self.lib.run_case(code,out)
        self.assertEqual(out[0],0,'unbalanced NAPI, recursive mutex or unsafe DMA reclamation')
        self.assertEqual(out[9],0,'device mutex leaked')
        self.assertEqual(out[16],1,'NAPI enable/disable not balanced')
        self.assertEqual(out[17],out[11], 'only an associated STA is notified on terminal failure')
        return list(out)

    def test_inaccessible_dma_device_aborts_without_token_release(self):
        for code in (40,50,60,70):
            with self.subTest(code=code):
                r=self.run_fault(code)
                self.assertEqual(r[4],1)
                self.assertEqual(r[5],0)
                self.assertEqual(r[8],0)
                self.assertEqual(r[1:4],[1,0,0])

    def test_full_reset_success_and_each_failure(self):
        for base in (0,20):
            for fault in range(7):
                with self.subTest(wed=bool(base),fault=fault):
                    r=self.run_fault(base+fault)
                    self.assertEqual(r[6],1)
                    self.assertEqual(r[5],0 if fault==1 else 1,'recovery must not repeat ten times')
                    self.assertEqual(r[14],3,'all PHY ROC work must be completed')
                    if fault:
                        self.assertEqual(r[1:4],[1,0,0])
                        self.assertEqual(r[10:13],[0,1,1])
                        if fault==1: self.assertEqual([r[4],r[8]],[0,0])
                    else:
                        self.assertEqual(r[1:4],[0,1,1])
                        self.assertEqual(r[7],1,'NPU must be reinitialized on full reset')

    def test_l1_success_and_each_handshake_failure(self):
        for fault in (0,1,3,7,8,9):
            with self.subTest(fault=fault):
                r=self.run_fault(10+fault)
                if fault:
                    self.assertEqual(r[1:4],[1,0,0])
                    self.assertEqual(r[10:13],[0,1,1])
                    self.assertEqual(r[15],0)
                    if fault in (1,7): self.assertEqual([r[4],r[8]],[0,0])
                else:
                    self.assertEqual(r[1:4],[0,1,0])
                    self.assertEqual(r[15],3)

class ScanRocCompletion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='w1700k-scan-')
        folder=Path(cls.temp.name)
        inner=inner_patch('0009-wifi-fix-channel-and-npu-recovery-lifecycle.patch','package/kernel/mt76/patches/9999-y-mt76-recovery-lifecycle.patch')
        scan=patch_side(inner,'scan.c'); channel=patch_side(inner,'channel.c')
        (folder/'control_functions.h').write_text(function(scan,'mt76_scan_complete')+function(scan,'mt76_scan_work')+function(channel,'mt76_roc_complete'))
        shutil.copyfile(ROOT/'tests/wifi_control_harness.c',folder/'test.c')
        try: cls.lib=compile_harness(folder,'control')
        except subprocess.CalledProcessError as e: raise RuntimeError(e.stderr.decode(errors='replace')) from e

    @classmethod
    def tearDownClass(cls):
        if os.name=='nt':
            import _ctypes
            _ctypes.FreeLibrary(cls.lib._handle)
        cls.lib=None;cls.temp.cleanup()

    def case(self,n):
        out=(ctypes.c_uint32*8)();self.lib.run_case(n,out);return list(out)

    def test_reset_completes_scan_once_without_rf(self):
        self.assertEqual(self.case(0),[0,1,1,0,0,0,1,0])

    def test_success_and_restore_failure(self):
        self.assertEqual(self.case(1)[:3],[1,1,0])
        self.assertEqual(self.case(2)[:3],[1,1,1])

    def test_channel_failure_stops_probing_and_rescheduling(self):
        for n in (3,4,5):
            with self.subTest(case=n):
                r=self.case(n)
                self.assertEqual(r[1:3],[1,1])
                self.assertEqual(r[4:6],[0,0])
                self.assertEqual(r[7],0)
                if n==5:self.assertEqual(r[0],0)

    def test_roc_expired_once_even_during_reset(self):
        self.assertEqual(self.case(6)[0:4],[0,0,0,1])
        self.assertEqual(self.case(7)[0:4],[1,0,0,1])
        self.assertEqual(self.case(8)[3],0)

class ChannelRecoveryHandoff(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='w1700k-channel-');folder=Path(cls.temp.name)
        inner=inner_patch('0009-wifi-fix-channel-and-npu-recovery-lifecycle.patch','package/kernel/mt76/patches/9999-y-mt76-recovery-lifecycle.patch')
        source=patch_side(inner,'mac80211.c')
        (folder/'channel_function.h').write_text(function(source,'__mt76_set_channel'))
        shutil.copyfile(ROOT/'tests/channel_handoff_harness.c',folder/'test.c')
        try: cls.lib=compile_harness(folder,'channel')
        except subprocess.CalledProcessError as e: raise RuntimeError(e.stderr.decode(errors='replace')) from e

    @classmethod
    def tearDownClass(cls):
        if os.name=='nt':
            import _ctypes
            _ctypes.FreeLibrary(cls.lib._handle)
        cls.lib=None;cls.temp.cleanup()

    def test_balanced_park_and_reset_blocks_every_phy(self):
        expected=[
            [0,1,1,0,1,0,1,0,0],
            [5,1,1,0,1,0,1,1,0],
            [5,1,1,0,1,1,1,1,1],
            [5,0,0,0,0,0,1,1,0],
            [5,1,1,0,1,1,1,1,1],
        ]
        for n,row in enumerate(expected):
            with self.subTest(case=n):
                out=(ctypes.c_uint32*9)();self.lib.run_case(n,out)
                self.assertEqual(list(out),row)

class FirmwareEventBounds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='w1700k-events-');folder=Path(cls.temp.name)
        inner=inner_patch('0008-airoha-select-gilly-event-and-ethernet-fixes.patch','package/kernel/mt76/patches/9999-x-mt7996-bound-events.patch')
        source=patch_side(inner,'mt7996/mcu.c')
        (folder/'event_functions.h').write_text('static void\n'+function(source,'mt7996_mcu_rx_all_sta_info_event')+'static void\n'+function(source,'mt7996_mcu_ie_countdown'))
        shutil.copyfile(ROOT/'tests/event_bounds_harness.c',folder/'test.c')
        try: cls.lib=compile_harness(folder,'events')
        except subprocess.CalledProcessError as e: raise RuntimeError(e.stderr.decode(errors='replace')) from e

    @classmethod
    def tearDownClass(cls):
        if os.name=='nt':
            import _ctypes
            _ctypes.FreeLibrary(cls.lib._handle)
        cls.lib=None;cls.temp.cleanup()

    def case(self,n):
        out=(ctypes.c_uint32*2)();self.lib.run_case(n,out);return list(out)

    def test_all_four_station_tags_preserved_and_bounded(self):
        for tag in range(4):
            with self.subTest(tag=tag):
                self.assertEqual(self.case(tag)[0],1)
                for mode in range(1,6): self.assertEqual(self.case(mode*10+tag)[0],0)
        self.assertEqual(self.case(9)[0],0)

    def test_countdown_headers_and_tlv_progress(self):
        for n in range(9):
            with self.subTest(case=n):
                self.assertEqual(self.case(100+n)[1],1 if n in (0,6,8) else 0)

if __name__=='__main__': unittest.main()
