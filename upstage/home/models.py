import html as html_lib
import re

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models, transaction
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.html import strip_tags

link_url = RegexValidator(
    r"^(https?://\S+|/\S*)$", "Enter a full web address (https://...) or a path on this site, e.g. /page/about/."
)
hex_colour = RegexValidator(r"^#[0-9a-fA-F]{6}$", "Enter a colour as #rrggbb, e.g. #7a1f2b.")


_MEDIA_TAG = re.compile(r"<(?:img|iframe|video|audio|embed|object)\b", re.IGNORECASE)


def html_has_content(html):
    """
    Whether some rich text shows anything. The editor can leave "<p></p>", "<p><br></p>" or "<p>&nbsp;</p>" behind
    when the text is cleared: that is nothing to show. An image or video counts as something.
    """
    if not html:
        return False
    if _MEDIA_TAG.search(html):
        return True
    return bool(html_lib.unescape(strip_tags(html)).replace("\xa0", " ").strip())


def default_diary_shows():
    return ["upcoming_stage"]


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
        return (
            self.pageblock_set.select_related("block__image", "block__production")
            .prefetch_related("block__columns__image")
            .order_by("position", "id")
        )

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
        SPLIT = "split", "Split text and image"
        COLUMNS_2 = "columns_2", "Two columns"
        COLUMNS_3 = "columns_3", "Three columns"
        COLUMNS_4 = "columns_4", "Four columns"
        AUDITIONS = "auditions", "Auditions"
        PROMOTION = "promotion", "Promotion"
        DIARY = "diary", "Diary"

    class DiaryShow(models.TextChoices):
        RECENT_RADIO = "recent_radio", "Recent radio plays"
        UPCOMING_RADIO = "upcoming_radio", "Upcoming radio plays"
        UPCOMING_STAGE = "upcoming_stage", "Upcoming stage plays"
        AUDITIONS = "auditions", "Auditions"

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
        BlockType.SPLIT: "home/blocks/split.html",
        BlockType.COLUMNS_2: "home/blocks/columns.html",
        BlockType.COLUMNS_3: "home/blocks/columns.html",
        BlockType.COLUMNS_4: "home/blocks/columns.html",
        BlockType.AUDITIONS: "home/blocks/auditions.html",
        BlockType.PROMOTION: "home/blocks/promotion.html",
        BlockType.DIARY: "home/blocks/diary.html",
    }

    name = models.CharField(max_length=255, help_text="Identifies the block when adding it to pages.")
    block_type = models.CharField(max_length=20, choices=BlockType.choices, default=BlockType.TEXT)
    title = models.CharField(max_length=255, blank=True)
    subtitle = models.CharField(max_length=255, blank=True)
    text = models.TextField(blank=True, help_text="HTML. Used by text, text and image, hero image (optional) and auditions (optional) blocks.")
    background_colour = models.CharField(
        max_length=7, blank=True, validators=[hex_colour], help_text="#rrggbb; leave blank for the theme's colour."
    )
    text_colour = models.CharField(
        max_length=7, blank=True, validators=[hex_colour], help_text="#rrggbb; leave blank for the theme's colour."
    )
    image = models.ForeignKey(
        "backstage.Image", null=True, blank=True, on_delete=models.SET_NULL, related_name="blocks"
    )
    url = models.CharField(
        "Image link", max_length=500, blank=True, validators=[link_url],
        help_text="Where clicking the image goes: a web address, or a path on this site such as /page/about/. "
                  "Used by text and image, and split, blocks.",
    )
    image_size = models.CharField(max_length=10, choices=ImageSize.choices, default=ImageSize.MEDIUM)
    layout = models.CharField(
        max_length=20, choices=Layout.choices, default=Layout.TEXT_LEFT,
        help_text="Used by text and image, split, and cast list, blocks (the cast list takes the text's place).",
    )
    separate_columns = models.BooleanField(
        "Separate columns", default=False,
        help_text="Columns blocks: each column is its own card with a gap between, instead of sharing the block's card.",
    )
    flush_images = models.BooleanField(
        "Images with no margin", default=False,
        help_text="Columns blocks: images run to the edges of their card, with the text padded underneath. "
                  "For separate columns, or equal height columns (where the columns are in cards or boxes).",
    )
    match_image_heights = models.BooleanField(
        "Images the same height", default=False,
        help_text="Columns blocks: every image is as tall as the shortest one; the taller images are cropped to match.",
    )
    equal_height = models.BooleanField(
        "Equal height columns", default=False,
        help_text="Columns blocks: make all the columns as tall as the tallest one (they are drawn in boxes, unless separate).",
    )
    fade_in_seconds = models.FloatField(
        "Fade-in time (seconds)", default=5, validators=[MinValueValidator(0), MaxValueValidator(30)],
        help_text="Hero image blocks: how long the image, subtitle and text take to fade in. 0 for no fade.",
    )
    diary_shows = models.JSONField(
        "Show", default=default_diary_shows, blank=True,
        help_text="Diary blocks: which kinds of event to list (a list of DiaryShow values).",
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

    # How many columns each of the column block types has.
    COLUMN_COUNTS = {BlockType.COLUMNS_2: 2, BlockType.COLUMNS_3: 3, BlockType.COLUMNS_4: 4}
    MAX_COLUMNS = 4

    @property
    def column_count(self):
        """How many columns this type of block shows (0 if it isn't a columns block)."""
        return self.COLUMN_COUNTS.get(self.block_type, 0)

    def visible_columns(self):
        """The columns to show: the first few, as many as the type of block has."""
        return list(self.columns.all())[: self.column_count]

    def upcoming_auditions(self):
        """For an auditions block: the productions with an audition still to come (see home.auditions)."""
        from .auditions import upcoming_auditions

        return upcoming_auditions()

    def diary_productions(self):
        """For a diary block: the productions with a published event still to come (see home.diary)."""
        from .diary import diary_productions

        return diary_productions(self.diary_shows)

    @property
    def image_ratio(self):
        """
        For "images the same height": the CSS aspect-ratio ("400 / 300") of the shortest image among the columns shown.
        Using it for every image makes them all as tall as that one, as the columns are equally wide. Empty if the
        option is off, or no column has an image whose size can be read.
        """
        if not self.match_image_heights:
            return ""
        shortest = None  # (width, height) of the image with the smallest height for its width
        for column in self.visible_columns():
            if not column.image_id or not column.image.image:
                continue
            try:
                width, height = column.image.image.width, column.image.image.height
            except (OSError, ValueError):  # the file is missing or isn't an image
                continue
            if width and height and (shortest is None or height * shortest[0] < shortest[1] * width):
                shortest = (width, height)
        return f"{shortest[0]} / {shortest[1]}" if shortest else ""

    @property
    def has_visible_text(self):
        """Whether the block's text shows anything (an empty paragraph from the editor does not count)."""
        return html_has_content(self.text)

    @property
    def has_text(self):
        return self.block_type in (self.BlockType.TEXT, self.BlockType.TEXT_IMAGE, self.BlockType.SPLIT)

    @property
    def has_image(self):
        return self.block_type in (
            self.BlockType.IMAGE, self.BlockType.TEXT_IMAGE, self.BlockType.CAST, self.BlockType.HERO_IMAGE,
            self.BlockType.SPLIT,
        )

    @property
    def link_url(self):
        """Where clicking the image goes, for the types of block that link their image."""
        if self.block_type in (self.BlockType.TEXT_IMAGE, self.BlockType.SPLIT, self.BlockType.PROMOTION):
            return self.url
        return ""

    @cached_property
    def promotion(self):
        """For a promotion block: (the promotion image of the production of the next promoted event, or None; where to buy tickets, or "")."""
        from .promotions import next_promotion

        return next_promotion()

    @property
    def promotion_image(self):
        return self.promotion[0]

    @property
    def ticket_url(self):
        """For a promotion block: where to buy tickets for that event (empty if it has no ticket address)."""
        return self.promotion[1]

    @property
    def display_image(self):
        """The image to show: the block's own, or for a cast list, the production's default image."""
        if self.block_type == self.BlockType.PROMOTION:
            return self.promotion_image
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
        if self.has_text and not self.has_visible_text:
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


class BlockColumn(models.Model):
    """One column of a columns block: an image and some text, side by side with the block's other columns."""

    block = models.ForeignKey(Block, on_delete=models.CASCADE, related_name="columns")
    position = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=255, blank=True, help_text="Shown centred at the top of the column, above the image.")
    image = models.ForeignKey(
        "backstage.Image", null=True, blank=True, on_delete=models.SET_NULL, related_name="block_columns"
    )
    text = models.TextField(blank=True, help_text="HTML.")
    url = models.CharField(
        "Image link", max_length=500, blank=True, validators=[link_url],
        help_text="Where clicking the image goes: a web address, or a path on this site such as /page/about/.",
    )

    class Meta:
        ordering = ["position", "id"]

    @property
    def has_title(self):
        """Whether the column has a title with some text in it (spaces alone do not count)."""
        return bool(self.title.strip())

    @property
    def has_visible_text(self):
        return html_has_content(self.text)

    def __str__(self):
        return f"{self.block}: column {self.position + 1}"


class PageBlock(models.Model):
    """A block's place on a page: blocks are shown in order of position."""

    page = models.ForeignKey(WebPage, on_delete=models.CASCADE)
    block = models.ForeignKey(Block, on_delete=models.CASCADE)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return f"{self.page}: {self.position}. {self.block}"
