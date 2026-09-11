"""Landscape photo processing with explicit conversion to reference scan order."""
import io
import math
import warnings
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, UnidentifiedImageError
from .panel import WIDTH as NATIVE_WIDTH, HEIGHT as NATIVE_HEIGHT, validate_frame

WIDTH, HEIGHT = 720, 480
RGB = ((0, 0, 0), (255, 255, 255), (255, 255, 0),
       (255, 0, 0), (0, 0, 255), (0, 255, 0))
CODES = (0, 1, 2, 3, 5, 6)
ALGORITHMS = ('none', 'floyd-steinberg', 'atkinson', 'bayer')
Image.MAX_IMAGE_PIXELS = 16_000_000


def number(value, name, low, high):
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{name} 参数无效') from None
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} 必须在 {low}–{high} 之间')
    return value


def quantize(image, algorithm, strength):
    palette = Image.new('P', (1, 1))
    palette.putpalette([v for i in range(256) for v in RGB[i % 6]])
    if algorithm in ('none', 'floyd-steinberg'):
        result = image.quantize(palette=palette, dither=(Image.Dither.NONE if algorithm == 'none'
                                                        else Image.Dither.FLOYDSTEINBERG))
        return Image.frombytes('L', image.size, bytes(CODES[i % 6] for i in result.tobytes()))
    width, height = image.size
    raw = image.tobytes()
    pixels = list(zip(raw[0::3], raw[1::3], raw[2::3]))
    result = bytearray(width * height)
    cache = {}

    def nearest(values):
        # Integer RGB cache, bounded to this image. Avoid quantization bias at pure colors.
        key = tuple(max(0, min(255, round(v))) for v in values)
        if key not in cache:
            cache[key] = min(range(6), key=lambda i: sum((key[c] - RGB[i][c]) ** 2 for c in range(3)))
        return cache[key]

    if algorithm == 'bayer':
        matrix = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))
        for y in range(height):
            for x in range(width):
                offset = ((matrix[y % 4][x % 4] + .5) / 16 - .5) * 128 * strength
                result[y * width + x] = CODES[nearest([v + offset for v in pixels[y * width + x]])]
    else:
        # Serpentine Atkinson: distribute 6/8 error; alternate rows to reduce directional streaks.
        errors = [[[0., 0., 0.] for _ in range(width)] for _ in range(3)]
        for y in range(height):
            direction = 1 if y % 2 == 0 else -1
            row = errors[y % 3]
            for x in (range(width) if direction == 1 else range(width - 1, -1, -1)):
                values = [max(0, min(255, pixels[y * width + x][c] + row[x][c])) for c in range(3)]
                index = nearest(values)
                result[y * width + x] = CODES[index]
                error = [(values[c] - RGB[index][c]) * strength / 8 for c in range(3)]
                for dx, dy in ((direction, 0), (2 * direction, 0), (-direction, 1),
                               (0, 1), (direction, 1), (0, 2)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < width and ny < height:
                        target = errors[ny % 3][nx]
                        for c in range(3):
                            target[c] += error[c]
            errors[y % 3] = [[0., 0., 0.] for _ in range(width)]
    return Image.frombytes('L', image.size, bytes(result))


def pack(codes, orientation='landscape'):
    if orientation == 'landscape':
        codes = codes.transpose(Image.Transpose.ROTATE_90)
    elif orientation != 'portrait':
        raise ValueError('不支持的显示方向')
    if codes.size != (NATIVE_WIDTH, NATIVE_HEIGHT):
        raise ValueError('图像尺寸与原始帧不匹配')
    values = codes.tobytes()
    frame = bytes((values[i] << 4) | values[i + 1] for i in range(0, len(values), 2))
    validate_frame(frame)
    return frame


def convert(raw, algorithm='floyd-steinberg', fit='contain', *, orientation='landscape',
            enhance='none', brightness=1, contrast=1, saturation=1, gamma=1, strength=1):
    if algorithm not in ALGORITHMS or fit not in ('contain', 'cover'):
        raise ValueError('不支持的图像处理选项')
    if orientation not in ('landscape', 'portrait') or enhance not in ('none', 'photo', 'soft'):
        raise ValueError('不支持的方向或增强模式')
    brightness = number(brightness, '亮度', .5, 1.5)
    contrast = number(contrast, '对比度', .5, 1.5)
    saturation = number(saturation, '饱和度', 0, 2)
    gamma = number(gamma, '中间调', .5, 2)
    strength = number(strength, '抖动强度', 0, 1)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in ('PNG', 'JPEG', 'WEBP'):
                    raise ValueError('请上传 PNG、JPEG 或 WebP 图片')
                source.load()
                image = ImageOps.exif_transpose(source).convert('RGBA')
        image = Image.alpha_composite(Image.new('RGBA', image.size, 'white'), image).convert('RGB')
        size = (WIDTH, HEIGHT) if orientation == 'landscape' else (NATIVE_WIDTH, NATIVE_HEIGHT)
        if fit == 'cover':
            image = ImageOps.fit(image, size, Image.Resampling.LANCZOS)
        else:
            image = ImageOps.contain(image, size, Image.Resampling.LANCZOS)
        # Enhance content before adding white margins.
        if enhance == 'photo':
            image = ImageOps.autocontrast(image, cutoff=.5, preserve_tone=True)
            image = ImageEnhance.Color(image).enhance(1.12)
            image = image.filter(ImageFilter.UnsharpMask(radius=1, percent=110, threshold=3))
        elif enhance == 'soft':
            image = image.filter(ImageFilter.MedianFilter(3))
            image = ImageEnhance.Contrast(image).enhance(.95)
        image = ImageEnhance.Brightness(image).enhance(brightness)
        image = ImageEnhance.Contrast(image).enhance(contrast)
        image = ImageEnhance.Color(image).enhance(saturation)
        if gamma != 1:
            image = image.point([round(255 * (v / 255) ** (1 / gamma)) for v in range(256)] * 3)
        codes = quantize(image, algorithm, strength)
        canvas = Image.new('L', size, 1)
        canvas.paste(codes, ((size[0] - codes.width) // 2, (size[1] - codes.height) // 2))
        frame = pack(canvas, orientation)
        return frame, preview(frame, orientation)
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning,
            OSError) as error:
        raise ValueError('图片无法解码或超过 1600 万像素限制') from error


def preview(frame, orientation='landscape'):
    validate_frame(frame)
    colors = dict(zip(CODES, RGB))
    pixels = bytearray()
    for byte in frame:
        pixels.extend(colors[byte >> 4])
        pixels.extend(colors[byte & 15])
    image = Image.frombytes('RGB', (NATIVE_WIDTH, NATIVE_HEIGHT), bytes(pixels))
    if orientation == 'landscape':
        image = image.transpose(Image.Transpose.ROTATE_270)
    elif orientation != 'portrait':
        raise ValueError('不支持的显示方向')
    output = io.BytesIO()
    image.save(output, 'PNG')
    return output.getvalue()
