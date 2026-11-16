"""Bounded fixtures for live append, cancellation, and frozen identity protection."""
import copy,json,unittest
from collections import deque
from unittest.mock import patch
from ges_next.pipeline import queue_changes as changes,runner
from ges_next.production.assets import digest,write_json
from tests.test_parallel_pipeline import ParallelPipelineTests

class QueueChangesTests(unittest.TestCase):
    def setUp(self):
        self.fixture=ParallelPipelineTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.f=self.fixture.f
    def candidate(self):
        f=self.f;project=copy.deepcopy(f.project);project['EndUtc']='2026-10-20T13:50:00Z'
        records=copy.deepcopy(f.records)
        for minute in ('40','50'):
            row=copy.deepcopy(records[0]);row['requested_utc']=f'2026-10-20T13:{minute}:00Z';row['native']['observed_utc']=row['requested_utc']
            row['native']['keys']=[k.replace('1300','13'+minute) for k in row['native']['keys']]
            row['native']['sizes']=[len(k.encode()) for k in row['native']['keys']]
            f.payloads.update({k:k.encode() for k in row['native']['keys']});records.append(row)
        inventory=f.root/'extended_inventory.json';write_json(inventory,dict(project_id=project['Id'],finished=True,project_spec=project,records=records))
        from ges_next.pipeline.plan import create
        return create(project,inventory,f.root/'candidate')
    def test_stage_preserves_frozen_plan_state_and_acceptance(self):
        before={n:digest(self.f.queue/n) for n in ('plan.json','state.json')}
        r=changes.stage(self.f.queue,self.candidate());self.assertEqual(r['added'],2)
        self.assertEqual(before,{n:digest(self.f.queue/n) for n in before})
        self.assertEqual(changes.read(self.f.queue/'effective_plan_summary.json')['steps'].__len__(),6)
    def test_native_revise_action_keeps_original_queue_and_pause(self):
        import types,sys,io
        from contextlib import redirect_stdout
        from pathlib import Path
        candidate=self.candidate();project=dict(self.f.project,EndUtc=candidate['project']['EndUtc']);path=self.f.root/'request.json';write_json(path,project)
        state=changes.read(self.f.queue/'state.json');state['phase']='paused-user';write_json(self.f.queue/'state.json',state)
        module=types.ModuleType('ges_next.pipeline.cli');module.__package__='ges_next.pipeline';module.__file__=str(Path('ges_next/pipeline/cli.py').resolve())
        source=Path('reports/live_queue_changes_20261027/candidate/cli.py')
        exec(compile(source.read_text(encoding='utf-8'),module.__file__,'exec'),module.__dict__)
        out=io.StringIO()
        with patch.object(sys,'argv',['cli','revise','--queue',str(self.f.queue),'--project',str(path),'--inventory',str(self.f.root/'extended_inventory.json')]),redirect_stdout(out):module.main()
        reply=json.loads(out.getvalue());self.assertEqual(len(reply['plan']['steps']),6)
        self.assertEqual(changes.read(self.f.queue/'state.json')['phase'],'paused-user')
    def test_reject_changed_quality_without_manifest(self):
        p=self.candidate();p['project']['Production']['JpegQuality']=90
        with self.assertRaises(ValueError):changes.stage(self.f.queue,p)
        self.assertFalse((self.f.queue/'queue_changes.json').exists())
    def test_reject_replaced_old_object(self):
        p=self.candidate();p['steps'][0]['objects'][0]['etag']='different'
        with self.assertRaises(ValueError):changes.stage(self.f.queue,p)
    def test_refreshed_catalog_missing_old_scan_keeps_its_frozen_identity(self):
        p=self.candidate();original=copy.deepcopy(p['steps'][1]);stamp=original['utc']
        p['steps']=[s for s in p['steps'] if s['utc']!=stamp]
        p['nodes']=[dict(n,state='missing') if n['utc']==stamp else n for n in p['nodes']]
        changes.stage(self.f.queue,p);merged=changes.effective(self.f.queue,changes.read(self.f.queue/'plan.json'))
        self.assertEqual(len(merged['steps']),6)
        self.assertEqual(next(s for s in merged['steps'] if s['utc']==stamp),original)
        self.assertEqual(next(n for n in merged['nodes'] if n['utc']==stamp)['state'],'catalog_available')
    def test_append_updates_guardian_resume_request_without_changing_frozen_plan(self):
        p=self.candidate();request=dict(self.f.project,Name='preserved name');write_json(self.f.queue/'current_request.earthproj',request)
        before=digest(self.f.queue/'plan.json');changes.stage(self.f.queue,p)
        stored=changes.read(self.f.queue/'current_request.earthproj')
        self.assertEqual(stored['EndUtc'],p['project']['EndUtc']);self.assertEqual(stored['Name'],'preserved name')
        self.assertEqual(stored['Production'],request['Production']);self.assertEqual(before,digest(self.f.queue/'plan.json'))
    def test_refresh_retains_previous_append_and_refuses_shortened_range(self):
        p=self.candidate();changes.stage(self.f.queue,p);stamp=p['steps'][-1]['utc']
        smaller=copy.deepcopy(p);smaller['steps']=[s for s in p['steps'] if s['utc']!=stamp]
        changes.stage(self.f.queue,smaller)
        self.assertEqual(len(changes.effective(self.f.queue,changes.read(self.f.queue/'plan.json'))['steps']),6)
        before=digest(self.f.queue/'queue_changes.json')
        with self.assertRaises(ValueError):changes.stage(self.f.queue,changes.read(self.f.queue/'plan.json'))
        self.assertEqual(before,digest(self.f.queue/'queue_changes.json'))
    def test_runtime_difference_requires_current_code_and_existing_certificate(self):
        p=self.candidate();p['runtime']=dict(p['runtime']);p['runtime']['fixture']='qualified current'
        with patch('ges_next.pipeline.plan.runtime_signature',return_value=p['runtime']),patch('ges_next.performance.compatibility.permits',return_value=False):
            with self.assertRaises(ValueError):changes.stage(self.f.queue,p)
        with patch('ges_next.pipeline.plan.runtime_signature',return_value=p['runtime']),patch('ges_next.performance.compatibility.permits',return_value=True):
            self.assertEqual(changes.stage(self.f.queue,p)['added'],2)
    def test_unrelated_runtime_is_rejected_even_if_a_certificate_is_claimed(self):
        p=self.candidate();p['runtime']=dict(p['runtime']);p['runtime']['fixture']='not current'
        with patch('ges_next.performance.compatibility.permits',return_value=True):
            with self.assertRaises(ValueError):changes.stage(self.f.queue,p)
    def test_cancellation_protects_completed_and_active(self):
        p=changes.read(self.f.queue/'state.json');p['completed']=['2026-10-20T13:00:00Z'];p['active']=[dict(utc='2026-10-20T13:10:00Z',phase='producing')];write_json(self.f.queue/'state.json',p)
        r=changes.stage(self.f.queue,cancel_start='2026-10-20T13:00:00Z',cancel_end='2026-10-20T13:30:00Z')
        self.assertEqual(r['excluded'],2);self.assertEqual(len(r['protected']),2)
    def test_manifest_cannot_move_to_another_base(self):
        changes.stage(self.f.queue,self.candidate());p=changes.read(self.f.queue/'queue_changes.json');p['base_plan_sha256']='wrong';write_json(self.f.queue/'queue_changes.json',p)
        with self.assertRaises(ValueError):runner.load(self.f.queue)
    def test_owner_finishes_live_append_without_reprocessing_old(self):
        self.fixture.accept_first();candidate=self.candidate();original=self.f.produce;fired=[]
        def produce(step,package,profile):
            if not fired:
                fired.append(True);changes.stage(self.f.queue,candidate)
            return original(step,package,profile)
        self.f.workers.produce=produce
        state=self.fixture.run_parallel()
        self.assertEqual(state['phase'],'complete');self.assertEqual(len(state['completed']),6)
        self.assertEqual(len(self.f.produced),len(set(self.f.produced)))
        self.assertEqual(state['control_revision'],1)
    def test_cancelled_unstarted_frames_are_not_downloaded_or_produced(self):
        self.fixture.accept_first();changes.stage(self.f.queue,cancel_start='2026-10-20T13:20:00Z',cancel_end='2026-10-20T13:30:00Z')
        state=self.fixture.run_parallel();self.assertEqual(state['phase'],'complete');self.assertEqual(len(state['completed']),2)
        self.assertEqual(len(self.f.calls),120)
        self.assertFalse((self.f.queue/'steps/20261020T132000Z').exists())
    def test_live_cancellation_does_not_touch_inflight_work(self):
        self.fixture.accept_first();original=self.f.produce;fired=[]
        def produce(step,package,profile):
            if not fired:
                fired.append(True);changes.stage(self.f.queue,cancel_start=step['utc'],cancel_end=step['utc'])
            return original(step,package,profile)
        self.f.workers.produce=produce
        state=self.fixture.run_parallel();self.assertEqual(len(state['completed']),4)
    def test_m13_attachment_alias_uses_same_lock_and_state(self):
        from ges_next.pipeline.locking import exclusive,QueueBusyError
        # Reuse the candidate inventory produced by candidate(), not any network.
        candidate=self.candidate();alias=self.f.root/'native_attachment'
        changes.live_append(dict(self.f.project,EndUtc=candidate['project']['EndUtc']),self.f.root/'extended_inventory.json',alias,self.f.queue)
        self.assertEqual(alias.resolve(),self.f.queue.resolve())
        self.assertEqual(digest(alias/'state.json'),digest(self.f.queue/'state.json'))
        with exclusive(self.f.queue/'queue.lock'):
            with self.assertRaises(QueueBusyError):
                with exclusive(alias/'queue.lock'):pass
    def test_failed_alias_stage_removes_only_alias_and_preserves_queue(self):
        candidate=self.candidate();alias=self.f.root/'bad_attachment';original=digest(self.f.queue/'plan.json')
        with patch.object(changes,'stage',side_effect=ValueError('identity conflict')):
            with self.assertRaises(ValueError):changes.live_append(dict(self.f.project,EndUtc=candidate['project']['EndUtc']),self.f.root/'extended_inventory.json',alias,self.f.queue)
        self.assertFalse(alias.exists());self.assertEqual(original,digest(self.f.queue/'plan.json'))
    def test_failed_frame_retries_before_all_new_work_is_consumed(self):
        self.fixture.accept_first();original=self.f.produce;calls=[];failed=[]
        def produce(step,package,profile):
            calls.append(step['utc'])
            if step['utc']=='2026-10-20T13:10:00Z' and not failed:
                failed.append(True);raise RuntimeError('transient fixture failure')
            return original(step,package,profile)
        self.f.workers.produce=produce;write_json(self.f.queue/'unattended.json',dict(enabled=True))
        with patch('ges_next.pipeline.retry_book.SHORT_DELAY',0):state=self.fixture.run_parallel()
        self.assertEqual(state['phase'],'complete');self.assertEqual(len(state['completed']),4)
        self.assertEqual(calls.count('2026-10-20T13:10:00Z'),2)
        self.assertEqual(changes.read(self.f.queue/'frame_retries.json')['frames'],{})

if __name__=='__main__':unittest.main()
