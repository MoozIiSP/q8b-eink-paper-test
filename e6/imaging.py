"""Six-color conversion. RGB palette is illustrative, not panel calibration."""
import io
import warnings
from PIL import Image, ImageOps, UnidentifiedImageError
from .panel import WIDTH, HEIGHT, validate_frame

RGB = ((0, 0, 0), (255, 255, 255), (255, 255, 0),
       (255, 0, 0), (0, 0, 255), (0, 255, 0))
CODES = (0, 1, 2, 3, 5, 6)
Image.MAX_IMAGE_PIXELS = 16_000_000


def convert(raw, algorithm='floyd-steinberg', fit='contain'):
    if algorithm not in ('none', 'floyd-steinberg') or fit not in ('contain', 'cover'):
        raise ValueError('不支持的图像处理选项')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in ('PNG', 'JPEG', 'WEBP'):
                    raise ValueError('请上传 PNG、JPEG 或 WebP 图片')
                source.load()
                image = ImageOps.exif_transpose(source).convert('RGBA')
        white = Image.new('RGBA', image.size, 'white')
        image = Image.alpha_composite(white, image).convert('RGB')
        if fit == 'cover':
            image = ImageOps.fit(image, (WIDTH, HEIGHT), Image.Resampling.LANCZOS)
        else:
            image = ImageOps.pad(image, (WIDTH, HEIGHT), Image.Resampling.LANCZOS, color='white')
        palette = Image.new('P', (1, 1))
        # Fill all 256 entries with valid colors; duplicate entries map modulo 6.
        palette.putpalette([v for i in range(256) for v in RGB[i % 6]])
        quantized = image.quantize(palette=palette, dither=(Image.Dither.NONE if algorithm == 'none'
                                                          else Image.Dither.FLOYDSTEINBERG))
        codes = [CODES[index % 6] for index in quantized.tobytes()]
        frame = bytes((codes[i] << 4) | codes[i + 1] for i in range(0, len(codes), 2))
        validate_frame(frame)
        return frame, preview(frame)
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning,
            OSError) as error:
        raise ValueError('图片无法解码或超过 1600 万像素限制') from error


def preview(frame):
    validate_frame(frame)
    colors = dict(zip(CODES, RGB))
    pixels = bytearray()
    for byte in frame:
        pixels.extend(colors[byte >> 4])
        pixels.extend(colors[byte & 15])
    output = io.BytesIO()
    Image.frombytes('RGB', (WIDTH, HEIGHT), bytes(pixels)).save(output, 'PNG')
    return output.getvalue()
