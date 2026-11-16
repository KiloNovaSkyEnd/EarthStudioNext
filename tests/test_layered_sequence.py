"""Synthetic tiny sources only; never represent these as satellite observations."""
import json
from pathlib import Path
import unittest
import uuid
import numpy as np
from ges_next.layered_sequence.collection import collect
from ges_next.layered_sequence.package import build
from ges_next.layered_sequence.preview import prepare
from ges_next.production.assets import write_json,record,digest,verify_assets
from ges_next.production.jpeg_layers import encode_jpeg,encode_mask
from ges_next.production.rebuild_recipe import BANDS


class SequenceTests(unittest.TestCase):
    def setUp(self):
        self.root=(Path('reports/layered_sequence_fixtures')/uuid.uuid4().hex).resolve();self.root.mkdir(parents=True)
        self.sources=[self.source('00',40),self.source('10',160)]

    def source(self,minute,value):
        root=self.root/minute;root.mkdir();rgb=np.full((8,8,3),value,np.uint8)
        assets=[encode_jpeg(root,'base.jpg',rgb,95,'stock-clouds-day-without-ground-background'),
            encode_jpeg(root,'night.jpg',rgb*0,95,'shared-static-night-background'),
            encode_mask(root,'transmission.png',np.zeros((8,8),np.uint16),'stock-ground-transmission'),
            encode_mask(root,'support.png',np.full((8,8),255,np.uint8),'actual-observation-support')]
        utc=f'2026-10-20T13:{minute}:00Z';rows=[]
        for band in BANDS:
            for segment in range(1,11):
                rows.append(dict(bucket='noaa-himawari9',key=f'AHI-L1b-FLDK/2026/10/20/13{minute}/HS_H09_20261020_13{minute}_{band}_FLDK_R10_S{segment:02}10.DAT.bz2',
                    bytes=1,sha256='0'*64,etag='"fixture"'))
        write_json(root/'rebuild_recipe.json',dict(schema='earthstudio.h9.rebuild.v1',utc=utc,inputs=rows,test_fixture_only=True))
        write_json(root/'commit.json',dict(schema='earthstudio.layered_jpeg.v1',utc=utc,assets=assets,quality=dict(psnr_db=40),
            grid=dict(shape=[8,8],extent=[-180,-90,180,90],crs='EPSG:4326'),
            rebuild_recipe=record(root,root/'rebuild_recipe.json','single-scan-rebuild-recipe'),test_fixture_only=True))
        return root

    def test_single_frame_delivery_has_full_grid_jpg_and_fixed_weather(self):
        from ges_next.layered_sequence.still import export_still
        from PIL import Image
        root=self.root/'still';result=build(self.sources[:1],root);manifest=prepare(root,width=1024)
        self.assertEqual(len(manifest['frames']),1);self.assertNotIn('videoPreview',manifest)
        proof=export_still(root)
        with Image.open(root/'GeoColor.jpg') as image:self.assertEqual(image.size,(8,8))
        self.assertTrue(proof['layers_remain_editable']);verify_assets(root,result['files'])
        with self.assertRaises(FileExistsError):export_still(root)

    def test_portable_copy_and_source_preserved(self):
        before={p:digest(p) for r in self.sources for p in r.iterdir() if p.is_file()}
        result=build(self.sources,self.root/'delivery')
        self.assertEqual(len(result['nodes']),2);verify_assets(self.root/'delivery',result['files']+result['auxiliary_files'])
        self.assertTrue(all(digest(p)==v for p,v in before.items()))
        self.assertTrue(all(p.stat().st_nlink==1 for p in (self.root/'delivery/assets').rglob('*') if p.is_file()))
        (self.sources[0]/'base.jpg').unlink()  # Only tiny test source, copied delivery remains independent.
        verify_assets(self.root/'delivery',result['files'])

    def test_corruption_rejected(self):
        (self.sources[0]/'base.jpg').write_bytes(b'bad')
        with self.assertRaises(ValueError):collect(self.sources)

    def test_duplicate_times_rejected(self):
        with self.assertRaises(ValueError):collect([self.sources[0],self.sources[0]])

    def test_gap_is_blank_support(self):
        later=self.source('20',240);result=build([self.sources[0],later],self.root/'gap')
        self.assertTrue(result['nodes'][1]['missing'])
        from PIL import Image
        with Image.open(self.root/'gap/assets/support/weather_0002.png') as image:self.assertEqual(np.asarray(image).max(),0)

    def test_mixed_grid_rejected(self):
        path=self.sources[1]/'commit.json';value=json.loads(path.read_text());value['grid']['extent'][0]=-170;write_json(path,value)
        with self.assertRaises(ValueError):collect(self.sources)

    def test_independent_finer_night_survives_package_and_flat_still(self):
        from ges_next.layered_sequence.still import export_still
        from PIL import Image
        role='shared-static-night-background'
        source=self.sources[0];path=source/'commit.json';value=json.loads(path.read_text())
        pixels=np.full((16,16,3),100,np.uint8)
        finer=encode_jpeg(source,'finer_night.jpg',pixels,95,role)
        value['assets']=[a if a['role']!=role else finer for a in value['assets']]
        value['grid']['layer_shapes']={role:[16,16]};write_json(path,value)
        with self.assertRaises(ValueError):collect(self.sources)  # Do not mix night profiles in a sequence.
        target=self.root/'finer_delivery';result=build([source],target)
        night=next(a for a in result['files'] if a['role']==role)
        with Image.open(target/night['path']) as image:self.assertEqual(image.size,(16,16))
        proof=export_still(target)
        self.assertEqual(proof['independent_night_shape'],[16,16])
        with Image.open(target/'GeoColor.jpg') as image:self.assertEqual(image.size,(8,8))

    def test_no_overwrite(self):
        build(self.sources,self.root/'delivery')
        with self.assertRaises(FileExistsError):build(self.sources,self.root/'delivery')

    def test_no_write_inside_source(self):
        with self.assertRaises(ValueError):build(self.sources,self.sources[0]/'nested')

    def test_nan_quality_rejected(self):
        path=self.sources[1]/'commit.json';value=json.loads(path.read_text());value['quality']['psnr_db']=float('nan');write_json(path,value)
        with self.assertRaises(ValueError):collect(self.sources)

    def test_unfinished_queue_scan_not_treated_as_missing(self):
        import shutil
        from ges_next.layered_sequence.collection import from_queue
        queue=self.root/'queue';later=self.source('20',200)
        for minute,source in (('00',self.sources[0]),('20',later)):
            shutil.copytree(source,queue/f'steps/20261020T13{minute}00Z')
        plan=dict(project=dict(IntervalMinutes=10),steps=[dict(utc=f'2026-10-20T13:{m}:00Z') for m in ('00','10','20')])
        write_json(queue/'plan.json',plan);write_json(queue/'state.json',dict(plan_sha256=digest(queue/'plan.json')))
        with self.assertRaises(ValueError):from_queue(queue)
        plan['steps'].pop(1);write_json(queue/'plan.json',plan);write_json(queue/'state.json',dict(plan_sha256=digest(queue/'plan.json')))
        paths,step=from_queue(queue);self.assertEqual((len(paths),step),(2,10))

    def test_layout_corruption_is_detected(self):
        result=build(self.sources,self.root/'delivery');(self.root/'delivery/native_master.json').write_text('{}')
        with self.assertRaises(ValueError):verify_assets(self.root/'delivery',result['auxiliary_files'])

    def test_preview_movie_and_formal_hashes(self):
        root=self.root/'delivery';result=build(self.sources,root);manifest=prepare(root,width=1024)
        self.assertEqual(manifest['videoPreview']['frames'],2);self.assertTrue(manifest['previewDisplayOnly'])
        self.assertGreater((root/'timelapse.mp4').stat().st_size,0);verify_assets(root,result['files'])
        import imageio_ffmpeg,subprocess
        decoded=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-i',str(root/'timelapse.mp4'),'-f','rawvideo','-pix_fmt','rgb24','pipe:1'],capture_output=True,check=True).stdout
        frames=np.frombuffer(decoded,np.uint8).reshape(2,512,1024,3)
        self.assertGreater(np.abs(frames[0].astype(float)-frames[1]).mean(),20)


if __name__=='__main__':unittest.main()
