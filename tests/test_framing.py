import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import app
from framing import geometry, validate_crop


class Framing(unittest.TestCase):
    def test_crop_validation_rejects_nonfinite_outside_tiny_and_injected_values(self):
        valid = dict(mode='crop',x=.5,y=0,width=.5,height=1)
        self.assertEqual(validate_crop(valid),valid)
        self.assertEqual(validate_crop({'mode':'fit'}),{'mode':'fit'})
        for value in [None,[],{'mode':'unknown'},dict(valid,x=-.1),dict(valid,width=.7),dict(valid,height=.001),dict(valid,y=float('nan')),dict(valid,width=True),dict(valid,x='0;movie=/etc/passwd')]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):validate_crop(value)

    def test_plan_preserves_per_clip_crop_and_legacy_default(self):
        sources={'source':dict(id='source',duration=10)}
        plan=dict(format='vertical',audio='mute',cuts=[dict(source='source',start=1,end=5,crop=dict(mode='crop',x=.5,y=0,width=.5,height=1))])
        clean=app.validate_plan(plan,sources)
        self.assertEqual(clean['cuts'][0]['crop']['x'],.5)
        del plan['cuts'][0]['crop']
        self.assertNotIn('crop',app.validate_plan(plan,sources)['cuts'][0])
        self.assertIn('force_original_aspect_ratio=increase',geometry(None,90,160,True))
        self.assertNotIn('force_original_aspect_ratio=increase',geometry({'mode':'fit'},90,160,True))

    def test_real_ffmpeg_crop_selects_right_side_not_centre(self):
        # Synthetic source: left half red, right half blue. No production state/media.
        with tempfile.TemporaryDirectory(prefix='wmb-framing-test-') as tmp:
            output=Path(tmp)/'crop.mp4'
            def render(crop):
                subprocess.run(['ffmpeg','-nostdin','-y','-v','error','-threads','1','-filter_threads','1','-f','lavfi','-i','color=c=red:s=320x180:r=30:d=0.3,drawbox=x=160:y=0:w=160:h=180:color=blue:t=fill',
                                '-vf',geometry(crop,90,160,True)+',setsar=1','-an','-c:v','libx264','-pix_fmt','yuv420p','-threads','1',str(output)],check=True)
                info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(output)]))
                self.assertEqual((info['streams'][0]['width'],info['streams'][0]['height']),(90,160))
                return subprocess.check_output(['ffmpeg','-nostdin','-v','error','-threads','1','-filter_threads','1','-i',str(output),'-vf','crop=2:2:44:78,format=rgb24','-frames:v','1','-threads','1','-f','rawvideo','pipe:1'])[:3]
            right=render(dict(mode='crop',x=.5,y=0,width=.5,height=1))
            left=render(dict(mode='crop',x=0,y=0,width=.5,height=1))
            self.assertGreater(right[2],200);self.assertLess(right[0],30)
            self.assertGreater(left[0],200);self.assertLess(left[2],30)
            render({'mode':'fit'})


if __name__=='__main__':unittest.main()
