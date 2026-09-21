"""Run the real shell sampler with bounded mock probes and route changes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT/'package/w1700k-custom/root/usr/libexec/npu-jitter-daemon').read_text()


class Window(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.shell = shutil.which('sh') or 'C:/Program Files/Git/bin/sh.exe'

    def tearDown(self):
        self.temp.cleanup()

    def run_sampler(self, count, start=1000, target='1.1.1.1'):
        prefix = r'''
test_count=0
date() { echo "$((TEST_START + test_count * 5))"; }
timeout() { shift; "$@"; }
# Exercise the old failure mode: temporary missing route, then new WAN.
ip() {
    if [ "$test_count" -lt 4 ]; then echo '1.1.1.1 via 1.2.3.4 dev wan uid 0';
    elif [ "$test_count" -lt 7 ]; then return 1;
    else echo '1.1.1.1 via 10.0.0.1 dev wlan uid 0'; fi
}
ping() {
    [ "$test_count" != 5 ] || return 1
    echo 'round-trip min/avg/max = 10.000/10.000/10.000 ms'
}
sleep() {
    cat result.json >> history.jsonl
    test_count=$((test_count + 1))
    [ "$test_count" -lt "$TEST_COUNT" ] || exit 0
}
'''
        source = SOURCE.replace('RESULT=/tmp/npu-jitter.json', 'RESULT=result.json')
        source = source.replace('STATE=/tmp/npu-jitter.window', 'STATE=window')
        (self.directory/'sampler.sh').write_text(prefix + source, newline='\n')
        history = self.directory/'history.jsonl'
        history.unlink(missing_ok=True)
        env = {**os.environ, 'TEST_COUNT': str(count), 'TEST_START': str(start)}
        if os.name == 'nt':
            env['PATH'] = 'C:/Program Files/Git/usr/bin;' + env['PATH']
        subprocess.run([self.shell, 'sampler.sh', target], cwd=self.directory,
                       env=env, check=True, capture_output=True)
        return [json.loads(line) for line in history.read_text().splitlines()]

    def test_route_loss_and_failover_keep_twelve_attempts(self):
        rows = self.run_sampler(15)
        self.assertEqual([r['attempts'] for r in rows], list(range(1, 13)) + [12]*3)
        self.assertEqual(rows[-1]['samples'], 11)
        self.assertEqual(rows[-1]['avg_ping'], 10)

    def test_prompt_service_restart_keeps_recent_window(self):
        self.run_sampler(12)
        self.assertEqual(self.run_sampler(1, start=1060)[0]['attempts'], 12)

    def test_changed_target_stale_and_invalid_state_start_fresh(self):
        self.run_sampler(12)
        self.assertEqual(self.run_sampler(1, start=1200)[0]['attempts'], 1)
        self.assertEqual(self.run_sampler(1, start=1205, target='8.8.8.8')[0]['attempts'], 1)
        (self.directory/'window').write_text('1.1.1.1\n1210\n10 garbage\n')
        self.assertEqual(self.run_sampler(1, start=1210)[0]['attempts'], 1)


if __name__ == '__main__':
    unittest.main()
