import importlib.util,json,os,pathlib,sys,tempfile,unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('build_meta_identity_test',ROOT/'scripts/build-meta.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class BuildIdentity(unittest.TestCase):
    def test_metadata_is_outside_preserved_etc_and_matches_run(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{
                'GH_REPO':'ACK72/openwrt-w1700k-builds','GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'2'}):
            root=pathlib.Path(tmp)
            module.write_build_identity(root,{'builder_commit':'a'*40,'openwrt':'b'*40})
            data=json.loads((root/'files/usr/share/w1700k/build.json').read_text())
            self.assertEqual(data['run_id'],'123')
            self.assertEqual(data['build_attempt'],'2')
            self.assertEqual(data['source'],'b'*40)
            self.assertEqual(data['builder_commit'],'a'*40)
            self.assertFalse((root/'files/etc').exists())
