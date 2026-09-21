"""Overlapping monitor patches must be repeatable without partial updates."""
import difflib,importlib.util,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from customize import apply_patch_series

class MonitorPatchSeries(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.tree=self.root/'tree';self.tree.mkdir()
        self.initial='line 1\nold backend\nline 3\n'
        self.middle='line 1\nucode backend\nline 3\n'
        self.final='line 1\nshared collector\nline 3\n'
        self.path=self.tree/'package/backend';self.path.parent.mkdir();self.path.write_text(self.initial)
        self.patches=[]
        for i,(before,after) in enumerate([(self.initial,self.middle),(self.middle,self.final)]):
            path=self.root/f'{i}.patch'
            path.write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/package/backend',tofile='b/package/backend')),newline='\n')
            self.patches.append(path)

    def test_apply_and_repeat_overlapping_changes(self):
        apply_patch_series(self.tree,self.patches);self.assertEqual(self.path.read_text(),self.final)
        apply_patch_series(self.tree,self.patches);self.assertEqual(self.path.read_text(),self.final)

    def test_upgrade_existing_partial_series(self):
        apply_patch_series(self.tree,self.patches[:1]);apply_patch_series(self.tree,self.patches)
        self.assertEqual(self.path.read_text(),self.final)

    def test_failed_series_leaves_original_untouched(self):
        self.patches[1].write_text(self.patches[1].read_text().replace('-ucode backend','-unexpected backend'),newline='\n')
        with self.assertRaises(RuntimeError):apply_patch_series(self.tree,self.patches)
        self.assertEqual(self.path.read_text(),self.initial)
