from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from ges_next.h9_parallel import admitted_rows,row_command,run_rows,dispatch_rows,GIB

class H9ParallelTests(unittest.TestCase):
    def test_low_memory_reuses_single_scene_without_starting_four_children(self):
        args=SimpleNamespace(row=None,assemble_only=False)
        with patch('ges_next.h9_parallel.run_rows') as launch:
            self.assertFalse(dispatch_rows(args,Path('prepare.py'),1))
            launch.assert_not_called()
            self.assertFalse(args.assemble_only)
            self.assertTrue(dispatch_rows(args,Path('prepare.py'),2))
            launch.assert_called_once_with(args,Path('prepare.py'),2)
        for invalid in [0,3,True,1.0]:
            with self.assertRaises(ValueError):dispatch_rows(args,Path('prepare.py'),invalid)
    def test_memory_and_commit_bound_process_admission(self):
        self.assertEqual(admitted_rows(2,14*GIB,12*GIB),2)
        self.assertEqual(admitted_rows(2,10*GIB,12*GIB),1)
        self.assertEqual(admitted_rows(2,14*GIB,7*GIB),1)
        self.assertEqual(admitted_rows(2,3*GIB,GIB),1)
        for invalid in [0,3,True,1.5]:
            with self.assertRaises(ValueError):admitted_rows(invalid,30*GIB,30*GIB)
    def test_children_keep_exact_time_and_scope_and_disjoint_rows(self):
        args=SimpleNamespace(utc='2026-10-20T14:20:00Z',raw=Path('raw'),reference=Path('ref'),
            night=Path('night.vrt'),output=Path('output'),scope_generation=2,
            shared_static_cache=Path('shared'),row=None,assemble_only=False)
        commands=[row_command(args,Path('prepare.py'),r) for r in (0,5500,11000,16500)]
        self.assertEqual({c[c.index('--row')+1] for c in commands},{'0','5500','11000','16500'})
        for command in commands:
            self.assertEqual(command[command.index('--utc')+1],args.utc)
            self.assertEqual(command[command.index('--scope-generation')+1],'2')
            self.assertEqual(command[command.index('--output')+1],'output')
        args.performance_profile=Path('experiment.json')
        command=row_command(args,Path('prepare.py'),0)
        self.assertEqual(command[command.index('--performance-profile')+1],'experiment.json')
        args.row=0
        with self.assertRaises(ValueError):run_rows(args,Path('prepare.py'),2)

if __name__=='__main__':unittest.main()
