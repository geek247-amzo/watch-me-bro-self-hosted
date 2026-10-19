"""Fixed, editable subtitle designs; never generated or guessed speech."""
STYLES = {
    'studio': 'FontName=DejaVu Sans,Fontsize=24,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00101010,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=30,MarginL=24,MarginR=24',
    'gaming': 'FontName=DejaVu Sans,Fontsize=27,Bold=1,PrimaryColour=&H005BF8D2,OutlineColour=&H00101010,BorderStyle=1,Outline=3,Shadow=1,Alignment=2,MarginV=38,MarginL=24,MarginR=24',
    'boxed': 'FontName=DejaVu Sans,Fontsize=23,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H80101010,BorderStyle=3,Outline=4,Shadow=0,Alignment=2,MarginV=30,MarginL=24,MarginR=24',
}


def validate_style(value):
    if not isinstance(value, str) or value not in STYLES:
        raise ValueError('Choose Studio, Gaming or Boxed caption style.')
    return value


def subtitle_filter(path, style):
    # Path comes from the server-created job folder, never the browser.
    return f"subtitles={path}:force_style='{STYLES[validate_style(style)]}'"


def responsive_subtitles(items, path, style, width, height):
    """Exact output-resolution ASS with measured wrapping and UI-safe margins."""
    from PIL import Image, ImageDraw, ImageFont
    from titles import FONT, wrap
    validate_style(style)
    primary = '&H005BF8D2' if style == 'gaming' else '&H00FFFFFF'
    border, outline = (3, 4) if style == 'boxed' else (1, 3)
    margin = round(height * (.18 if height > width else .09))
    header = f'''[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,DejaVu Sans,30,{primary},&H00FFFFFF,&H00101010,&H80101010,-1,0,0,0,100,100,0,0,{border},{outline},1,2,{round(width*.1)},{round(width*.1)},{margin},1
[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
'''
    def timestamp(t):
        cs = round(t * 100)
        return f'{cs//360000:01}:{cs//6000%60:02}:{cs//100%60:02}.{cs%100:02}'
    draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    events = []
    for item in items:
        # Disable untrusted ASS overrides; plain SRT preserves the original spelling.
        text = item['text'].replace('\\', '＼').replace('{', '｛').replace('}', '｝')
        for size in range(round(min(width * .052, height * .06)), 5, -1):
            font = ImageFont.truetype(FONT, size)
            content = wrap(text, font, width*.78)
            box = draw.multiline_textbbox((0, 0), content, font=font, spacing=round(size*.2), stroke_width=outline)
            if box[2]-box[0] <= width*.8 and box[3]-box[1] <= height*.24:
                break
        else:
            raise ValueError('A caption is too long to fit safely. Split it into shorter captions.')
        content = content.replace('\n', r'\N')
        events.append(f"Dialogue: 0,{timestamp(item['start'])},{timestamp(item['end'])},Default,,0,0,0,,{{\\fs{size}}}{content}")
    path.write_text(header + '\n'.join(events))
    return f'subtitles={path}'
