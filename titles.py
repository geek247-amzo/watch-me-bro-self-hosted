"""Measured, safe-area title sprites and timed compositing. No AI requests."""
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'


def settings(overlay, duration):
    result = {}
    for name, choices, default in [('title_style', ('3d', 'flat'), '3d'),
                                   ('title_size', ('small', 'medium', 'large'), 'medium'),
                                   ('title_position', ('top', 'centre', 'bottom'), 'centre')]:
        value = overlay.get(name, default)
        if not isinstance(value, str) or value not in choices:
            raise ValueError('Choose a supported title look, size and position.')
        result[name] = value
    for name, default in [('headline_start', 0), ('headline_end', min(3, duration))]:
        value = overlay.get(name, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('Title timestamps must be finite seconds.')
        result[name] = float(value)
    if overlay.get('headline') and not 0 <= result['headline_start'] < result['headline_end'] <= duration:
        raise ValueError('Title start/end must fall within the chosen gameplay (before the opening screen).')
    return result


def wrap(text, font, width):
    """Pixel wrap, including long unbroken words; preserve all title characters."""
    lines = []
    for paragraph in text.splitlines() or ['']:
        line = ''
        for word in paragraph.split():
            candidate = (line + ' ' + word).strip()
            if font.getbbox(candidate)[2] <= width:
                line = candidate
                continue
            if line:
                lines.append(line)
                line = ''
            for char in word:
                if line and font.getbbox(line + char)[2] > width:
                    lines.append(line)
                    line = ''
                line += char
        if line:
            lines.append(line)
    return '\n'.join(lines)


def sprite(text, path, width, height, look, scale=1, color='#ffffff', box_height=.23):
    """Render to an actual pixel-measured transparent box, without truncation."""
    max_width, max_height = int(width * .80), int(height * box_height)
    base = round(min(width * .085, height * .073) * {'small': .78, 'medium': 1, 'large': 1.25}[look['title_size']] * scale)
    draw = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
    for size in range(max(10, base), 5, -1):
        font = ImageFont.truetype(FONT, size)
        depth = max(2, round(size * .12)) if look['title_style'] == '3d' else 0
        stroke = max(1, round(size * .035))
        padding = depth + stroke + 3
        content = wrap(text, font, max_width - padding * 2)
        bounds = draw.multiline_textbbox((0, 0), content, font=font, spacing=round(size * .20), stroke_width=stroke, align='center')
        if bounds[2] - bounds[0] + padding * 2 <= max_width and bounds[3] - bounds[1] + padding * 2 <= max_height:
            break
    else:
        raise ValueError('Title cannot fit safely. Shorten the words or choose a smaller title.')
    image = Image.new('RGBA', (math.ceil(bounds[2] - bounds[0] + padding * 2), math.ceil(bounds[3] - bounds[1] + padding * 2)))
    draw = ImageDraw.Draw(image)
    x, y = padding - bounds[0], padding - bounds[1]
    for offset in range(depth, 0, -1):
        draw.multiline_text((x+offset, y+offset), content, font=font, spacing=round(size*.20), align='center', fill='#18362f', stroke_width=stroke, stroke_fill='#07110f')
    draw.multiline_text((x, y), content, font=font, spacing=round(size*.20), align='center', fill=color, stroke_width=stroke, stroke_fill='#101914')
    image.save(path)
    return {'text': content, 'fontSize': size, 'width': image.width, 'height': image.height}


def layers(overlay, intro, gameplay, outro):
    """Positions are sprite centre points; times use the final exported timeline."""
    result = []
    brand = overlay.get('brand') or 'WATCH ME BRO'
    if intro:
        result += [(brand, 0, intro, .29, .65, '#d2f85b', .12),
                   (overlay.get('intro', ''), 0, intro, .48, 1, '#ffffff', .25)]
    if overlay.get('headline'):
        look = settings(overlay, gameplay)
        result.append((overlay['headline'], intro+look['headline_start'], intro+look['headline_end'],
                       {'top': .25, 'centre': .46, 'bottom': .68}[look['title_position']], 1, '#ffffff', .23))
    if outro:
        result += [('THANKS FOR WATCHING', intro+gameplay, intro+gameplay+outro, .29, .65, '#f3c85b', .12),
                   (overlay.get('cta', ''), intro+gameplay, intro+gameplay+outro, .47, 1, '#ffffff', .25),
                   (brand, intro+gameplay, intro+gameplay+outro, .67, .6, '#f3c85b', .12)]
    return [layer for layer in result if layer[0]]


def composite_titles(run, folder, video, overlay, width, height, intro, gameplay, outro):
    entries = layers(overlay, intro, gameplay, outro)
    if not entries:
        return
    look = settings(overlay, gameplay)
    args = ['ffmpeg', '-nostdin', '-y', '-v', 'error', '-threads', '1', '-filter_complex_threads', '1', '-i', str(video)]
    graph, current, files = [], '0:v', []
    for i, (text, start, end, y, scale, color, box_height) in enumerate(entries, 1):
        path = Path(folder) / f'title-layer-{i}.png'
        sprite(text, path, width, height, look, scale, color, box_height)
        files.append(path)
        args += ['-loop', '1', '-threads', '1', '-protocol_whitelist', 'file,pipe', '-format_whitelist', 'png_pipe', '-i', str(path)]
        graph.append(f"[{current}][{i}:v]overlay=x=(W-w)/2:y=H*{y}-h/2:enable='gte(t,{start})*lt(t,{end})':eof_action=repeat:shortest=1[title{i}]")
        current = f'title{i}'
    output = Path(folder) / 'titled.mp4'
    run(args + ['-filter_complex', ';'.join(graph), '-map', f'[{current}]', '-map', '0:a', '-t', str(intro+gameplay+outro), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '24', '-pix_fmt', 'yuv420p', '-threads', '1', '-c:a', 'copy', '-movflags', '+faststart', str(output)])
    output.replace(video)
    for path in files:
        path.unlink()  # Only generated scratch sprites from this render.
