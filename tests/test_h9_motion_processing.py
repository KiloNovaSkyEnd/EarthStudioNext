import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('h9worker',root/'scripts/run_h9_motion_processing.py')
worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)

class H9DownloadTests(unittest.TestCase):
    def test_coordinator_download_overlaps_science_and_is_not_repeated(self):
        from threading import Event
        from ges_next.h9_prefetch import OneScanPrefetch
        next_started=Event();downloads=[];computed=[]
        first='2026-10-20T15:00:00Z';second='2026-10-20T15:10:00Z'
        scenes=[dict(utc=utc,missing=[],objects=[dict(bytes=10)]) for utc in (first,second)]
        plan=dict(scenes=scenes,complete_nodes=2,generation=4)
        def fetch_scene(scene):
            downloads.append(scene['utc'])
            if scene['utc']==second:next_started.set()
            return ['validated.dat']
        def compute(command,**kwargs):
            utc=command[command.index('--utc')+1]
            if utc==first:self.assertTrue(next_started.wait(3),'Next download did not overlap compute')
            computed.append(utc)
            output=Path(command[command.index('--output')+1]);output.mkdir(parents=True)
            (output/'native_master.json').write_text('{}')
        def validate(folder,utc):
            return dict(sourceBands=dict(B03=dict(startUtc=utc,endUtc=utc)))
        with tempfile.TemporaryDirectory(dir=root/'data') as folder:
            folder=Path(folder)
            for name in ['reports','scratch','processed','exports']:(folder/name).mkdir()
            with patch.object(worker,'PROJECT',folder),patch.object(worker,'update'),\
                    patch.object(worker,'fetch_scan',side_effect=fetch_scene),\
                    patch.object(worker,'check_space'),patch.object(worker,'decode_originals'),\
                    patch.object(worker,'verify_prefetched_sources') as verify_prefetched,\
                    patch.object(worker,'validate_master',side_effect=validate),\
                    patch.object(worker.subprocess,'run',side_effect=compute):
                with OneScanPrefetch(fetch_scene,lambda n:None,lambda data:None,True) as prefetch:
                    worker.execute_scans(plan,2,[],Path('night.vrt'),Path('reference'),prefetch)
                verify_prefetched.assert_called_once_with(scenes[1],['validated.dat'])
            result=json.loads((folder/'reports/native_frames.json').read_text())
            self.assertEqual(result['completed'],2)
            self.assertEqual([f['utc'] for f in result['frames']],[first,second])
        self.assertEqual(downloads,[first,second])
        self.assertEqual(computed,[first,second])

    def test_prefetched_original_is_rechecked_after_wait(self):
        with tempfile.TemporaryDirectory(dir=root/'data') as folder:
            folder=Path(folder);source=folder/'HS_H09_test.DAT.bz2';source.write_bytes(b'original')
            obj=dict(key='prefix/'+source.name,bytes=8,etag='provider-etag')
            source.with_suffix(source.suffix+'.json').write_text(json.dumps(dict(
                **obj,sha256=hashlib.sha256(b'original').hexdigest())))
            worker.verify_prefetched_sources(dict(objects=[obj]),[source])
            source.write_bytes(b'modified')
            with self.assertRaisesRegex(ValueError,'before decode'):
                worker.verify_prefetched_sources(dict(objects=[obj]),[source])

    def test_unchanged_night_mosaic_does_not_invalidate_shared_cache(self):
        from ges.earth_validation.night_background import build_vrt,TILE_IDS
        with tempfile.TemporaryDirectory(dir=root/'data') as folder:
            folder=Path(folder)
            entries=[dict(tile=tile,file=str(folder/(tile+'.tif'))) for tile in TILE_IDS]
            path=build_vrt(folder/'global_500m.vrt',entries)
            before=(path.stat().st_mtime_ns,path.read_bytes())
            build_vrt(path,entries)
            self.assertEqual((path.stat().st_mtime_ns,path.read_bytes()),before)
    def test_expanded_inventory_requires_explicit_gap_and_preserves_utc(self):
        report=json.loads((root/'data/projects/H9_20261020_UTCminus7_1100_1700/reports/expanded_12h_storage_preflight.json').read_text())
        plan=dict(satellite='himawari9',user_start=report['user_start'],user_end=report['user_end'],
                  complete_nodes=72,scenes=report['scenes'],acknowledged_missing_utc=['2026-10-20T14:40:00Z'])
        self.assertEqual(worker.validate_plan(plan),(73,['2026-10-20T14:40:00Z']))
        plan['acknowledged_missing_utc']=[]
        with self.assertRaises(ValueError):worker.validate_plan(plan)
    def test_scope_change_leaves_old_scan_output_untouched(self):
        import subprocess,sys
        with tempfile.TemporaryDirectory(dir=root/'data') as folder:
            folder=Path(folder)
            (folder/'requested_scope.json').write_text(json.dumps(dict(generation=2)))
            output=folder/'do_not_create'
            result=subprocess.run([sys.executable,str(root/'scripts/prepare_native_h9_disk.py'),
                '--raw',str(folder),'--reference',str(folder),'--night',str(folder/'absent.vrt'),
                '--output',str(output),'--shared-static-cache',str(folder/'shared_static')],capture_output=True)
            self.assertEqual(result.returncode,75)
            self.assertFalse(output.exists())
    def test_etag_checked_resume_and_immutable_cache(self):
        body=b'exact observed bytes, not a weather fixture'
        etag='"'+hashlib.md5(body).hexdigest()+'"'
        obj=dict(key='test.DAT.bz2',bytes=len(body),etag=etag)
        calls=[]
        class Client:
            def get_object(self,**options):
                calls.append(options)
                offset=int(options.get('Range','bytes=0-').split('=')[1].split('-')[0])
                return dict(ContentLength=len(body)-offset,ETag=etag,Body=io.BytesIO(body[offset:]))
        with tempfile.TemporaryDirectory(dir=root/'data') as folder:
            folder=Path(folder)
            partial=folder/'test.DAT.bz2.part'
            partial.write_bytes(body[:7])
            partial.with_suffix('.identity.json').write_text(json.dumps(obj))
            with patch.object(worker,'s3_client',return_value=Client()):
                path=worker.fetch(obj,folder)
                self.assertEqual(path.read_bytes(),body)
                self.assertEqual(calls[0]['IfMatch'],etag)
                self.assertEqual(calls[0]['Range'],'bytes=7-')
                worker.fetch(obj,folder)
                self.assertEqual(len(calls),1)
                path.write_bytes(body[:-1]+b'!')
                with self.assertRaises(ValueError):worker.fetch(obj,folder)
    def test_reject_unknown_partial_without_touching_it(self):
        with tempfile.TemporaryDirectory(dir=root/'data') as folder:
            folder=Path(folder);p=folder/'x.bz2.part';p.write_bytes(b'keep')
            with self.assertRaises(ValueError):worker.fetch(dict(key='x.bz2',bytes=10,etag='"a"'),folder)
            self.assertEqual(p.read_bytes(),b'keep')
    def test_safety_reserve_stops_before_download(self):
        with patch.object(worker.shutil,'disk_usage',return_value=type('Disk',(),dict(free=worker.RESERVE))()):
            with self.assertRaises(RuntimeError):worker.check_space(1)

if __name__=='__main__':unittest.main()
