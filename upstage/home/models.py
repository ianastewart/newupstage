from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models, transaction
from django.urls import reverse

hex_colour = RegexValidator(r"^#[0-9a-fA-F]{6}$", "Enter a colour as #rrggbb, e.g. #7a1f2b.")


class WebPage(models.Model):
    """A web page built from a sequence of blocks."""

    title = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    background_colour = models.CharField(
        max_length=7, blank=True, validators=[hex_colour], help_text="#rrggbb; leave blank for the theme's colour."
    )
    blocks = models.ManyToManyField("Block", through="PageBlock", related_name="pages", blank=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("webpage", args=[self.slug])

    def page_blocks(self):
        """The page's blocks in order, as PageBlocks (each has .block and .position)."""
        return self.pageblock_set.select_related("block__image", "block__production").order_by("position", "id")

    def add_block(self, block):
        """Put a block at the end of the page."""
        last = self.pageblock_set.aggregate(last=models.Max("position"))["last"] or 0
        return PageBlock.objects.create(page=self, block=block, position=last + 1)

    def move_block(self, page_block_id, offset):
        """Move one of the page's blocks up (offset -1) or down (+1); positions end up as 1, 2, 3..."""
        with transaction.atomic():
            order = list(self.pageblock_set.select_for_update().order_by("position", "id"))
            index = next((i for i, pb in enumerate(order) if pb.pk == page_block_id), None)
            if index is None or not 0 <= index + offset < len(order):
                return
            order[index], order[index + offset] = order[index + offset], order[index]
            self._renumber(order)

    def remove_block(self, page_block_id):
        """Take a block off the page (the block itself is kept: other pages may use it)."""
        with transaction.atomic():
            self.pageblock_set.filter(pk=page_block_id).delete()
            self._renumber(list(self.pageblock_set.order_by("position", "id")))

    @staticmethod
    def _renumber(page_blocks):
        for position, page_block in enumerate(page_blocks, start=1):
            page_block.position = position
        PageBlock.objects.bulk_update(page_blocks, ["position"])


class Block(models.Model):
    """A piece of page content. The same block can appear on several pages."""

    class BlockType(models.TextChoices):
        TEXT = "text", "Text"
        IMAGE = "image", "Image"
        TEXT_IMAGE = "text_image", "Text and image"
        CAST = "cast", "Cast list"
        HERO_IMAGE = "hero_image", "Hero image"

    class ImageSize(models.TextChoices):
        SMALL = "small", "Small"
        MEDIUM = "medium", "Medium"
        LARGE = "large", "Large"
        FULL = "full", "Full width"

    class Layout(models.TextChoices):
        TEXT_LEFT = "text_left", "Text left, image right"
        IMAGE_LEFT = "image_left", "Image left, text right"
        IMAGE_TOP = "image_top", "Image top, text bottom"

    # The template fragment that renders each type of block.
    TEMPLATES = {
        BlockType.TEXT: "home/blocks/text.html",
        BlockType.IMAGE: "home/blocks/image.html",
        BlockType.TEXT_IMAGE: "home/blocks/text_image.html",
        BlockType.CAST: "home/blocks/cast.html",
        BlockType.HERO_IMAGE: "home/blocks/hero_image.html",
    }

    name = models.CharField(max_length=255, help_text="Identifies the block when adding it to pages.")
    block_type = models.CharField(max_length=20, choices=BlockType.choices, default=BlockType.TEXT)
    title = models.CharField(max_length=255, blank=True)
    subtitle = models.CharField(max_length=255, blank=True)
    text = models.TextField(blank=True, help_text="HTML. Used by text, text and image, and hero image (optional) blocks.")
    background_colour = models.CharField(
        max_length=7, blank=True, validators=[hex_colour], help_text="#rrggbb; leave blank for the theme's colour."
    )
    text_colour = models.CharField(
        max_length=7, blank=True, validators=[hex_colour], help_text="#rrggbb; leave blank for the theme's colour."
    )
    image = models.ForeignKey(
        "backstage.Image", null=True, blank=True, on_delete=models.SET_NULL, related_name="blocks"
    )
    image_size = models.CharField(max_length=10, choices=ImageSize.choices, default=ImageSize.MEDIUM)
    layout = models.CharField(
        max_length=20, choices=Layout.choices, default=Layout.TEXT_LEFT,
        help_text="Used by text and image, and cast list, blocks (the cast list takes the text's place).",
    )
    production = models.ForeignKey(
        "backstage.Production", null=True, blank=True, on_delete=models.SET_NULL, related_name="blocks",
        help_text="Cast list blocks show this production's cast (and its default image if no image is chosen).",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_block_type_display()})"

    @property
    def template(self):
        return self.TEMPLATES[self.block_type]

    @property
    def has_text(self):
        return self.block_type in (self.BlockType.TEXT, self.BlockType.TEXT_IMAGE)

    @property
    def has_image(self):
        return self.block_type in (
            self.BlockType.IMAGE, self.BlockType.TEXT_IMAGE, self.BlockType.CAST, self.BlockType.HERO_IMAGE,
        )

    @property
    def display_image(self):
        """The image to show: the block's own, or for a cast list, the production's default image."""
        if self.image_id or self.block_type != self.BlockType.CAST or not self.production_id:
            return self.image
        default = self.production.default_image
        return default.image if default else None

    @property
    def heading(self):
        """The title to show: the block's own, or for a cast list, the production's title."""
        if self.title or self.block_type != self.BlockType.CAST or not self.production_id:
            return self.title
        return self.production.title

    def cast_members(self):
        """For a cast list: the production's characters and actors, in the order they were added."""
        if not self.production_id:
            return []
        return self.production.cast.select_related("actor").order_by("id")

    def clean(self):
        errors = {}
        if self.has_text and not self.text.strip():
            errors["text"] = "This type of block needs some text."
        if self.block_type == self.BlockType.CAST:
            if not self.production_id:
                errors["production"] = "A cast list block needs a production."
            elif not self.display_image:
                errors["image"] = "Choose an image: this production has no default image to use."
        elif self.has_image and not self.image_id:
            errors["image"] = "This type of block needs an image."
        if errors:
            raise ValidationError(errors)


class PageBlock(models.Model):
    """A block's place on a page: blocks are shown in order of position."""

    page = models.ForeignKey(WebPage, on_delete=models.CASCADE)
    block = models.ForeignKey(Block, on_delete=models.CASCADE)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return f"{self.page}: {self.position}. {self.block}"
