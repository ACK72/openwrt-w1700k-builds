"""Check NAPI identity, thread lifetime locking and the module API boundary."""
import ctypes
import os
from pathlib import Path
import tempfile
import unittest

from test_recovery import compile_harness, function, inner_patch, patch_side


class NapiNames(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patch = inner_patch(
            '0018-airoha-name-qdma-napi-threads.patch',
            'target/linux/airoha/patches-6.18/9999-airoha-name-qdma-napi-threads.patch')
        cls.core = patch_side(cls.patch, 'net/core/dev.c')
        cls.driver = patch_side(cls.patch, 'drivers/net/ethernet/airoha/airoha_eth.c')
        cls.temp = tempfile.TemporaryDirectory(prefix='w1700k-napi-names-')
        folder = Path(cls.temp.name)
        harness = r'''
typedef unsigned int u32;
#define TASK_COMM_LEN 16
struct task_struct { char comm[TASK_COMM_LEN]; };
struct net_device { int locked; };
struct napi_struct { struct net_device *dev; struct task_struct *thread; };
struct airoha_eth;
struct airoha_qdma { struct airoha_eth *eth; };
struct airoha_eth { struct airoha_qdma qdma[2]; };
static u32 *output;
static struct net_device *device;
static void netdev_lock(struct net_device *dev) {
    if (dev->locked) output[0]++;
    dev->locked = 1; output[1]++;
}
static void netdev_unlock(struct net_device *dev) {
    if (!dev->locked) output[0]++;
    dev->locked = 0; output[2]++;
}
static int strscpy(char *to, const char *from, unsigned long long size) {
    int i = 0;
    while (i + 1 < size && from[i]) { to[i] = from[i]; i++; }
    to[i] = 0;
    return i;
}
static void set_task_comm(struct task_struct *task, const char *name) {
    if (!device->locked) output[0]++;
    output[3]++;
    strscpy(task->comm, name, TASK_COMM_LEN);
}
static int snprintf(char *to, unsigned long long size, const char *fmt, ...) {
    const char expected[] = "napi/qdma%d-%c%d";
    const char prefix[] = "napi/qdma";
    __builtin_va_list args;
    __builtin_va_start(args, fmt);
    int qdma = __builtin_va_arg(args, int);
    int type = __builtin_va_arg(args, int);
    int id = __builtin_va_arg(args, int);
    __builtin_va_end(args);
    for (int i = 0; i < sizeof(expected); i++)
        if (fmt[i] != expected[i]) output[0]++;
    if (size != TASK_COMM_LEN) output[0]++;
    int n = 0;
    while (prefix[n]) { to[n] = prefix[n]; n++; }
    to[n++] = '0' + qdma; to[n++] = '-'; to[n++] = type;
    if (id >= 10) to[n++] = '0' + id / 10;
    to[n++] = '0' + id % 10; to[n] = 0;
    return n;
}
''' + function(cls.core, 'netif_napi_set_thread_name') + function(cls.driver, 'airoha_qdma_name_napi') + r'''
void run_case(int mode, u32 *out) {
    output = out;
    struct net_device dev = {0}; device = &dev;
    struct task_struct task = {{0}};
    struct napi_struct napi = {&dev, mode == 68 ? 0 : &task};
    struct airoha_eth eth;
    for (int i = 0; i < 2; i++) eth.qdma[i].eth = &eth;
    if (mode < 69) {
        int qdma = mode == 68 ? 0 : mode / 34;
        int ring = mode == 68 ? 0 : mode % 34;
        airoha_qdma_name_napi(&eth.qdma[qdma], &napi,
                            ring < 32 ? 'r' : 't', ring < 32 ? ring : ring - 32);
    } else {
        netif_napi_set_thread_name(&napi, mode == 69 ? "0123456789abcdefghijkl" : "");
    }
    output[4] = dev.locked;
    for (int i = 0; i < TASK_COMM_LEN; i++) output[5 + i] = task.comm[i];
}
'''
        (folder / 'test.c').write_text(harness, newline='\n')
        cls.lib = compile_harness(folder, 'napi_names')

    @classmethod
    def tearDownClass(cls):
        if os.name == 'nt':
            import _ctypes
            _ctypes.FreeLibrary(cls.lib._handle)
        cls.lib = None
        cls.temp.cleanup()

    def test_driver_uses_declared_exported_core_api(self):
        # Linux 6.18 keeps __set_task_comm internal. A C-only driver mock
        # misses this: the wrapper must also be declared and GPL-exported.
        header = patch_side(self.patch, 'include/linux/netdevice.h')
        self.assertNotIn('set_task_comm(', self.driver)
        self.assertIn('netif_napi_set_thread_name(napi, name);', self.driver)
        self.assertIn('void netif_napi_set_thread_name(struct napi_struct *napi, const char *name);', header)
        self.assertIn('EXPORT_SYMBOL_GPL(netif_napi_set_thread_name);', self.core)

    def test_names_missing_thread_and_bounded_copy(self):
        for mode in range(71):
            with self.subTest(mode=mode):
                out = (ctypes.c_uint32 * 21)()
                self.lib.run_case(mode, out)
                self.assertEqual(list(out[:5]), [0, 1, 1, 0 if mode == 68 else 1, 0])
                if mode < 68:
                    qdma, ring = divmod(mode, 34)
                    expected = f'napi/qdma{qdma}-' + (f'r{ring}' if ring < 32 else f't{ring - 32}')
                else:
                    expected = '0123456789abcde' if mode == 69 else ''
                name = bytes(out[5:]).split(b'\0', 1)[0].decode()
                self.assertEqual(name, expected)
                self.assertEqual(out[20], 0)
