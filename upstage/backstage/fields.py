"""A resizing image field that, for headshots, also makes the photo monochrome."""
import math
from io import BytesIO

from django.core.files.base import ContentFile
from django.db.models.fields.files import ImageFieldFile
from django_resized import ResizedImageField
from django_resized.forms import ResizedImageFieldFile
from PIL import Image as PILImage
from PIL import ImageOps

# Headshots are stored 400 pixels wide by 500 high, cropped from the centre, in black and white.
HEADSHOT_SIZE = [400, 500]
HEADSHOT_CROP = ["middle", "center"]  # vertically, then horizontally


CENTRE = (0.5, 0.5)


def clamp(value, default=0.5):
    """A number from 0 to 1 (anything else, or nothing, is the middle)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(number) else min(max(number, 0.0), 1.0)


def focal_crop_box(width, height, focal=CENTRE):
    """
    The part of a photo to keep, as (left, top, right, bottom) in pixels: the biggest window of the headshot's shape
    that fits in the photo, centred on the focus point where it can be (and kept inside the photo where it can't).

    `focal` is the focus point as fractions of the photo's width and height, (0, 0) being the top left and (1, 1) the
    bottom right. The upload page's preview does the same sum (see image_form.html).
    """
    ratio = HEADSHOT_SIZE[0] / HEADSHOT_SIZE[1]
    if width / height > ratio:  # wider than a headshot: all of the height, some of the width
        crop_width, crop_height = min(width, math.floor(height * ratio + 0.5)), height
    else:  # taller: all of the width, some of the height
        crop_width, crop_height = width, min(height, math.floor(width / ratio + 0.5))
    crop_width, crop_height = max(crop_width, 1), max(crop_height, 1)
    fx, fy = clamp(focal[0]), clamp(focal[1])
    left = math.floor(min(max(fx * width - crop_width / 2, 0), width - crop_width) + 0.5)
    top = math.floor(min(max(fy * height - crop_height / 2, 0), height - crop_height) + 0.5)
    return left, top, left + crop_width, top + crop_height


def monochrome(content, focal=CENTRE):
    """
    The uploaded photo in greyscale, in the same file format (as a ContentFile), cropped to the headshot's shape around
    the focus point (the middle, unless told otherwise). It is turned the right way up first, as a sideways phone photo
    says so in metadata that would otherwise be lost. A photo with transparency keeps it.
    """
    content.file.seek(0)
    with PILImage.open(content.file) as source:
        file_format = source.format
        photo = ImageOps.exif_transpose(source)
        has_alpha = photo.mode in ("RGBA", "LA", "PA") or "transparency" in photo.info
        photo = photo.convert("LA" if has_alpha else "L")
        photo = photo.crop(focal_crop_box(photo.width, photo.height, focal))
    options = {}
    if file_format == "JPEG":
        options = {"quality": 100, "subsampling": 0}  # the resize that follows is the one that compresses
    elif file_format == "WEBP":
        options = {"lossless": True}
    buffer = BytesIO()
    photo.save(buffer, format=file_format, **options)
    return ContentFile(buffer.getvalue())


class HeadshotResizedFieldFile(ResizedImageFieldFile):
    def save(self, name, content, save=True):
        # Only a headshot is changed; any other type of image is stored exactly as it was uploaded.
        if self.instance.image_type != "headshot":
            return ImageFieldFile.save(self, name, content, save)
        # The focus point the person chose when uploading (the middle if they did not).
        focal = getattr(self.instance, "focal_point", CENTRE)
        return super().save(name, monochrome(content, focal), save)


class HeadshotImageField(ResizedImageField):
    """
    An image that is changed when uploaded, if the image's type (its `image_type`) is Headshot: made black and
    white, scaled to cover 400 x 500 (width x height) and cropped from the centre. The photo's metadata (location,
    camera...) is removed; a sideways phone photo is turned the right way up first.
    """

    attr_class = HeadshotResizedFieldFile

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("size", HEADSHOT_SIZE)
        kwargs.setdefault("crop", HEADSHOT_CROP)
        kwargs.setdefault("quality", 90)
        kwargs.setdefault("keep_meta", False)
        super().__init__(*args, **kwargs)
