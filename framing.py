"""Validated normalised crop rectangles, shared by saved plans and FFmpeg exports."""
import math


def validate_crop(value):
    if not isinstance(value, dict) or value.get('mode') not in ['fit', 'crop']:
        raise ValueError('Choose whole-picture framing or a valid crop rectangle.')
    if value['mode'] == 'fit':
        return {'mode': 'fit'}
    clean = {'mode': 'crop'}
    for name in ['x', 'y', 'width', 'height']:
        number = value.get(name)
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
            raise ValueError('Crop coordinates must be finite numbers.')
        clean[name] = float(number)
    if not (0 <= clean['x'] <= 1 and 0 <= clean['y'] <= 1 and .01 <= clean['width'] <= 1 and .01 <= clean['height'] <= 1
            and clean['x']+clean['width'] <= 1+1e-9 and clean['y']+clean['height'] <= 1+1e-9):
        raise ValueError('Keep the crop inside the original picture (minimum 1% per side).')
    return clean


def geometry(crop, width, height, vertical):
    contain = f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2'
    if crop is None:
        return f'scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}' if vertical else contain
    crop = validate_crop(crop)
    if crop['mode'] == 'fit':
        return contain
    # Even pixel rounding is deterministic for subsampled codecs. Clamp x/y after rounding.
    return (f"crop=w='max(2,trunc(iw*{crop['width']:.12f}/2)*2)':h='max(2,trunc(ih*{crop['height']:.12f}/2)*2)'"
            f":x='min(iw-ow,max(0,trunc(iw*{crop['x']:.12f}/2)*2))':y='min(ih-oh,max(0,trunc(ih*{crop['y']:.12f}/2)*2))',"+contain)
