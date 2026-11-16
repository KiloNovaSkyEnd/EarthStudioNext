import tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
from ges_next.production.assets import write_json,record,digest
from ges_next.production.jpeg_layers import encode_jpeg,encode_mask
from ges_next.production.batch_assets import check_pixels
from ges_next.pipeline.worker_validation import selection


class BatchAssetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path.cwd()/'reports');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.package=self.root/'steps'/'frame';self.package.mkdir(parents=True)
        p=self.package;a=np.full((8,8,3),80,np.uint8)
        self.assets=[encode_jpeg(p,'assets/base.jpg',a,95,'stock-clouds-day-without-ground-background'),
            encode_jpeg(p,'assets/night.jpg',a,95,'shared-static-night-background'),
            encode_mask(p,'assets/transmission.png',np.full((8,8),30000,np.uint16),'stock-ground-transmission'),
            encode_mask(p,'assets/support.png',np.full((8,8),255,np.uint8),'actual-observation-support')]
        self.data=dict(utc='2026-10-12T14:10:00Z',assets=self.assets,
            grid=dict(shape=[8,8],maximum_float_recomposition_error=0),quality=dict(psnr_db=45,samples=192))
        write_json(p/'commit.json',self.data)

    def test_complete_decode_and_invalid_quality_or_support_rejected(self):
        check_pixels(self.package,self.data)
        self.data['quality']['psnr_db']=float('nan')
        with self.assertRaises(ValueError):check_pixels(self.package,self.data)
        self.data['quality']['psnr_db']=45
        path=self.package/'assets/support.png';Image.new('L',(8,8),10).save(path)
        self.assets[-1].update(record(self.package,path,self.assets[-1]['role'],[8,8]))
        with self.assertRaisesRegex(ValueError,'observed'):check_pixels(self.package,self.data)

    def test_corrupt_image_cannot_pass_by_rehashing_manifest(self):
        item=self.assets[0];path=self.package/item['path'];path.write_bytes(b'broken JPEG')
        item.update(record(self.package,path,item['role'],[8,8]))
        with self.assertRaises(OSError):check_pixels(self.package,self.data)

    def test_policy_full_first_sample_boundary_and_certificate_integrity(self):
        write_json(self.root/'execution.json',dict(verification=dict(mode='batch',sample_interval=2)))
        steps=[dict(utc=f'2026-10-12T14:{m:02}:00Z') for m in (0,10,20,30)]
        write_json(self.root/'plan.json',dict(project=dict(Production=dict(NightLightMetres=1000)),steps=steps))
        folder=self.root/'certificate';folder.mkdir();certificate=folder/'certificate.json';write_json(certificate,dict(fixture=True))
        with patch('ges_next.pipeline.worker_validation.folder_for',return_value=(folder,{})):
            self.assertEqual(selection(self.package,'fixture')[0],'blender')
            write_json(folder/'receipt.json',dict(sha256=digest(certificate)))
            self.assertEqual(selection(self.package,'fixture')[0],'assets')
            self.data['utc']=steps[2]['utc'];write_json(self.package/'commit.json',self.data)
            self.assertEqual(selection(self.package,'fixture')[0],'blender')
            certificate.write_text('changed')
            with self.assertRaises(ValueError):selection(self.package,'fixture')

    def test_appended_frame_uses_effective_queue_plan(self):
        write_json(self.root/'execution.json',dict(verification=dict(mode='batch',sample_interval=2)))
        original=[dict(utc=f'2026-10-12T14:{m:02}:00Z') for m in (0,10)]
        extended=original+[dict(utc=f'2026-10-12T14:{m:02}:00Z') for m in (20,30)]
        write_json(self.root/'plan.json',dict(project=dict(Production=dict(NightLightMetres=1000)),steps=original))
        self.data['utc']=extended[2]['utc'];write_json(self.package/'commit.json',self.data)
        folder=self.root/'certificate';folder.mkdir();certificate=folder/'certificate.json';write_json(certificate,dict(fixture=True))
        write_json(folder/'receipt.json',dict(sha256=digest(certificate)))
        with patch('ges_next.pipeline.queue_changes.effective',return_value=dict(project=dict(Production=dict(NightLightMetres=1000)),steps=extended)) as effective_plan, \
             patch('ges_next.pipeline.worker_validation.folder_for',return_value=(folder,{})):
            self.assertEqual(selection(self.package,'fixture')[0],'blender')
            effective_plan.assert_called_once()
