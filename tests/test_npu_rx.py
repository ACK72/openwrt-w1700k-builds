"""Execute the actual old/new dequeue bodies with mocked ownership/DMA APIs.

This checks lifecycle and bounds, not ARM ordering or firmware/hardware behavior.
The full kernel build and device stress tests remain necessary.
"""
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

def patched_functions():
    outer = (ROOT / 'patches/w1700k/0007-wifi-fix-npu-rx-buffer-ownership.patch').read_text()
    marker = 'diff --git a/package/kernel/mt76/patches/9999-wifi-mt76-fix-npu-rx-buffer-ownership.patch '
    added = outer[outer.index(marker):].splitlines()
    inner = '\n'.join(line[1:] for line in added if line.startswith('+') and not line.startswith('+++'))
    old, new = [], []
    active = False
    for line in inner.splitlines():
        if line.startswith('@@'):
            active = True
        elif active and line.startswith(' '):
            old.append(line[1:]); new.append(line[1:])
        elif active and line.startswith('-'):
            old.append(line[1:])
        elif active and line.startswith('+'):
            new.append(line[1:])
    def extract(lines):
        text = '\n'.join(lines)
        start = text.index('static struct sk_buff *mt76_npu_dequeue(')
        pos = text.index('{', start)
        level = 1
        end = pos + 1
        while level:
            level += (text[end] == '{') - (text[end] == '}')
            end += 1
        return text[start:end] + '\n'
    return extract(old), extract(new)

class NpuRxOwnership(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='w1700k-rx-')
        cls.libs = []
        for label, function in zip(('before', 'after'), patched_functions()):
            folder = Path(cls.temp.name) / label
            folder.mkdir()
            (folder / 'dequeue.h').write_text(function)
            shutil.copyfile(ROOT / 'tests/npu_rx_harness.c', folder / 'test.c')
            if os.name == 'nt':
                clang = ROOT.parent / '.validation/llvm18/bin/clang.exe'
                lld = clang.with_name('lld.exe')
                subprocess.run([str(clang), '--target=x86_64-pc-windows-msvc', '-ffreestanding', '-fno-builtin', '-O1', '-c', str(folder/'test.c'), '-o', str(folder/'test.obj')], check=True, capture_output=True)
                library = folder / 'test.dll'
                subprocess.run([str(lld), '-flavor', 'link', '/dll', '/noentry', '/nodefaultlib', '/export:run_case', '/out:'+str(library), str(folder/'test.obj')], check=True, capture_output=True)
            else:
                library = folder / 'test.so'
                subprocess.run([os.environ.get('CC', 'cc'), '-shared', '-fPIC', '-ffreestanding', '-fno-builtin', '-O1', str(folder/'test.c'), '-o', str(library)], check=True, capture_output=True)
            lib = ctypes.CDLL(str(library))
            lib.run_case.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint32)]
            cls.libs.append(lib)

    @classmethod
    def tearDownClass(cls):
        if os.name == 'nt':
            import _ctypes
            for lib in cls.libs:
                _ctypes.FreeLibrary(lib._handle)
        cls.libs.clear()
        cls.temp.cleanup()

    def case(self, number, before=False):
        output = (ctypes.c_uint32 * 14)()
        self.libs[0 if before else 1].run_case(number, output)
        return list(output)

    def test_original_partial_chain_recycles_ring_owned_pages(self):
        result = self.case(1, before=True)
        self.assertGreater(result[11], 0)
        self.assertGreater(result[5], 0)
        self.assertGreater(result[6], 0)

    def test_fixed_ownership_bounds_and_failures(self):
        for number in range(14):
            with self.subTest(case=number):
                r = self.case(number)
                self.assertEqual(r[5:7], [0, 0], 'double return or DMA after recycle')
                self.assertEqual(r[11], 0, 'incomplete chain changed ownership')
                if number in (6, 7, 9, 10, 13):
                    self.assertEqual(r[:3], [0, 0, 0])
                    self.assertEqual(r[4], 0)
                    self.assertEqual(r[7], 0)
                elif number in (3, 4, 5, 12):
                    count = 2 if number in (3, 12) else 1
                    self.assertEqual(r[:5], [0, 1, count, 4-count, count])
                else:
                    count = 7 if number == 8 else 2 if number in (1, 2, 11) else 1
                    self.assertEqual(r[0:2], [1, 0])
                    self.assertEqual(r[2], 1 if number == 2 else count)
                    self.assertEqual(r[3], 0 if number == 8 else 4-count)
                    self.assertEqual(r[4], count)
                    self.assertEqual(r[7:10], [count, count*128, count-1])

if __name__ == '__main__':
    unittest.main()
