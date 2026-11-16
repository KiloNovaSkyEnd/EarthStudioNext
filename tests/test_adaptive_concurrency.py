import json,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
from ges_next.pipeline.admission import GIB,options
from ges_next.pipeline.concurrency import Concurrency
from ges_next.production.assets import write_json


class AdaptiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.memory=types.SimpleNamespace(available=24*GIB)
        for name,value in [('ges_next.pipeline.concurrency.gpu_free_bytes',4*GIB),
                           ('psutil.cpu_percent',30),('psutil.virtual_memory',self.memory)]:
            mock=patch(name,return_value=value);mock.start();self.addCleanup(mock.stop)
        self.configure('auto',8)

    def configure(self,control,count,prefetch=3):
        write_json(self.root/'execution.json',dict(mode='parallel',control=control,max_compute=count,prefetch=prefetch))

    def test_manual_five_fills_first_three_and_budgets_additional_launches(self):
        self.configure('manual',5);g=Concurrency(self.root,8,3)
        g.refresh([],True,100);self.assertEqual(g.target,5)
        self.memory.available=9*GIB
        self.assertTrue(g.admit([]))
        three=[dict(package=f'scan{i}',phase='producing',threads=4) for i in range(3)]
        self.assertFalse(g.admit(three))
        self.memory.available=32*GIB
        self.assertTrue(g.admit(three))

    def test_manual_target_met_does_not_warn_about_hypothetical_extra_scan(self):
        self.configure('manual',3);g=Concurrency(self.root,3,3)
        tasks=[dict(package=f'scan{i}',phase='producing',threads=4) for i in range(3)]
        with patch.object(g,'admit',return_value=False) as admission:
            g.refresh(tasks,True,100)
            admission.assert_not_called()
        self.assertEqual(g.reason,'manual-target');self.assertEqual(g.details()['actual_science'],3)
        self.configure('manual',4)
        with patch.object(g,'admit',return_value=False):g.refresh(tasks,True,111)
        self.assertEqual(g.reason,'memory-or-vram-limit');self.assertEqual(g.target,4)

    def test_auto_ramps_and_honours_live_shrink_and_prefetch(self):
        g=Concurrency(self.root,8,3);g.refresh([],True,100);self.assertEqual(g.target,3)
        g.refresh([],True,111);self.assertEqual(g.target,4)
        self.configure('manual',1,2);g.refresh([],True,122)
        self.assertEqual(g.target,1);self.assertEqual(g.prefetch,2)

    def test_pressure_can_reduce_extras_but_preserves_minimum_three(self):
        g=Concurrency(self.root,8,3);g.refresh([],True,100)
        self.memory.available=4*GIB;g.refresh([],True,111)
        self.assertEqual(g.target,3);self.assertEqual(g.reason,'minimum-three-priority')
        self.assertTrue(g.admit([]))
        self.assertFalse(g.admit([dict(package=str(i),phase='producing') for i in range(3)]))

    def test_measured_peak_reserves_future_worker_allocations(self):
        p=self.root/'scan';write_json(p/'scratch/work/reports/resource_usage.json',
            dict(process_rss_bytes=3*GIB,process_peak_rss_bytes=8*GIB))
        three=[p,self.root/'second',self.root/'third']
        g=Concurrency(self.root,8,3);g.refresh(three,True,100)
        self.assertEqual(g.budget,10*GIB)
        self.memory.available=20*GIB;self.assertFalse(g.admit(three))
        write_json(p/'performance.json',dict(process_peak_rss_bytes=8*GIB))
        g.sample_completed(p);self.assertEqual(Concurrency(self.root,8,3).history,[8*GIB])

    def test_low_vram_defers_extras_but_not_user_selected_first_three(self):
        with patch('ges_next.pipeline.concurrency.gpu_free_bytes',return_value=256*1024**2):
            g=Concurrency(self.root,8,3);g.refresh([],True,100);self.assertTrue(g.admit([]))
            self.assertFalse(g.admit([dict(package=str(i),phase='producing') for i in range(3)]))

    def test_recovery_keeps_measured_threads_after_pressure(self):
        write_json(self.root/'execution.json',dict(mode='parallel',control='auto',max_compute=3,prefetch=3,
            recommended_max_compute=3,thread_profiles={'2':5,'3':4}))
        g=Concurrency(self.root,3,3);g.science_by_threads={'5':[4*GIB],'4':[4*GIB]}
        self.memory.available=4*GIB;g.refresh([],True,100)
        self.assertEqual(g.target,3);self.assertEqual(g.thread_count(),4)
        self.memory.available=int(9.5*GIB);g.refresh([],True,111)
        self.assertEqual(g.target,3);self.assertEqual(g.budget,5*GIB)

    def test_high_cpu_alone_does_not_block_resource_safe_ramp(self):
        with patch('psutil.cpu_percent',return_value=99):
            g=Concurrency(self.root,8,3);g.refresh([],True,100)
            self.assertEqual(g.target,3);self.assertTrue(g.admit([]))

    def test_count_validation(self):
        for invalid in (0,9,True,2.5):
            self.configure('manual',invalid)
            with self.assertRaises(ValueError):options(self.root)
        self.configure('manual',5);self.assertEqual(options(self.root)['max_compute'],5)

    def test_user_floor_overrides_lower_auto_recommendation(self):
        write_json(self.root/'execution.json',dict(mode='parallel',control='auto',max_compute=8,prefetch=3,
            recommended_max_compute=2,thread_profiles={'2':5},decode_threads=4))
        g=Concurrency(self.root,8,3);g.refresh([],True,100)
        self.assertEqual(g.target,3);self.assertEqual(g.worker_environment()['EARTHSTUDIO_COMPUTE_THREADS'],'5')
        value=options(self.root);value.update(control='manual',max_compute=5);write_json(self.root/'execution.json',value)
        g.refresh([],True,111);self.assertEqual(g.target,5);self.assertEqual(g.requested,5)

    def test_profiled_memory_budget_is_separate_from_unknown_thread_budget(self):
        g=Concurrency(self.root,8,3);g.science_by_threads={'4':[4*GIB]}
        self.assertEqual(g.estimated_budget(4),5*GIB)
        self.assertEqual(g.estimated_budget(8),6*GIB)

    def test_qualified_profile_starts_with_measured_target_and_keeps_os_reserve(self):
        qualification=dict(recommended_max_compute=3,science_margin=1.15,science_by_threads={'4':[4*GIB]})
        with patch('ges_next.pipeline.measured_defaults.load',return_value=qualification):
            g=Concurrency(self.root,8,3,profile={'fixture':True})
        self.assertEqual(g.target,3);self.assertEqual(g.estimated_budget(4),int(4*GIB*1.15))
        self.assertEqual(g.estimated_budget(8),6*GIB)

    def test_small_requested_counts_and_serial_keep_original_admission(self):
        self.memory.available=0
        for count in (1,2):
            self.configure('manual',count);g=Concurrency(self.root,count,3);g.refresh([],True,100)
            self.assertEqual(g.minimum_science(),0);self.assertFalse(g.admit([]))
        write_json(self.root/'execution.json',dict(mode='serial',control='manual',max_compute=8,prefetch=3))
        g=Concurrency(self.root,8,3);g.refresh([],True,100)
        self.assertEqual(g.minimum_science(),0);self.assertEqual(g.target,1)

    def test_floor_does_not_fake_workers_without_ready_inputs(self):
        self.configure('manual',3);g=Concurrency(self.root,3,3);g.refresh([],False,100)
        self.assertEqual(g.target,3);self.assertEqual(g.details()['actual_science'],0)
        self.assertEqual(g.details()['minimum_science'],3)

    def test_finished_or_waiting_work_does_not_count_as_running_science(self):
        self.configure('manual',3);g=Concurrency(self.root,3,3)
        tasks=[dict(package='a',phase='producing'),dict(package='b',phase='producing'),
            dict(package='c',phase='waiting-verification'),dict(package='d',phase='cleaning')]
        g.refresh(tasks,True,100);self.assertEqual(g.actual_science,2)
        self.memory.available=0;self.assertTrue(g.admit(tasks))


if __name__=='__main__':unittest.main()
