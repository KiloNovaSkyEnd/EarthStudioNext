import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from scripts import refine_goni_ir,restore_goni_lowcloud,restore_goni_spectral,refine_goni_daylight


class PipelineReentryTests(unittest.TestCase):
    def test_earlier_stages_cannot_rewind_a_completed_material(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);frame=root/'goni_film_v1/frames/20201030T0400Z';frame.mkdir(parents=True)
            m={'material_revision':6,'vis':{'band':'B03'},'lowcloud_restoration':{'roi_native_yx':list(restore_goni_lowcloud.ROI)},
               'daylight_restoration':{'roi_tone_feather':True}}
            path=frame/'frame.json';path.write_text(json.dumps(m));before=path.read_bytes()
            item={'nominal_utc':'2020-10-30T04:00:00+00:00'}
            for module,function in [(refine_goni_ir,'refine'),(restore_goni_lowcloud,'restore'),
                                    (restore_goni_spectral,'restore'),(refine_goni_daylight,'refine')]:
                with patch.object(module,'load_config',return_value=SimpleNamespace(processed_dir=root)):
                    self.assertEqual(getattr(module,function)(item)['material_revision'],6)
                self.assertEqual(path.read_bytes(),before)
