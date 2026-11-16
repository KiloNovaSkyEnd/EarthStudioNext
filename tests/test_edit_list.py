import unittest
from ges_next.layered_sequence.edit_list import layout

class EditListTests(unittest.TestCase):
    def test_reorder_trim_and_repeat_same_weather(self):
        value=layout([dict(scene='B',**{'in':31,'out':60}),dict(scene='A'),dict(scene='B',**{'in':1,'out':30})],{'A':(1,30),'B':(1,90)})
        self.assertEqual([(r['start'],r['end']) for r in value],[(1,30),(31,60),(61,90)])
        self.assertEqual(value[0]['source_in'],31)
    def test_invalid_or_unknown_clip_rejected(self):
        for clip in [dict(scene='X'),dict(scene='A',**{'in':0}),dict(scene='A',**{'out':100}),dict(scene='A',**{'in':9,'out':3})]:
            with self.assertRaises(ValueError):layout([clip],{'A':(1,30)})
