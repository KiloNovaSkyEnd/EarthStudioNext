import unittest
from ges.visual_effects import atmosphere_config,validate_atmosphere


class VisualEffectTests(unittest.TestCase):
    def test_optional_settings_use_real_utc_sun_and_explicit_non_observation(self):
        stamp='2020-10-29T16:40:00Z';c=atmosphere_config(stamp)
        self.assertIs(validate_atmosphere(c,stamp),c)
        self.assertTrue(c['day_enabled']);self.assertFalse(c['airglow_enabled'])
        self.assertIn('NOT measured',c['kind'])

    def test_wrong_time_direction_or_excessive_shell_fail(self):
        stamp='2020-10-29T16:40:00Z'
        for change in [{'reference_utc':'2020-10-29T17:40:00Z'}, {'sun_direction_ecef':[1,0,0]},
                       {'shell_height_km':6371}, {'airglow_strength':float('nan')}]:
            c=atmosphere_config(stamp);c.update(change)
            with self.assertRaises(ValueError):validate_atmosphere(c,stamp)
