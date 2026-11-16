import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from ges_next.pipeline import measured_defaults
from ges_next.production.assets import write_json,digest


class MeasuredDefaultsTests(unittest.TestCase):
    def test_host_profile_and_engine_must_all_match(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'worker.py').write_text('qualified',encoding='utf-8')
            profile=dict(HimawariDiskSize=11000,JpegQuality=95,NightLightMetres=1000,Format='jpeg')
            value=dict(host={'node':'fixture'},profile=profile,all_assets_identical=True,
                independent_reopen_verified=True,engine={'worker.py':digest(root/'worker.py')},recommended_max_compute=2)
            write_json(root/'resources/performance/h9_11k_throughput.json',value)
            with patch.object(measured_defaults,'ROOT',root),patch.object(measured_defaults,'host_identity',return_value={'node':'fixture'}):
                self.assertEqual(measured_defaults.load(profile)['recommended_max_compute'],2)
                self.assertEqual(measured_defaults.load(dict(profile,NightLightMetres=500)),{})
                bad=dict(value,science_margin=.5);write_json(root/'resources/performance/h9_11k_throughput.json',bad)
                self.assertEqual(measured_defaults.load(profile),{})
                write_json(root/'resources/performance/h9_11k_throughput.json',value)
                (root/'worker.py').write_text('changed',encoding='utf-8')
                self.assertEqual(measured_defaults.load(profile),{})
            with patch.object(measured_defaults,'ROOT',root),patch.object(measured_defaults,'host_identity',return_value={'node':'other'}):
                self.assertEqual(measured_defaults.load(profile),{})


if __name__=='__main__':unittest.main()
