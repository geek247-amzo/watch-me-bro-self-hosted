import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image
import app
from captions import responsive_subtitles
from titles import settings, sprite, layers, composite_titles


class ResponsiveTitles(unittest.TestCase):
    def test_settings_legacy_bounds_and_injection(self):
        self.assertEqual(settings({'headline': 'Hello'}, 1)['headline_end'], 1)
        self.assertEqual(settings({}, 10)['title_style'], '3d')
        for bad in [{'headline_start': -1}, {'headline_end': 11}, {'headline_start': 4, 'headline_end': 2},
                    {'headline_end': float('nan')}, {'headline_start': True}, {'title_style': 'movie=/etc/passwd'},
                    {'title_size': []}, {'title_position': None}]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                settings({'headline': 'Hello', **bad}, 10)

    def test_plan_persists_title_controls(self):
        overlay=dict(headline='Hello', headline_start=1.25, headline_end=3.75, title_style='3d', title_size='large', title_position='centre')
        plan=app.validate_plan(dict(format='vertical', audio='mute', cuts=[dict(source='s',start=0,end=5)], overlay=overlay), {'s':dict(id='s',duration=5)})
        for key,value in overlay.items():
            self.assertEqual(plan['overlay'][key],value)

    def test_sprite_wraps_and_shrinks_without_losing_text_for_all_output_shapes(self):
        text='WATCH THIS INCREDIBLY LONG GAMING TITLE '+ 'W'*48 + ' 100% %{literal}'
        with tempfile.TemporaryDirectory(prefix='wmb-title-test-') as tmp:
            for width,height in [(1080,1920),(1920,1080),(720,1280),(1280,720)]:
                for size in ['small','medium','large']:
                    path=Path(tmp)/'title.png'
                    result=sprite(text,path,width,height,dict(title_size=size,title_style='3d'))
                    self.assertLessEqual(result['width'],width*.8)
                    self.assertLessEqual(result['height'],height*.23)
                    self.assertEqual(''.join(result['text'].split()), ''.join(text.split()))
                    with Image.open(path) as image:
                        bounds=image.getbbox()
                        self.assertGreater(bounds[0],0)
                        self.assertGreater(bounds[1],0)
                        self.assertLess(bounds[2],image.width)
                        self.assertLess(bounds[3],image.height)

    def test_real_timed_title_is_visible_only_in_its_window_with_intro_offset(self):
        with tempfile.TemporaryDirectory(prefix='wmb-timed-title-') as tmp:
            root=Path(tmp)
            for width,height in [(320,180),(180,320)]:
                video=root/'video.mp4'
                app.run(['ffmpeg','-nostdin','-y','-v','error','-threads','1','-filter_threads','1','-f','lavfi','-i',f'color=c=black:s={width}x{height}:r=30:d=4',
                         '-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t','4','-c:v','libx264','-threads','1','-pix_fmt','yuv420p','-c:a','aac',str(video)])
                overlay=dict(headline='MY GREAT MOMENT',headline_start=.5,headline_end=1.5,title_style='3d',title_size='large',title_position='centre')
                composite_titles(app.run,root,video,overlay,width,height,1,3,0)
                def pixels(t):
                    raw=app.run(['ffmpeg','-nostdin','-v','error','-threads','1','-ss',str(t),'-i',str(video),'-frames:v','1','-threads','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'])
                    return Image.frombytes('RGB',(width,height),raw)
                self.assertIsNone(pixels(1.2).getbbox())
                bounds=pixels(2).getbbox()
                self.assertIsNotNone(bounds)
                # Encoder ringing may extend a few pixels outside the measured glyphs.
                self.assertGreaterEqual(bounds[0],width*.1-8)
                self.assertLessEqual(bounds[2],width*.9+8)
                self.assertIsNone(pixels(2.8).getbbox())
                self.assertFalse(list(root.glob('title-layer-*.png')))

    def test_responsive_subtitles_use_output_geometry_and_disable_ass_overrides(self):
        with tempfile.TemporaryDirectory(prefix='wmb-subtitle-test-') as tmp:
            for width,height in [(320,180),(180,320)]:
                path=Path(tmp)/'captions.ass'
                filters=responsive_subtitles([dict(start=0,end=1,text=r'A long caption {\pos(0,0)} with a dangerous override and many wide words')],path,'gaming',width,height)
                body=path.read_text()
                self.assertIn(f'PlayResX: {width}',body)
                self.assertIn(f'PlayResY: {height}',body)
                self.assertNotIn(r'{\pos',body)
                raw=app.run(['ffmpeg','-nostdin','-v','error','-threads','1','-filter_threads','1','-f','lavfi','-i',f'color=c=black:s={width}x{height}:d=1', '-vf',filters,'-frames:v','1','-threads','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'])
                image=Image.frombytes('RGB',(width,height),raw)
                bounds=image.getbbox()
                self.assertIsNotNone(bounds)
                self.assertGreaterEqual(bounds[0],width*.08)
                self.assertLessEqual(bounds[2],width*.92)


if __name__=='__main__':
    unittest.main()
