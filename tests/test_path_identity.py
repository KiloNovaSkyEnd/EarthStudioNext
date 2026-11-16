import os
from pathlib import Path
import unittest,uuid
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from ges_next.path_identity import canonical,normal_namespace
from ges_next.production.owned_files import owned_path
from ges_next.isolation import require_writable


class PathIdentityTests(unittest.TestCase):
    def test_drive_unc_and_device_namespaces(self):
        self.assertEqual(normal_namespace(r'\\?\D:\folder\file'),r'D:\folder\file')
        self.assertEqual(normal_namespace(r'\\?\UNC\server\share\file'),r'\\server\share\file')
        for value in [r'\\.\PhysicalDrive0',r'\\?\Volume{abcd}\file']:
            self.assertEqual(normal_namespace(value),value)

    @unittest.skipUnless(os.name=='nt','Windows namespace alias')
    def test_extended_path_alias_keeps_containment_and_protection(self):
        root=(Path('reports/path_identity')/uuid.uuid4().hex).absolute();root.mkdir(parents=True)
        real=Path.resolve
        def extended(path,*args,**kwargs):
            return Path('\\\\?\\'+normal_namespace(real(path,*args,**kwargs)))
        with patch.object(Path,'resolve',extended):
            inside=root/'job/raw/scan/input.bz2'
            self.assertEqual(owned_path(root/'job',inside,'l1'),inside)
            self.assertEqual(require_writable(inside,workspace=root,protected=[],user_data=root/'user'),inside)
            with self.assertRaises(ValueError):owned_path(root/'job',root/'outside/file.bz2','l1')
            with self.assertRaises(ValueError):require_writable(root/'protected/file',workspace=root,protected=[root/'protected'],user_data=root/'user')

    def test_parallel_new_parent_paths(self):
        root=canonical(Path('reports/path_identity')/uuid.uuid4().hex);root.mkdir(parents=True)
        def one(i):
            job=root/str(i//4);path=job/'raw/scan'/f'input_{i}.bz2'
            owned_path(job,path,'l1');path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(b'tiny owned regression fixture')
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(one,range(400)))


if __name__=='__main__':unittest.main()
