from datetime import timedelta

from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from backstage.models import Cast, Image, Person, Production, ProductionImage, ProductionTeam, Role


class RadioArchiveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        # Only the image's file name is stored: nothing is written to the media folder.
        cls.image = Image.objects.create(description="Cover", image="images/test-cover.jpg")
        cls.old = Production.objects.create(title="Old Play", broadcast_datetime=now - timedelta(days=100))
        cls.new = Production.objects.create(title="New Play", broadcast_datetime=now - timedelta(days=1))
        cls.undated = Production.objects.create(title="Undated Play")
        cls.stage = Production.objects.create(title="A Stage Play", type=Production.ProductionType.STAGE)
        ProductionImage.objects.create(production=cls.new, image=cls.image, is_default=True)

        writer, director = Role.objects.get_or_create(name="Writer")[0], Role.objects.get_or_create(name="Director")[0]
        ProductionTeam.objects.create(production=cls.new, role=writer, person=Person.objects.create(first_name="Wendy", last_name="Writer"))
        ProductionTeam.objects.create(production=cls.new, role=director, person=Person.objects.create(first_name="Dan", last_name="Director"))
        Cast.objects.create(production=cls.new, character_name="Hamlet", actor=Person.objects.create(first_name="Ann", last_name="Actor"))

    def test_archive_is_public_lists_radio_plays_latest_first(self):
        response = self.client.get(reverse("radio-archive"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "A Stage Play")
        titles = [play.title for play in response.context["plays"]]
        self.assertEqual(titles, ["New Play", "Old Play", "Undated Play"])
        self.assertContains(response, "images/test-cover.jpg")

    def test_detail_shows_image_writer_team_and_cast(self):
        response = self.client.get(reverse("radio-play", args=[self.new.pk]))
        self.assertEqual(response.status_code, 200)
        for text in ("images/test-cover.jpg", "Wendy Writer", "Dan Director", "Director", "Hamlet", "Ann Actor"):
            self.assertContains(response, text)
        # The writer has their own heading, so isn't repeated as a team role.
        self.assertEqual([member.role.name for member in response.context["team"]], ["Director"])

    def test_detail_404_for_other_types(self):
        self.assertEqual(self.client.get(reverse("radio-play", args=[self.stage.pk])).status_code, 404)

    def test_play_without_image_still_renders(self):
        self.assertEqual(self.client.get(reverse("radio-play", args=[self.old.pk])).status_code, 200)

    def test_listen_now_button_only_when_there_is_a_listen_url(self):
        self.assertNotContains(self.client.get(reverse("radio-play", args=[self.new.pk])), "Listen now")
        self.new.listen_url = "https://example.com/listen"
        self.new.save()
        response = self.client.get(reverse("radio-play", args=[self.new.pk]))
        self.assertContains(response, "Listen now")
        self.assertContains(response, 'href="https://example.com/listen"')


class PublicNavTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from home.models import WebPage

        # The home view shows the page with the slug "home".
        WebPage.objects.create(title="Home", slug="home")

    def test_public_pages_have_the_public_navbar(self):
        for name in ("home", "auditions", "public-actors", "radio-archive"):
            response = self.client.get(reverse(name))
            for link in (reverse("home"), reverse("auditions"), reverse("public-actors")):
                self.assertContains(response, f'href="{link}"', msg_prefix=name)
            # None of the backstage links.
            self.assertNotContains(response, reverse("production-list"), msg_prefix=name)
            self.assertNotContains(response, reverse("page-list"), msg_prefix=name)

    def test_current_page_is_highlighted(self):
        response = self.client.get(reverse("auditions"))
        self.assertContains(response, f'<a href="{reverse("auditions")}" class="menu-active">', count=2)

    def test_backstage_pages_keep_the_backstage_navbar(self):
        from accounts.models import CustomUser

        self.client.force_login(CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!"))
        response = self.client.get(reverse("production-list"))
        self.assertContains(response, f'href="{reverse("page-list")}"')

    def test_backstage_link_only_when_logged_in(self):
        from accounts.models import CustomUser

        self.assertNotContains(self.client.get(reverse("home")), ">Backstage<")
        self.client.force_login(CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!"))
        response = self.client.get(reverse("home"))
        self.assertContains(response, f'<a href="{reverse("production-list")}">Backstage</a>', count=2)

    def test_radio_plays_link_is_highlighted_on_the_archive(self):
        response = self.client.get(reverse("radio-archive"))
        self.assertContains(response, f'<a href="{reverse("radio-archive")}" class="menu-active">Radio plays</a>', count=2)
        self.assertContains(self.client.get(reverse("home")), f'<a href="{reverse("radio-archive")}">Radio plays</a>', count=2)


class ColourSwatchTests(TestCase):
    def test_colour_fields_get_swatches(self):
        from accounts.models import CustomUser
        from home.models import WebPage

        self.client.force_login(CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!"))
        page = WebPage.objects.create(title="About", slug="about")
        for url, fields in (
            (reverse("page-create"), 1),
            (reverse("page-edit", args=[page.pk]), 1),
            (reverse("block-create", args=[page.pk]), 2),
        ):
            response = self.client.get(url)
            # One attribute per colour field, plus the script's own selector.
            self.assertContains(response, "data-swatches", count=fields + 1, msg_prefix=url)
            self.assertContains(response, "Theatre red", msg_prefix=url)


class StylesheetVersionTests(TestCase):
    def test_the_stylesheet_address_changes_when_the_file_does(self):
        import re

        from home.models import WebPage

        WebPage.objects.create(title="Home", slug="home")
        match = re.search(r'output\.css\?v=(\d+)"', self.client.get(reverse("home")).content.decode())
        self.assertIsNotNone(match)
        self.assertGreater(int(match.group(1)), 0)  # the file's modification time


class ColumnsBlockTests(TestCase):
    PASSWORD = "a-Long-pa55word!"

    @classmethod
    def setUpTestData(cls):
        from accounts.models import CustomUser
        from home.models import WebPage

        cls.user = CustomUser.objects.create_user("member", "member@example.com", cls.PASSWORD)
        cls.page = WebPage.objects.create(title="About", slug="about")
        # Only the file names are stored: nothing is written to the media folder.
        cls.images = [Image.objects.create(description=f"Pic {n}", image=f"images/test-col-{n}.jpg") for n in range(1, 5)]

    def setUp(self):
        self.client.force_login(self.user)

    def post(self, block_type, columns, name="Cols", **extra):
        """Post the new block form: `columns` is a list of (image, text, url), up to four."""
        data = {
            "name": name, "block_type": block_type, "title": "Our team", "subtitle": "", "text": "", "layout": "text_left",
            "image_size": "medium", "background_colour": "", "text_colour": "", "url": "",
            "col-TOTAL_FORMS": "4", "col-INITIAL_FORMS": "0", "col-MIN_NUM_FORMS": "0", "col-MAX_NUM_FORMS": "4",
        }
        for index in range(4):
            image, text, url = columns[index] if index < len(columns) else (None, "", "")
            data[f"col-{index}-image"] = image.pk if image else ""
            data[f"col-{index}-text"] = text
            data[f"col-{index}-url"] = url
        data.update(extra)
        return self.client.post(reverse("block-create", args=[self.page.pk]), data)

    def test_the_form_has_room_for_four_columns(self):
        response = self.client.get(reverse("block-create", args=[self.page.pk]))
        self.assertEqual(len(response.context["formset"].forms), 4)
        for number in (1, 2, 3, 4):
            self.assertContains(response, f"Column {number}")

    def test_create_a_two_column_block(self):
        from home.models import Block

        response = self.post("columns_2", [(self.images[0], "<p>One</p>", ""), (self.images[1], "<p>Two</p>", "/page/two/")])
        self.assertEqual(response.status_code, 302)
        block = Block.objects.get(name="Cols")
        self.assertEqual(block.column_count, 2)
        self.assertEqual([(c.position, c.text) for c in block.columns.all()], [(0, "<p>One</p>"), (1, "<p>Two</p>")])
        self.assertEqual(block.columns.all()[1].url, "/page/two/")
        self.assertEqual(self.page.pageblock_set.count(), 1)

    def test_each_column_the_type_needs_must_have_something_in_it(self):
        from home.models import Block

        # A three column block with only two columns filled in.
        response = self.post("columns_3", [(self.images[0], "<p>One</p>", ""), (None, "<p>Two</p>", "")])
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This column needs an image, a title or some text.")
        self.assertFalse(Block.objects.filter(name="Cols").exists())

    def test_extra_columns_beyond_the_type_are_not_required(self):
        from home.models import Block

        response = self.post("columns_2", [(self.images[0], "", ""), (None, "<p>Two</p>", "")])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Block.objects.get(name="Cols").columns.count(), 2)

    def test_blocks_of_other_types_ignore_the_columns(self):
        from home.models import Block

        response = self.post("text", [(self.images[0], "<p>Stray</p>", "")], text="<p>Hello</p>")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Block.objects.get(name="Cols").columns.count(), 0)

    def test_a_bad_link_is_rejected(self):
        response = self.post("columns_2", [(self.images[0], "x", "javascript:alert(1)"), (self.images[1], "y", "")])
        self.assertEqual(response.status_code, 200)

    def test_show_two_three_and_four_columns(self):
        from home.models import Block, BlockColumn

        classes = {"columns_2": "md:grid-cols-2", "columns_3": "md:grid-cols-3", "columns_4": "lg:grid-cols-4"}
        for block_type, count in (("columns_2", 2), ("columns_3", 3), ("columns_4", 4)):
            block = Block.objects.create(name=block_type, block_type=block_type, title="Heading")
            for index in range(4):  # one more than any type shows, or the maximum
                BlockColumn.objects.create(block=block, position=index, image=self.images[index], text=f"<p>Text {index + 1}</p>")
            html = render_to_string(block.template, {"block": block})
            self.assertIn(classes[block_type], html)
            self.assertEqual(html.count("<img"), count)
            for index in range(4):
                self.assertEqual(f"Text {index + 1}" in html, index < count, (block_type, index))
            self.assertIn("Heading", html)

    def test_columns_stack_on_phones(self):
        from home.models import Block, BlockColumn

        block = Block.objects.create(name="Stack", block_type="columns_3")
        for index in range(3):
            BlockColumn.objects.create(block=block, position=index, text=f"<p>{index}</p>")
        html = render_to_string(block.template, {"block": block})
        # The columns are side by side only from the md breakpoint up: there is no unprefixed grid-cols class.
        self.assertIn("md:grid-cols-3", html)
        self.assertNotRegex(html, r"(?<![:\w-])grid-cols-\d")

    def test_the_image_link_is_used(self):
        from home.models import Block, BlockColumn

        block = Block.objects.create(name="Linked", block_type="columns_2")
        BlockColumn.objects.create(block=block, position=0, image=self.images[0], url="https://example.com/a")
        BlockColumn.objects.create(block=block, position=1, image=self.images[1])
        html = render_to_string(block.template, {"block": block})
        self.assertEqual(html.count('href="https://example.com/a"'), 1)

    def test_edit_keeps_columns_in_order_and_removes_emptied_ones(self):
        from home.models import Block

        self.post("columns_3", [(self.images[0], "<p>A</p>", ""), (self.images[1], "<p>B</p>", ""), (self.images[2], "<p>C</p>", "")])
        block = Block.objects.get(name="Cols")
        columns = list(block.columns.all())
        data = {
            "name": "Cols", "block_type": "columns_2", "title": "Our team", "subtitle": "", "text": "", "layout": "text_left",
            "image_size": "medium", "background_colour": "", "text_colour": "", "url": "",
            "col-TOTAL_FORMS": "4", "col-INITIAL_FORMS": "3", "col-MIN_NUM_FORMS": "0", "col-MAX_NUM_FORMS": "4",
        }
        for index, column in enumerate(columns):
            data[f"col-{index}-id"] = column.pk
            data[f"col-{index}-block"] = block.pk
            data[f"col-{index}-image"] = column.image_id
            data[f"col-{index}-text"] = f"<p>{'ABC'[index]}2</p>" if index < 2 else ""  # the third is emptied...
            data[f"col-{index}-url"] = ""
        data["col-2-image"] = ""  # ...completely
        data["col-3-image"], data["col-3-text"], data["col-3-url"] = "", "", ""
        response = self.client.post(reverse("block-edit", args=[self.page.pk, block.pk]), data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual([c.text for c in block.columns.all()], ["<p>A2</p>", "<p>B2</p>"])
        self.assertEqual(block.columns.count(), 2)

    def test_the_edit_form_shows_the_saved_columns(self):
        from home.models import Block, BlockColumn

        block = Block.objects.create(name="Saved", block_type="columns_2")
        BlockColumn.objects.create(block=block, position=0, text="<p>First column</p>")
        response = self.client.get(reverse("block-edit", args=[self.page.pk, block.pk]))
        self.assertContains(response, "First column")
        self.assertEqual(len(response.context["formset"].forms), 4)

    def test_page_shows_a_columns_block(self):
        from home.models import Block, BlockColumn, WebPage

        home = WebPage.objects.create(title="Home", slug="home")
        block = Block.objects.create(name="C", block_type="columns_2", title="Meet us")
        BlockColumn.objects.create(block=block, position=0, text="<p>Left</p>")
        BlockColumn.objects.create(block=block, position=1, text="<p>Right</p>")
        self.page.add_block(block)
        response = self.client.get(reverse("webpage", args=["about"]))
        self.assertContains(response, "Left")
        self.assertContains(response, "Right")

    def test_equal_height_draws_each_column_in_a_box(self):
        from home.models import Block, BlockColumn

        for equal in (False, True):
            block = Block.objects.create(name=f"Equal {equal}", block_type="columns_3", equal_height=equal)
            for index, text in enumerate(("<p>Short</p>", "<p>" + "Much longer text. " * 30 + "</p>", "<p>Medium text here</p>")):
                BlockColumn.objects.create(block=block, position=index, text=text)
            html = render_to_string(block.template, {"block": block})
            # One box per column when on, none when off.
            self.assertEqual(html.count("border-current/25"), 3 if equal else 0, equal)
            self.assertEqual(html.count(" h-full "), 3 if equal else 0, equal)

    def test_the_equal_height_option_is_saved_and_only_offered_for_columns(self):
        from home.models import Block

        response = self.post("columns_2", [(self.images[0], "<p>One</p>", ""), (self.images[1], "<p>Two</p>", "")], equal_height="on")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Block.objects.get(name="Cols").equal_height)
        form = self.client.get(reverse("block-create", args=[self.page.pk]))
        self.assertContains(form, "Equal height columns")
        self.assertContains(form, 'data-for="columns_2 columns_3 columns_4"')

    def columns_html(self, **options):
        from home.models import Block, BlockColumn

        block = Block.objects.create(name=f"Sep {options}", block_type="columns_3", title="Heading", **options)
        for index in range(3):
            BlockColumn.objects.create(block=block, position=index, image=self.images[index], text=f"<p>Column {index + 1}</p>")
        return render_to_string(block.template, {"block": block})

    def test_shared_card_is_the_default(self):
        html = self.columns_html()
        self.assertIn("rounded-box p-6 md:p-10", html)  # the one card round all the columns
        self.assertEqual(html.count("bg-base-200"), 0)
        self.assertIn("gap-8", html)

    def test_separate_columns_are_each_their_own_card_with_a_gap(self):
        html = self.columns_html(separate_columns=True)
        self.assertNotIn("md:p-10", html)  # no card round them all
        self.assertEqual(html.count("gap-4 p-6"), 3)  # one padded card each
        self.assertEqual(html.count("bg-base-200"), 3)  # with the theme's card colour...
        self.assertIn("gap-4 md:gap-6", html)  # ...and a gap between
        self.assertIn("items-start", html)  # each as tall as its own content
        self.assertNotIn(" h-full", html)
        for index in (1, 2, 3):
            self.assertIn(f"Column {index}", html)

    def test_separate_columns_use_the_block_colours(self):
        html = self.columns_html(separate_columns=True, background_colour="#112233", text_colour="#ffffff")
        self.assertEqual(html.count("background-color: #112233"), 3)
        self.assertEqual(html.count("color: #ffffff"), 3)
        self.assertEqual(html.count("bg-base-200"), 0)

    def test_separate_columns_can_also_be_equal_height(self):
        html = self.columns_html(separate_columns=True, equal_height=True)
        self.assertEqual(html.count(" h-full"), 3)
        self.assertNotIn("items-start", html)
        self.assertNotIn("border-current/25", html)  # the cards are already visible, so no outline

    def test_the_separate_option_is_saved_and_offered(self):
        from home.models import Block

        response = self.post("columns_2", [(self.images[0], "<p>One</p>", ""), (self.images[1], "<p>Two</p>", "")], separate_columns="on")
        self.assertEqual(response.status_code, 302)
        block = Block.objects.get(name="Cols")
        self.assertTrue(block.separate_columns)
        self.assertFalse(block.equal_height)
        self.assertContains(self.client.get(reverse("block-create", args=[self.page.pk])), "Separate columns")

    def test_no_template_comment_is_printed_on_the_page(self):
        for options in ({}, {"separate_columns": True}, {"equal_height": True}):
            html = self.columns_html(**options)
            self.assertNotIn("{#", html, options)
            self.assertNotIn("#}", html, options)
            self.assertNotIn("A columns block", html, options)

    @staticmethod
    def rounded_images(html):
        """How many of the <img> tags have rounded corners."""
        import re

        return len(re.findall(r"<img[^>]*rounded-box", html))

    def test_flush_images_run_to_the_edge_of_a_separate_card(self):
        html = self.columns_html(separate_columns=True, flush_images=True)
        # The card clips its contents and has no padding of its own...
        self.assertEqual(html.count("gap-0 overflow-hidden"), 3)
        self.assertNotIn("gap-4 p-6", html)
        # ...the text carries the padding instead, and the images are square-cornered.
        self.assertEqual(html.count("flex flex-col gap-2 p-6"), 3)
        self.assertEqual(html.count("<img"), 3)
        self.assertEqual(self.rounded_images(html), 0)

    def test_images_keep_their_margin_unless_flush(self):
        html = self.columns_html(separate_columns=True)
        self.assertEqual(self.rounded_images(html), 3)
        self.assertNotIn("overflow-hidden", html)
        self.assertNotIn("flex flex-col gap-2 p-", html)

    def test_flush_images_in_equal_height_boxes(self):
        html = self.columns_html(equal_height=True, flush_images=True)
        self.assertEqual(html.count("border-current/25"), 3)
        self.assertEqual(html.count("gap-0 overflow-hidden"), 3)
        self.assertNotIn("gap-4 p-4", html)  # the box has no padding of its own...
        self.assertEqual(html.count("flex flex-col gap-2 p-4"), 3)  # ...the boxes' smaller padding is on the text
        self.assertEqual(self.rounded_images(html), 0)

    def test_flush_has_no_effect_when_the_columns_share_the_block_card(self):
        html = self.columns_html(flush_images=True)
        self.assertNotIn("overflow-hidden", html)
        self.assertEqual(self.rounded_images(html), 3)

    def test_the_flush_option_is_saved_and_offered(self):
        from home.models import Block

        response = self.post("columns_2", [(self.images[0], "<p>One</p>", ""), (self.images[1], "<p>Two</p>", "")], flush_images="on")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Block.objects.get(name="Cols").flush_images)
        self.assertContains(self.client.get(reverse("block-create", args=[self.page.pk])), "Images with no margin")

    def test_each_column_can_have_a_title(self):
        from home.models import Block, BlockColumn

        block = Block.objects.create(name="Titled", block_type="columns_2", title="Block heading")
        BlockColumn.objects.create(block=block, position=0, title="First title", image=self.images[0], text="<p>One</p>")
        BlockColumn.objects.create(block=block, position=1, text="<p>Two, with no title</p>")
        html = render_to_string(block.template, {"block": block})
        self.assertEqual(html.count("<h3"), 1)
        self.assertIn("First title", html)
        # The title is between the image and the text.
        self.assertLess(html.index("<img"), html.index("First title"))
        self.assertLess(html.index("First title"), html.index("<p>One</p>"))

    def test_a_title_is_escaped(self):
        from home.models import Block, BlockColumn

        block = Block.objects.create(name="Esc", block_type="columns_2")
        BlockColumn.objects.create(block=block, position=0, title="<script>alert(1)</script>", text="x")
        self.assertNotIn("<script>alert", render_to_string(block.template, {"block": block}))

    def test_a_column_with_only_a_title_counts_as_filled_in(self):
        from home.models import Block

        response = self.post("columns_2", [(None, "", ""), (None, "", "")], title="x")
        self.assertEqual(response.status_code, 200)  # two empty columns are refused...
        data = {"col-0-title": "Only a title", "col-1-title": "Another"}
        response = self.post("columns_2", [(None, "", ""), (None, "", "")], **data)
        self.assertEqual(response.status_code, 302)  # ...but titles alone are enough
        self.assertEqual([c.title for c in Block.objects.get(name="Cols").columns.all()], ["Only a title", "Another"])

    def test_the_form_offers_a_title_for_each_column(self):
        response = self.client.get(reverse("block-create", args=[self.page.pk]))
        for index in range(4):
            self.assertContains(response, f'name="col-{index}-title"')

    def test_flush_title_and_text_are_padded_together(self):
        from home.models import Block, BlockColumn

        block = Block.objects.create(name="Flush titled", block_type="columns_2", separate_columns=True, flush_images=True)
        BlockColumn.objects.create(block=block, position=0, title="T", image=self.images[0], text="<p>x</p>")
        html = render_to_string(block.template, {"block": block})
        self.assertEqual(html.count("flex flex-col gap-2 p-6"), 1)  # one padded wrapper holding the title and the text


class MatchImageHeightsTests(TestCase):
    """Images in columns can all be made the height of the shortest one."""

    SIZES = [(400, 300), (300, 300), (200, 400)]  # width x height: the first is the shortest for its width

    def setUp(self):
        import tempfile

        from django.test import override_settings

        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        override = override_settings(MEDIA_ROOT=self.media.name)
        override.enable()
        self.addCleanup(override.disable)

    def make_image(self, width, height):
        """An image in the library with a real (tiny, temporary) file of this size."""
        from io import BytesIO

        from django.core.files.base import ContentFile
        from PIL import Image as PILImage

        buffer = BytesIO()
        PILImage.new("RGB", (width, height), "white").save(buffer, "PNG")
        image = Image(description=f"{width}x{height}")
        image.image.save(f"test-{width}x{height}.png", ContentFile(buffer.getvalue()), save=True)
        return image

    def block(self, sizes=None, **options):
        from home.models import Block, BlockColumn

        block = Block.objects.create(name=f"Match {options} {sizes}", block_type="columns_3", **options)
        for index, (width, height) in enumerate(sizes or self.SIZES):
            BlockColumn.objects.create(block=block, position=index, image=self.make_image(width, height), text=f"<p>{index}</p>")
        return block

    def test_the_shortest_image_sets_the_ratio(self):
        self.assertEqual(self.block(match_image_heights=True).image_ratio, "400 / 300")

    def test_it_is_the_shortest_for_the_width_not_the_smallest_file(self):
        # A big photo that is wide and short is shorter, at the same width, than a small square.
        self.assertEqual(self.block([(1000, 500), (100, 100)], match_image_heights=True).image_ratio, "1000 / 500")

    def test_off_by_default(self):
        block = self.block()
        self.assertEqual(block.image_ratio, "")
        html = render_to_string(block.template, {"block": block})
        self.assertNotIn("aspect-ratio", html)
        self.assertNotIn("object-cover", html)
        self.assertEqual(html.count("h-auto"), 3)

    def test_every_image_gets_the_same_ratio(self):
        block = self.block(match_image_heights=True)
        html = render_to_string(block.template, {"block": block})
        self.assertEqual(html.count("aspect-ratio: 400 / 300"), 3)
        self.assertEqual(html.count("object-cover"), 3)  # the taller images are cropped, not squashed
        self.assertNotIn("h-auto", html)

    def test_only_the_columns_shown_count(self):
        from home.models import Block, BlockColumn

        # A two column block with a very short image in a hidden third column.
        block = Block.objects.create(name="Hidden", block_type="columns_2", match_image_heights=True)
        for index, (width, height) in enumerate([(300, 300), (300, 300), (1000, 100)]):
            BlockColumn.objects.create(block=block, position=index, image=self.make_image(width, height))
        self.assertEqual(block.image_ratio, "300 / 300")

    def test_a_missing_or_unreadable_image_file_is_skipped(self):
        from home.models import Block, BlockColumn

        block = Block.objects.create(name="Broken", block_type="columns_2", match_image_heights=True)
        BlockColumn.objects.create(block=block, position=0, image=Image.objects.create(description="gone", image="images/not-there.png"))
        BlockColumn.objects.create(block=block, position=1, image=self.make_image(200, 100))
        self.assertEqual(block.image_ratio, "200 / 100")
        BlockColumn.objects.filter(block=block, position=1).delete()
        self.assertEqual(block.image_ratio, "")  # nothing readable: no ratio, so the page still shows

    def test_it_works_with_separate_flush_and_equal_height_cards(self):
        block = self.block(match_image_heights=True, separate_columns=True, flush_images=True, equal_height=True)
        html = render_to_string(block.template, {"block": block})
        self.assertEqual(html.count("aspect-ratio: 400 / 300"), 3)
        self.assertEqual(html.count("<img"), 3)

