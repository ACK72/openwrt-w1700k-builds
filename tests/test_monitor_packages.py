"""Regression coverage for source pinning, CPU availability and backup recovery."""
import importlib.util,json,pathlib,subprocess,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]

class MonitorPackages(unittest.TestCase):
    def test_sources_are_immutable_and_nft_native(self):
        lock=json.loads((ROOT/'configs/extra-packages.json').read_text())
        self.assertEqual({r['repo'] for r in lock},{'dl12345/mwan3','dl12345/luci-app-mwan3'})
        for row in lock:
            self.assertRegex(row['commit'],r'^[a-f0-9]{40}$')
            self.assertRegex(row['sha256'],r'^[a-f0-9]{64}$')
            self.assertTrue(row['url'].endswith('/'+row['commit']))

    def test_cpu_ui_missing_is_not_idle(self):
        subprocess.run(['node',str(ROOT/'tests/cpu_display.cjs')],check=True)

    def test_restore_hook_respects_explicit_disable(self):
        # Exercise the actual boot function with stubbed service and UCI commands.
        import shutil
        shell=shutil.which('bash') or 'C:/Program Files/Git/bin/bash.exe'
        text=(ROOT/'package/w1700k-custom/root/etc/init.d/w1700k-monitor').read_text()
        text=text.replace('/etc/init.d/npu-jitter','sampler')
        for value,expected in [('0',''),('1','enable\nstart\n'),('','enable\nstart\n')]:
            script='uci() { printf "%s" "$SETTING"; }; sampler() { echo "$1"; };\n'+text+'\nboot\n'
            import os
            env={**os.environ,'SETTING':value}
            r=subprocess.run([shell,'-c',script],capture_output=True,text=True,env=env,check=True)
            self.assertEqual(r.stdout,expected)
