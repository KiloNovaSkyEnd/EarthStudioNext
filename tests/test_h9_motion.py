import unittest
from ges_next.h9_motion import observation_times, weather_index, storage_budget

class H9MotionTests(unittest.TestCase):
    def test_utc_crosses_date_and_retains_both_endpoints(self):
        times = observation_times()
        self.assertEqual(len(times),37)
        self.assertEqual(times[0].isoformat(),'2026-10-20T18:00:00+00:00')
        self.assertEqual(times[-1].isoformat(),'2026-10-21T00:00:00+00:00')
        self.assertTrue(all((b-a).total_seconds()==600 for a,b in zip(times,times[1:])))
    def test_retime_preserves_same_weather_path(self):
        for i in range(37):
            self.assertEqual(weather_index(i),i)
            self.assertEqual(weather_index(i*2,duration=72),i)
        self.assertEqual(weather_index(-1),0)
        self.assertEqual(weather_index(100),36)
        self.assertEqual(weather_index(.99),0)
    def test_refuse_ambiguous_or_misaligned_times(self):
        for start in ['2026-10-20T11:00:00','2026-10-20T11:01:00-07:00']:
            with self.assertRaises(ValueError): observation_times(start)
        with self.assertRaises(ValueError): weather_index(1,duration=0)
    def test_forecast_cannot_claim_available_storage(self):
        budget=storage_budget(17_449_381_617,17_449_381_617,51_288_416_256)
        self.assertFalse(budget['sufficient'])
        self.assertGreater(budget['required_free_bytes'],70_000_000_000)

if __name__=='__main__': unittest.main()
