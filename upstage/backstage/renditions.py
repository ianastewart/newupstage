"""
Resized copies of library images for a production's public gallery.

The original is never changed: a smaller JPEG is stored beside it, in renditions/gallery/, named for the image and for
the original's file so that a replaced file gets a new copy. A portrait photo is shrunk to fit 600 x 800 and a landscape
one to fit 1200 x 800, which is sharp on a screen with twice the pixels at the largest size the gallery shows them
(a third of the page across for a portrait, two thirds for a landscape). Photos are never enlarged.
"""
import hashlib
import logging

from django.core.files.base import ContentFile
from PIL import Image as PILImage
from PIL import ImageOps

logger = logging.getLogger(__name__)

PORTRAIT_BOX = (600, 800)
LANDSCAPE_BOX = (1200, 800)
# A photo this much wider than it is tall is landscape; squarer ones are shown as portraits.
LANDSCAPE_RATIO = 1.15
JPEG_QUALITY = 82
FOLDER = "renditions/gallery"

PORTRAIT = "portrait"
LANDSCAPE = "landscape"
_SUFFIX = {PORTRAIT: "p", LANDSCAPE: "l"}


def orientation(width, height):
    """`LANDSCAPE` for a photo clearly wider than it is tall, else `PORTRAIT`."""
    return LANDSCAPE if width >= height * LANDSCAPE_RATIO else PORTRAIT


def rendition_stem(image):
    """The start of the copy's name: the image's id and a short code of its file's name (a new file, a new copy)."""
    code = hashlib.md5(image.image.name.encode("utf-8")).hexdigest()[:8]
    return f"{FOLDER}/{image.pk}-{code}"


def existing_rendition(image):
    """(name, orientation) of the copy already made for this image, or None."""
    storage = image.image.storage
    stem = rendition_stem(image)
    for kind, suffix in _SUFFIX.items():
        name = f"{stem}-{suffix}.jpg"
        if storage.exists(name):
            return name, kind
    return None


def make_rendition(image):
    """Make (or find) the resized copy of an image; returns (name, orientation), or None if the file can't be read."""
    found = existing_rendition(image)
    if found:
        return found
    storage = image.image.storage
    try:
        with storage.open(image.image.name) as source:
            photo = PILImage.open(source)
            photo.load()
    except (OSError, ValueError, FileNotFoundError):
        return None
    photo = ImageOps.exif_transpose(photo)  # a phone photo's rotation, so the shape is the one people see
    kind = orientation(*photo.size)
    if photo.mode in ("RGBA", "LA", "P"):
        photo = photo.convert("RGBA")
        flat = PILImage.new("RGB", photo.size, (255, 255, 255))  # transparent parts become white
        flat.paste(photo, mask=photo.getchannel("A"))
        photo = flat
    elif photo.mode != "RGB":
        photo = photo.convert("RGB")
    photo.thumbnail(LANDSCAPE_BOX if kind == LANDSCAPE else PORTRAIT_BOX, PILImage.Resampling.LANCZOS)
    from io import BytesIO

    buffer = BytesIO()
    photo.save(buffer, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    name = storage.save(f"{rendition_stem(image)}-{_SUFFIX[kind]}.jpg", ContentFile(buffer.getvalue()))
    return name, kind


def gallery_item(image):
    """
    What the public gallery needs for one image: the resized copy's address, the original's, the shape and the alt text.
    None if the image has no readable file.
    """
    if not image.image:
        return None
    made = make_rendition(image)
    if not made:
        return None
    name, kind = made
    return {
        "image": image,
        "url": image.image.storage.url(name),
        "full_url": image.image.url,
        "orientation": kind,
        "alt": image.description,
    }


def gallery_items(images):
    """`gallery_item` for each image, leaving out those whose file is missing. A fault in one never stops the page."""
    items = []
    for image in images:
        try:
            item = gallery_item(image)
        except Exception:  # noqa: BLE001 - a broken picture must not break the page
            logger.exception("Gallery copy of image %s failed", image.pk)
            item = None
        if item:
            items.append(item)
    return items
