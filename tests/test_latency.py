"""Exercise the sampler's actual averaging program, including missed probes."""
import json,pathlib,shutil,subprocess,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
SOURCE=(ROOT/'package/w1700k-custom/root/usr/libexec/npu-jitter-daemon').read_text()
AWK=SOURCE.split('-v cur="$cpu_now" \'\n',1)[1].split("' > \"$RESULT.tmp\"",1)[0]

class Latency(unittest.TestCase):
    def calculate(self, values):
        awk=shutil.which('awk')
        fallback=pathlib.Path('C:/Program Files/Git/usr/bin/awk.exe')
        if not awk and fallback.is_file():awk=str(fallback)
        if not awk:self.skipTest('awk is required')
        result=subprocess.run([awk,'-v','target=1.1.1.1','-v','now=100','-v','interval=5','-v','prev=','-v','cur=',AWK],
                              input=values+'\n',text=True,capture_output=True,check=True)
        return json.loads(result.stdout)
    def test_mean_and_last_are_distinct(self):
        row=self.calculate('1 2 9')
        self.assertEqual(row['avg_ping'],4)
        self.assertEqual(row['last_ping'],9)
        self.assertEqual(row['samples'],3)
    def test_failed_probe_counts_as_loss_not_zero_latency(self):
        row=self.calculate('10 - 20 -')
        self.assertEqual(row['avg_ping'],15)
        self.assertEqual(row['loss_percent'],50)
        self.assertEqual(row['attempts'],4)
        self.assertFalse(row['reachable'])
        self.assertIsNone(row['last_ping'])
    def test_all_failed_probes_are_unavailable_not_fast(self):
        row=self.calculate('- - -')
        self.assertIsNone(row['avg_ping'])
        self.assertEqual(row['samples'],0)
        self.assertEqual(row['loss_percent'],100)
    def test_zero_rtt_is_valid(self):
        row=self.calculate('0.000')
        self.assertEqual(row['avg_ping'],0)
        self.assertTrue(row['reachable'])
    def test_display_staleness(self):
        subprocess.run(['node',str(ROOT/'tests/latency_display.cjs')],check=True)
