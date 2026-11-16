"""Experimental execution changes cannot enter science without qualification."""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT=Path(__file__).resolve().parents[1]


class PerformanceProfileTests(unittest.TestCase):
    def test_unqualified_chunk_and_shared_solar_stop_before_input_inventory(self):
        cases=[(dict(compute_chunk=1024),'chunk changes require pixel parity'),
            (dict(zlevel=1),'level changes require full encoding qualification'),
            (dict(zlevel=True),'Only qualified lossless DEFLATE'),
            (dict(zlevel=1,lossless_level_pixel_parity_qualified=True,allow_storage_growth=False),'storage policy forbids larger'),
            (dict(gdal_threads=8,encoding_pixel_parity_qualified=True),'Eight encoder threads require dedicated'),
            (dict(shared_solar_factors=True),'solar factors require exact qualification')]
        for extra,message in cases:
            with TemporaryDirectory(dir=ROOT/'data') as temporary:
                folder=Path(temporary);profile=folder/'profile.json'
                profile.write_text(json.dumps(dict(pixel_parity_qualified=True,compute_workers=6,**extra)))
                output=folder/'output'
                result=subprocess.run([sys.executable,str(ROOT/'scripts/prepare_native_h9_disk.py'),
                    '--raw',str(folder),'--reference',str(folder),'--night',str(folder/'absent'),
                    '--output',str(output),'--performance-profile',str(profile)],capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0)
                self.assertIn(message,result.stderr)
                self.assertFalse((output/'input_inventory.json').exists())
