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
            self.assertContains(response, f"<span data-column-number>{number}</span>")

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

    def test_columns_are_saved_in_the_order_they_were_moved_to(self):
        from home.models import Block

        # The second column is moved to the left: its order is 0 and the first one's is 1.
        self.post("columns_3", [(self.images[0], "<p>A</p>", ""), (self.images[1], "<p>B</p>", ""), (self.images[2], "<p>C</p>", "")],
                  **{"col-0-order": "1", "col-1-order": "0", "col-2-order": "2"})
        block = Block.objects.get(name="Cols")
        self.assertEqual([c.text for c in block.columns.all()], ["<p>B</p>", "<p>A</p>", "<p>C</p>"])
        self.assertEqual([c.position for c in block.columns.all()], [0, 1, 2])

    def test_moving_a_column_right_when_editing(self):
        from home.models import Block

        self.post("columns_3", [(self.images[0], "<p>A</p>", ""), (self.images[1], "<p>B</p>", ""), (self.images[2], "<p>C</p>", "")])
        block = Block.objects.get(name="Cols")
        columns = list(block.columns.all())
        data = {
            "name": "Cols", "block_type": "columns_3", "title": "Our team", "subtitle": "", "text": "", "layout": "text_left",
            "image_size": "medium", "background_colour": "", "text_colour": "", "url": "",
            "col-TOTAL_FORMS": "4", "col-INITIAL_FORMS": "3", "col-MIN_NUM_FORMS": "0", "col-MAX_NUM_FORMS": "4",
            "col-3-image": "", "col-3-text": "", "col-3-url": "", "col-3-order": "3",
        }
        for index, column in enumerate(columns):
            data[f"col-{index}-id"] = column.pk
            data[f"col-{index}-block"] = block.pk
            data[f"col-{index}-image"] = column.image_id
            data[f"col-{index}-text"] = column.text
            data[f"col-{index}-url"] = ""
        data.update({"col-0-order": "1", "col-1-order": "2", "col-2-order": "0"})  # C, A, B
        response = self.client.post(reverse("block-edit", args=[self.page.pk, block.pk]), data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual([c.text for c in block.columns.all()], ["<p>C</p>", "<p>A</p>", "<p>B</p>"])
        # The same columns, so the images moved with their text.
        self.assertEqual([c.image_id for c in block.columns.all()], [self.images[2].pk, self.images[0].pk, self.images[1].pk])

    def test_the_order_decides_which_columns_must_be_filled_in(self):
        # A three column block where the empty column is moved to the fourth place: only the first three count.
        response = self.post("columns_3", [(None, "", ""), (self.images[1], "<p>B</p>", ""), (self.images[2], "<p>C</p>", ""), (self.images[3], "<p>D</p>", "")],
                             **{"col-0-order": "3", "col-1-order": "0", "col-2-order": "1", "col-3-order": "2"})
        self.assertEqual(response.status_code, 302)

    def test_without_an_order_the_columns_keep_the_order_they_came_in(self):
        from home.models import Block

        self.post("columns_2", [(self.images[0], "<p>A</p>", ""), (self.images[1], "<p>B</p>", "")])
        self.assertEqual([c.text for c in Block.objects.get(name="Cols").columns.all()], ["<p>A</p>", "<p>B</p>"])

    def test_the_form_has_move_buttons_and_an_order_for_each_column(self):
        html = self.client.get(reverse("block-create", args=[self.page.pk])).content.decode()
        self.assertEqual(html.count("data-column-card>"), 4)
        self.assertEqual(html.count('data-move="-1" aria-label'), 4)
        self.assertEqual(html.count('data-move="1" aria-label'), 4)
        for index in range(4):
            self.assertRegex(html, rf'name="col-{index}-order" value="{index}"')

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
        self.assertEqual(html.count("prose prose-themed max-w-none p-6"), 3)
        self.assertEqual(html.count("<img"), 3)
        self.assertEqual(self.rounded_images(html), 0)

    def test_images_keep_their_margin_unless_flush(self):
        html = self.columns_html(separate_columns=True)
        self.assertEqual(self.rounded_images(html), 3)
        self.assertNotIn("overflow-hidden", html)
        self.assertNotIn("max-w-none p-", html)

    def test_flush_images_in_equal_height_boxes(self):
        html = self.columns_html(equal_height=True, flush_images=True)
        self.assertEqual(html.count("border-current/25"), 3)
        self.assertEqual(html.count("gap-0 overflow-hidden"), 3)
        self.assertNotIn("gap-4 p-4", html)  # the box has no padding of its own...
        self.assertEqual(html.count("prose prose-themed max-w-none p-4"), 3)  # ...the boxes' smaller padding is on the text
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
        # The title is at the top, above the image, with the text under the image.
        self.assertLess(html.index("First title"), html.index("<img"))
        self.assertLess(html.index("<img"), html.index("<p>One</p>"))

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
        self.assertEqual(html.count(" p-6"), 1)  # the card has none: the text is padded round the flush image...
        self.assertEqual(html.count(" p-4"), 1)  # ...and the title, with less padding
        self.assertLess(html.index("<h3"), html.index("<img"))  # the title is above the image, which still touches the card's edges


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


class AuditionsBlockTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from accounts.models import CustomUser
        from backstage.models import Event, EventDateTime, Venue
        from home.models import Block, WebPage

        now = timezone.now()
        cls.user = CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!")
        venue = Venue.objects.create(name="Esher Theatre")

        def audition(title, *days, event_type=Event.EventType.AUDITION, image=True):
            production = Production.objects.create(title=title)
            event = Event.objects.create(title=f"{title} auditions", event_type=event_type, venue=venue)
            event.productions.add(production)
            for day in days:
                EventDateTime.objects.create(event=event, datetime=now + timedelta(days=day))
            if image:
                ProductionImage.objects.create(
                    production=production, is_default=True,
                    image=Image.objects.create(description=title, image=f"images/test-{title.replace(' ', '-')}.jpg"),
                )
            return production

        cls.later = audition("Later Play", 40)
        cls.soon = audition("Soon Play", 10, 12)
        cls.two_events = audition("Past And Future", -5, 20)
        cls.past = audition("Past Play", -3)
        cls.performance = audition("Performance Only", 15, event_type=Event.EventType.PERFORMANCE)
        cls.no_image = audition("No Image Play", 30, image=False)
        cls.block = Block.objects.create(
            name="Auditions", block_type="auditions", title="Join us", subtitle="Come along", text="<p>All welcome.</p>",
        )
        cls.page = WebPage.objects.create(title="Take part", slug="take-part")
        cls.page.add_block(cls.block)

    def test_only_productions_with_an_audition_still_to_come_in_date_order(self):
        from home.auditions import upcoming_auditions

        titles = [production.title for production in upcoming_auditions()]
        self.assertEqual(titles, ["Soon Play", "Past And Future", "No Image Play", "Later Play"])

    def test_each_production_has_its_upcoming_dates_only(self):
        from home.auditions import upcoming_auditions

        dates = {p.title: p.audition_dates for p in upcoming_auditions()}
        self.assertEqual(len(dates["Soon Play"]), 2)
        self.assertEqual(len(dates["Past And Future"]), 1)  # the past one is left out
        self.assertEqual(dates["Soon Play"][0].event.venue.name, "Esher Theatre")
        self.assertTrue(dates["Soon Play"][0].datetime < dates["Soon Play"][1].datetime)

    def test_the_block_shows_title_subtitle_text_and_the_productions(self):
        html = render_to_string(self.block.template, {"block": self.block})
        for text in ("Join us", "Come along", "All welcome.", "Soon Play", "Later Play", "No Image Play"):
            self.assertIn(text, html)
        for text in ("Past Play", "Performance Only"):
            self.assertNotIn(text, html)

    def test_each_has_a_small_image_then_the_title_then_the_dates_which_link_to_its_page(self):
        html = render_to_string(self.block.template, {"block": self.block})
        item = html[html.index("Soon Play</h3>") - 600:html.index("Past And Future")]
        self.assertLess(item.index("<img"), item.index("Soon Play</h3>"))
        self.assertLess(item.index('href="'), item.index("<img"))  # the image sits inside its own link
        self.assertLess(item.index("Soon Play</h3>"), item.rindex('href="'))  # the date links come after the title
        self.assertEqual(html.count(f'href="/auditions/{self.soon.pk}/"'), 3)  # its image, and one for each of its two dates
        self.assertEqual(html.count(f'href="/auditions/{self.later.pk}/"'), 2)  # its image and its date
        self.assertIn("max-h-40", html)  # a reduced size image

    def test_each_audition_is_a_card_of_three_columns(self):
        import re

        html = render_to_string(self.block.template, {"block": self.block})
        cards = re.findall(r'<li class="grid[^"]*">', html)
        self.assertEqual(len(cards), 4)  # one card for each production
        for card in cards:
            self.assertIn("md:grid-cols-3", card)  # three columns side by side...
            self.assertIn("bg-base-100", card)  # ...in a card...
            self.assertNotRegex(card, r"(?<![:\w-])grid-cols-\d")  # ...which stack on a phone
        # Column 1 is the image, column 2 the title, column 3 the dates.
        card = html[html.index("<li class=\"grid"):html.index("Past And Future")]
        self.assertLess(card.index("<img"), card.index("Soon Play</h3>"))
        self.assertLess(card.index("Soon Play</h3>"), card.index("<ul"))
        self.assertEqual(card.count("<h3"), 1)

    def test_a_card_with_no_image_keeps_its_first_column(self):
        html = render_to_string(self.block.template, {"block": self.block})
        card = html[html.index("No Image Play</h3>") - 400:html.index("No Image Play</h3>")]
        self.assertNotIn("<img", card)
        self.assertIn("<div>", card)  # an empty first column, so the title stays in the middle

    def test_a_production_with_no_image_still_shows(self):
        html = render_to_string(self.block.template, {"block": self.block})
        self.assertEqual(html.count("<img"), 3)  # three of the four have an image
        self.assertIn("No Image Play", html)

    def test_with_no_live_auditions_the_block_shows_nothing(self):
        from backstage.models import EventDateTime

        EventDateTime.objects.all().delete()
        html = render_to_string(self.block.template, {"block": self.block})
        self.assertEqual(html.strip(), "")  # not even its title, subtitle or text

    def test_with_only_past_auditions_the_block_shows_nothing(self):
        from backstage.models import EventDateTime

        EventDateTime.objects.update(datetime=timezone.now() - timedelta(days=1))
        self.assertEqual(render_to_string(self.block.template, {"block": self.block}).strip(), "")

    def test_a_page_whose_only_block_has_no_auditions_shows_none_of_it(self):
        from backstage.models import EventDateTime

        EventDateTime.objects.all().delete()
        response = self.client.get(reverse("webpage", args=["take-part"]))
        self.assertEqual(response.status_code, 200)
        for text in ("Join us", "Come along", "All welcome.", "no auditions"):
            self.assertNotContains(response, text)

    def test_the_block_is_on_the_page_and_the_page_is_public(self):
        response = self.client.get(reverse("webpage", args=["take-part"]))
        self.assertContains(response, "Soon Play")

    def test_audition_detail_page(self):
        response = self.client.get(reverse("audition-detail", args=[self.soon.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Soon Play")
        self.assertContains(response, "Esher Theatre")
        self.assertNotContains(response, "Later Play")  # just this production
        self.assertContains(response, "All auditions")

    def test_audition_detail_is_404_when_there_is_no_audition_to_come(self):
        for production in (self.past, self.performance, Production.objects.create(title="Nothing")):
            self.assertEqual(self.client.get(reverse("audition-detail", args=[production.pk])).status_code, 404)

    def test_the_auditions_page_still_lists_every_audition(self):
        response = self.client.get(reverse("auditions"))
        self.assertEqual([view["production"].title for view in response.context["audition_views"]],
                         ["Soon Play", "Past And Future", "No Image Play", "Later Play"])
        self.assertContains(response, "Esher Theatre")

    def test_the_form_offers_the_block_and_keeps_its_text_optional(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("block-create", args=[self.page.pk]))
        self.assertContains(response, 'value="auditions"')
        data = {
            "name": "No text", "block_type": "auditions", "title": "Auditions", "subtitle": "", "text": "", "layout": "text_left",
            "image_size": "medium", "background_colour": "", "text_colour": "", "url": "",
            "col-TOTAL_FORMS": "4", "col-INITIAL_FORMS": "0", "col-MIN_NUM_FORMS": "0", "col-MAX_NUM_FORMS": "4",
        }
        self.assertEqual(self.client.post(reverse("block-create", args=[self.page.pk]), data).status_code, 302)

    def test_clicking_the_image_goes_to_the_audition_page_too(self):
        import re

        html = render_to_string(self.block.template, {"block": self.block})
        for production in (self.soon, self.later):
            link = re.search(rf'<a href="/auditions/{production.pk}/"[^>]*>\s*<img[^>]*alt="{production.title}"', html)
            self.assertIsNotNone(link, production.title)  # the image is inside a link to its own audition page
        # A production with no image has no image link, only date links.
        self.assertEqual(html.count(f'href="/auditions/{self.no_image.pk}/"'), 1)

    def test_the_title_is_big_and_the_strap_line_is_under_it(self):
        self.soon.strap_line = "A tale of two halves"
        self.soon.save()
        html = render_to_string(self.block.template, {"block": self.block})
        self.assertIn("text-2xl font-bold md:text-3xl", html)  # bigger than before (it was text-xl)
        self.assertLess(html.index("Soon Play</h3>"), html.index("A tale of two halves"))
        self.assertLess(html.index("A tale of two halves"), html.index("Past And Future</h3>"))
        self.assertEqual(html.count("<p class=\"mt-1 text-lg italic"), 1)  # only productions that have one

    def test_only_the_date_is_shown_not_the_time(self):
        import re

        from home.auditions import upcoming_auditions

        html = render_to_string(self.block.template, {"block": self.block})
        links = re.findall(r'<a href="/auditions/\d+/" class="link link-hover">([^<]+)</a>', html)
        # One link for each day: Soon Play has two, and Past And Future, No Image and Later have one each.
        self.assertEqual(len(links), 5)
        for text in links:
            self.assertRegex(text, r"^[A-Z][a-z]{2} \d{1,2} [A-Z][a-z]{2} \d{4}$")  # "Mon 12 Oct 2026"
            self.assertNotRegex(text, r"\d:\d\d|[ap]\.m\.")
        # The first link is the soonest audition's day.
        first_day = upcoming_auditions()[0].audition_days[0]
        self.assertEqual(links[0], first_day.strftime("%a ") + str(first_day.day) + first_day.strftime(" %b %Y"))

    def test_two_audition_times_on_one_day_are_one_date(self):
        from backstage.models import Event, EventDateTime
        from home.auditions import upcoming_auditions

        day = timezone.now() + timedelta(days=60)
        production = Production.objects.create(title="Two Sessions")
        event = Event.objects.create(title="Sessions", event_type=Event.EventType.AUDITION)
        event.productions.add(production)
        for hour in (0, 4):  # two sessions on the same day
            EventDateTime.objects.create(event=event, datetime=day.replace(hour=10, minute=0) + timedelta(hours=hour))
        found = next(p for p in upcoming_auditions() if p.title == "Two Sessions")
        self.assertEqual(len(found.audition_dates), 2)
        self.assertEqual(len(found.audition_days), 1)
        html = render_to_string(self.block.template, {"block": self.block})
        self.assertEqual(html.count(f'href="/auditions/{production.pk}/"'), 1)  # one date link (it has no image)


class EmptyTextTests(TestCase):
    """Text that shows nothing (an empty paragraph left by the editor) is treated as no text, and its container is not drawn."""

    EMPTY = ("", "   ", "<p></p>", "<p><br></p>", "<p>&nbsp;</p>", "<p> \xa0 </p><div></div>", "<p><strong></strong></p>")

    def test_what_counts_as_text(self):
        from home.models import html_has_content

        for html in self.EMPTY:
            self.assertFalse(html_has_content(html), repr(html))
        for html in ("<p>Hello</p>", "<p>&amp;</p>", '<p><img src="/x.png"></p>', '<iframe src="https://example.com"></iframe>'):
            self.assertTrue(html_has_content(html), repr(html))

    def test_the_auditions_block_draws_no_text_container_without_text(self):
        from backstage.models import Event, EventDateTime
        from home.models import Block

        production = Production.objects.create(title="Live One")
        event = Event.objects.create(title="Auditions", event_type=Event.EventType.AUDITION)
        event.productions.add(production)
        EventDateTime.objects.create(event=event, datetime=timezone.now() + timedelta(days=5))
        for text in self.EMPTY:
            block = Block.objects.create(name=f"Aud {text!r}", block_type="auditions", title="Join us", text=text)
            html = render_to_string(block.template, {"block": block})
            self.assertIn("Live One", html)
            self.assertNotIn("mb-8", html, repr(text))  # the div that holds the text
            self.assertNotIn("prose", html, repr(text))
        block = Block.objects.create(name="Aud with text", block_type="auditions", title="Join us", text="<p>All welcome.</p>")
        html = render_to_string(block.template, {"block": block})
        self.assertIn("mb-8", html)
        self.assertIn("All welcome.", html)

    def test_a_column_draws_no_text_container_without_text(self):
        from home.models import Block, BlockColumn

        block = Block.objects.create(name="Cols", block_type="columns_2")
        for index, text in enumerate(("<p></p>", "<p>&nbsp;</p>")):
            BlockColumn.objects.create(block=block, position=index, title=f"Title {index}", text=text)
        html = render_to_string(block.template, {"block": block})
        self.assertIn("Title 0", html)
        self.assertNotIn("prose", html)

    def test_a_column_with_only_empty_text_draws_nothing_under_its_image(self):
        from home.models import Block, BlockColumn

        block = Block.objects.create(name="Cols", block_type="columns_2")
        BlockColumn.objects.create(block=block, position=0, image=Image.objects.create(description="x", image="images/x.jpg"), text="<p></p>")
        html = render_to_string(block.template, {"block": block})
        self.assertIn("<img", html)
        self.assertNotIn("prose", html)  # no text container under the image

    def test_the_hero_draws_no_text_without_text(self):
        from home.models import Block

        block = Block.objects.create(
            name="Hero", block_type="hero_image", title="Welcome", text="<p></p>",
            image=Image.objects.create(description="x", image="images/x.jpg"),
        )
        html = render_to_string(block.template, {"block": block})
        self.assertIn("Welcome", html)
        self.assertNotIn("prose", html)

    def test_a_text_block_with_only_an_empty_paragraph_is_rejected(self):
        from django.core.exceptions import ValidationError

        from home.models import Block

        block = Block(name="Empty", block_type="text", text="<p></p>")
        with self.assertRaises(ValidationError):
            block.clean()


class ColumnTitleTests(TestCase):
    """A column's title is centred at the top of its card, above the image."""

    def render(self, **options):
        from home.models import Block, BlockColumn

        block = Block.objects.create(name=f"Titles {options}", block_type="columns_2", **options)
        BlockColumn.objects.create(block=block, position=0, title="Top title", image=Image.objects.create(description="a", image="images/a.jpg"), text="<p>Words</p>")
        BlockColumn.objects.create(block=block, position=1, title="   ", image=Image.objects.create(description="b", image="images/b.jpg"), text="<p>More</p>")
        return render_to_string(block.template, {"block": block})

    def test_the_title_is_centred_above_the_image(self):
        html = self.render()
        self.assertIn('<h3 class="text-center text-2xl font-bold leading-tight md:text-3xl -mb-2">Top title</h3>', html)
        self.assertLess(html.index("Top title"), html.index("<img"))
        self.assertLess(html.index("<img"), html.index("Words"))

    def test_a_title_of_only_spaces_shows_no_heading(self):
        html = self.render()
        self.assertEqual(html.count("<h3"), 1)  # only the first column's
        self.assertEqual(html.count("<img"), 2)

    def test_it_is_the_first_thing_in_a_separate_card_too(self):
        html = self.render(separate_columns=True)
        card = html[html.index('<div class="flex min-w-0 flex-col'):html.index("Words")]
        self.assertLess(card.index("<h3"), card.index("<img"))

    def test_a_flush_image_still_touches_the_cards_top_when_there_is_no_title(self):
        html = self.render(separate_columns=True, flush_images=True)
        second = html.split('<div class="flex min-w-0 flex-col')[2]  # the second column's card
        self.assertNotIn("<h3", second)  # no heading, so the image is the card's first thing
        self.assertLess(second.index("<img"), second.index("More"))
        # With a title, the heading is padded above the image; the image itself still has no margin.
        self.assertIn('class="text-center text-2xl font-bold leading-tight md:text-3xl p-4"', html)

    def test_has_title(self):
        from home.models import BlockColumn

        self.assertTrue(BlockColumn(title="x").has_title)
        self.assertFalse(BlockColumn(title="  ").has_title)
        self.assertFalse(BlockColumn(title="").has_title)

    def test_the_title_is_larger_with_less_space_round_it(self):
        html = self.render()
        self.assertNotIn("text-xl font-bold", html)  # it was text-xl
        self.assertIn("text-2xl", html)
        self.assertIn("md:text-3xl", html)
        self.assertIn("-mb-2", html)  # the gap under it is pulled in
        flush = self.render(separate_columns=True, flush_images=True)
        self.assertNotIn("font-bold p-6", flush)  # tighter than the text's padding
        self.assertIn("md:text-3xl p-4", flush)
        box = self.render(equal_height=True, flush_images=True)
        self.assertIn("md:text-3xl p-3", box)  # tighter still in the smaller boxes


class HeroFadeInTimeTests(TestCase):
    """A hero image block's fade-in time is its own setting (5 seconds unless changed; 0 for none)."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import CustomUser
        from home.models import WebPage

        cls.user = CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!")
        cls.page = WebPage.objects.create(title="Home", slug="home")
        cls.image = Image.objects.create(description="x", image="images/x.jpg")

    def hero(self, **options):
        from home.models import Block

        return Block.objects.create(name="Hero", block_type="hero_image", title="Welcome", image=self.image, **options)

    def render(self, block):
        return render_to_string(block.template, {"block": block})

    def test_it_is_five_seconds_unless_changed(self):
        block = self.hero()
        self.assertEqual(block.fade_in_seconds, 5)
        self.assertRegex(self.render(block), r"--hero-fade: 5(\.0)?s;")

    def test_the_blocks_own_time_is_used(self):
        self.assertIn("--hero-fade: 2.5s", self.render(self.hero(fade_in_seconds=2.5)))

    def test_zero_means_no_fade(self):
        self.assertRegex(self.render(self.hero(fade_in_seconds=0)), r"--hero-fade: 0(\.0)?s;")

    def test_the_stylesheet_uses_the_blocks_time(self):
        from pathlib import Path

        css = (Path(__file__).resolve().parent.parent / "backstage" / "static" / "css" / "input.css").read_text(encoding="utf-8")
        self.assertIn("animation: hero-fade-in var(--hero-fade, 5s) ease-in both", css)
        self.assertIn("animation: hero-text-fade var(--hero-fade, 5s) ease-in both", css)

    def test_the_time_must_be_from_0_to_30_seconds(self):
        from home.forms import BlockForm

        base = {"name": "Hero", "block_type": "hero_image", "title": "Welcome", "layout": "text_left", "image_size": "medium", "image": self.image.pk}
        for good in ("0", "5", "12.5", "30"):
            self.assertTrue(BlockForm({**base, "fade_in_seconds": good}).is_valid(), good)
        for bad in ("-1", "30.5", "abc"):
            self.assertFalse(BlockForm({**base, "fade_in_seconds": bad}).is_valid(), bad)
        blank = BlockForm({**base, "fade_in_seconds": ""})  # left blank, it is the usual 5 seconds
        self.assertTrue(blank.is_valid())
        self.assertEqual(blank.cleaned_data["fade_in_seconds"], 5)

    def test_the_block_form_asks_for_it_for_hero_blocks_only(self):
        self.client.force_login(self.user)
        html = self.client.get(reverse("block-create", args=[self.page.pk])).content.decode()
        self.assertRegex(html, r'(?s)<div data-for="hero_image" class="max-w-xs">.*?name="fade_in_seconds"')
        self.assertIn("Fade-in time (seconds)", html)

    def test_saving_a_hero_block_keeps_the_time(self):
        from home.models import Block

        self.client.force_login(self.user)
        data = {
            "name": "Hero", "block_type": "hero_image", "title": "Welcome", "subtitle": "", "text": "", "layout": "text_left",
            "image_size": "medium", "image": self.image.pk, "background_colour": "", "text_colour": "", "url": "", "fade_in_seconds": "8",
            "col-TOTAL_FORMS": "4", "col-INITIAL_FORMS": "0", "col-MIN_NUM_FORMS": "0", "col-MAX_NUM_FORMS": "4",
        }
        self.assertEqual(self.client.post(reverse("block-create", args=[self.page.pk]), data).status_code, 302)
        self.assertEqual(Block.objects.get(name="Hero").fade_in_seconds, 8)


class PromotionBlockTests(TestCase):
    """A promotion block shows the promotion image of the next production with a performance still to come."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import CustomUser
        from home.models import Block, WebPage

        cls.user = CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!")
        cls.page = WebPage.objects.create(title="Home", slug="home")
        cls.block = Block.objects.create(name="Promo", block_type="promotion")

    def production(self, title, days=None, event_type="performance", images=(), hours=0):
        """A production with an event of that type `days` from now, and images [(description, type, default)]."""
        from backstage.models import Event, EventDateTime, ProductionImage

        production = Production.objects.create(title=title)
        if days is not None:
            event = Event.objects.create(title=f"{title} event", event_type=event_type)
            event.productions.add(production)
            EventDateTime.objects.create(event=event, datetime=timezone.now() + timedelta(days=days, hours=hours))
        for description, image_type, default in images:
            image = Image.objects.create(description=description, image=f"images/{description}.jpg", image_type=image_type)
            ProductionImage.objects.create(production=production, image=image, is_default=default)
        return production

    def shown(self, block=None):
        block = block or self.block
        return render_to_string(block.template, {"block": block})

    def test_the_block_type_is_offered_and_has_its_template(self):
        from home.models import Block

        self.assertIn(("promotion", "Promotion"), Block.BlockType.choices)
        self.assertEqual(self.block.template, "home/blocks/promotion.html")

    def test_it_shows_the_promotion_image_of_the_production_with_the_next_performance(self):
        self.production("Later", days=30, images=[("later-poster", "promotion", True)])
        self.production("Sooner", days=5, images=[("sooner-poster", "promotion", True)])
        html = self.shown()
        self.assertIn("sooner-poster.jpg", html)
        self.assertNotIn("later-poster", html)

    def test_past_performances_do_not_count(self):
        self.production("Over", days=-3, images=[("over-poster", "promotion", True)])
        self.production("Coming", days=9, images=[("coming-poster", "promotion", True)])
        html = self.shown()
        self.assertIn("coming-poster.jpg", html)
        self.assertNotIn("over-poster", html)

    def test_only_performances_count_not_auditions_or_rehearsals(self):
        self.production("Auditioning", days=2, event_type="audition", images=[("aud-poster", "promotion", True)])
        self.production("Rehearsing", days=3, event_type="rehearsal", images=[("reh-poster", "promotion", True)])
        self.production("Playing", days=20, images=[("play-poster", "promotion", True)])
        html = self.shown()
        self.assertIn("play-poster.jpg", html)
        self.assertNotIn("aud-poster", html)
        self.assertNotIn("reh-poster", html)

    def test_the_soonest_of_a_productions_dates_counts(self):
        from backstage.models import Event, EventDateTime

        late_first = self.production("Two dates", days=40, images=[("two-poster", "promotion", True)])
        event = late_first.events.first()
        EventDateTime.objects.create(event=event, datetime=timezone.now() + timedelta(days=4))  # sooner than the other
        self.production("One date", days=10, images=[("one-poster", "promotion", True)])
        self.assertIn("two-poster.jpg", self.shown())

    def test_that_production_without_a_promotion_image_shows_nothing(self):
        # It is the next production, so the block does not go on to a later one.
        self.production("Next", days=5, images=[("next-headshot", "headshot", True), ("next-gallery", "gallery", False)])
        self.production("After", days=50, images=[("after-poster", "promotion", True)])
        self.assertEqual(self.shown().strip(), "")

    def test_no_upcoming_performance_shows_nothing_not_even_the_title(self):
        from home.models import Block

        titled = Block.objects.create(name="Titled", block_type="promotion", title="Next show", subtitle="Book now")
        self.production("Over", days=-3, images=[("over-poster", "promotion", True)])
        self.assertEqual(self.shown(titled).strip(), "")

    def test_only_a_promotion_image_is_used_the_default_one_if_it_is(self):
        self.production("Show", days=5, images=[
            ("show-gallery", "gallery", True), ("show-promo-a", "promotion", False), ("show-promo-b", "promotion", False),
        ])
        html = self.shown()
        self.assertIn("show-promo-a.jpg", html)  # the first promotion image: the default is a gallery picture
        self.assertNotIn("show-gallery", html)
        self.assertNotIn("show-promo-b", html)

    def test_a_default_promotion_image_is_preferred(self):
        self.production("Show", days=5, images=[("promo-a", "promotion", False), ("promo-b", "promotion", True)])
        self.assertIn("promo-b.jpg", self.shown())

    def test_the_title_subtitle_size_and_link_are_used(self):
        from home.models import Block

        block = Block.objects.create(
            name="Big promo", block_type="promotion", title="Coming soon", subtitle="Book now", image_size="large", url="/page/tickets/"
        )
        self.production("Show", days=5, images=[("show-promo", "promotion", True)])
        html = self.shown(block)
        self.assertIn("Coming soon", html)
        self.assertIn("Book now", html)
        self.assertIn("max-w-2xl", html)
        self.assertIn('href="/page/tickets/"', html)

    def test_the_page_shows_it(self):
        from home.models import Block

        self.production("Show", days=5, images=[("show-promo", "promotion", True)])
        self.page.add_block(self.block)
        response = self.client.get(reverse("webpage", args=["home"]))
        self.assertContains(response, "show-promo.jpg")

    def test_a_promotion_block_needs_no_image_of_its_own(self):
        from home.forms import BlockForm

        form = BlockForm({"name": "Promo", "block_type": "promotion", "layout": "text_left", "image_size": "medium"})
        self.assertTrue(form.is_valid(), form.errors)

    def test_the_form_offers_the_size_and_link_but_not_an_image_to_choose(self):
        self.client.force_login(self.user)
        html = self.client.get(reverse("block-create", args=[self.page.pk])).content.decode()
        self.assertIn('<option value="promotion">Promotion</option>', html)
        self.assertRegex(html, r'data-for="image text_image cast promotion"')
        self.assertRegex(html, r'data-for="text_image split promotion"')
        self.assertRegex(html, r'(?s)<div data-for="image text_image cast hero_image split">.*?name="image"')
        self.assertIn("promotion image of the next production", html)

    def test_it_takes_few_queries(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.production("Show", days=5, images=[("show-promo", "promotion", True)])
        with CaptureQueriesContext(connection) as queries:
            self.shown()
        self.assertLessEqual(len(queries), 3)  # the production, its image, and where to buy tickets

    # ---- the Buy Tickets button

    def ticketed(self, title, days, url="https://tickets.example.com/show", **kwargs):
        """A production with a performance whose event sells tickets at `url` (a ticket site with no address if empty)."""
        from backstage.models import TicketSite

        production = self.production(title, days=days, images=[(f"{title.lower()}-promo", "promotion", True)], **kwargs)
        event = production.events.get()
        event.ticket_site = TicketSite.objects.create(name=f"{title} tickets", url=url)
        event.save()
        return production

    def test_a_ticketed_event_has_a_buy_tickets_button_linking_to_the_ticket_site(self):
        self.ticketed("Show", 5)
        html = self.shown()
        self.assertRegex(html, r'<a href="https://tickets.example.com/show" class="btn btn-primary btn-md[^"]*"[^>]*>Buy Tickets</a>')
        self.assertIn('target="_blank"', html)
        self.assertIn('rel="noopener noreferrer"', html)

    def test_the_button_is_medium_sized_and_sits_on_the_image_centred_30px_from_its_bottom(self):
        self.ticketed("Show", 5)
        html = self.shown()
        self.assertNotIn("btn-sm", html)
        self.assertNotIn("btn-lg", html)
        self.assertNotIn("btn-xs", html)
        # Inside the box that holds the image (positioned, so the button is placed on it), after the picture itself.
        self.assertRegex(html, r'(?s)<div id="promotion-image" class="relative [^"]*">.*<img .*Buy Tickets</a>\s*</div>')
        self.assertIn("btn btn-primary btn-md absolute bottom-[30px] left-1/2 -translate-x-1/2", html)  # centred, 30px up
        self.assertLess(html.index("<img"), html.index("Buy Tickets"))

    def test_the_image_box_has_the_blocks_size_so_the_button_is_centred_on_the_image(self):
        from home.models import Block

        self.ticketed("Show", 5)
        for size, expected in (("small", "max-w-xs"), ("medium", "max-w-md"), ("large", "max-w-2xl")):
            block = Block.objects.create(name=f"Promo {size}", block_type="promotion", image_size=size)
            self.assertRegex(self.shown(block), rf'<div id="promotion-image" class="relative mx-auto w-full {expected}"')
        full = Block.objects.create(name="Promo full", block_type="promotion", image_size="full")
        self.assertRegex(self.shown(full), r'<div id="promotion-image" class="relative mx-auto w-full "')

    def test_a_linked_image_does_not_hold_the_button_in_its_link(self):
        from home.models import Block

        self.ticketed("Show", 5)
        block = Block.objects.create(name="Linked promo", block_type="promotion", url="/page/about/")
        html = self.shown(block)
        link = html[html.index('<a href="/page/about/"'):html.index("</a>", html.index('<a href="/page/about/"'))]
        self.assertIn("<img", link)
        self.assertNotIn("Buy Tickets", link)  # no link inside a link

    def test_no_button_when_the_event_has_no_ticket_site(self):
        self.production("Show", days=5, images=[("show-promo", "promotion", True)])
        html = self.shown()
        self.assertIn("show-promo.jpg", html)
        self.assertNotIn("Buy Tickets", html)
        self.assertNotIn("mb-8", html)  # and no extra space

    def test_no_button_when_the_ticket_site_has_no_address(self):
        self.ticketed("Show", 5, url="")
        self.assertNotIn("Buy Tickets", self.shown())

    def test_the_button_uses_the_event_of_the_next_performance(self):
        from backstage.models import Event, EventDateTime, TicketSite

        show = self.ticketed("Show", 20, url="https://tickets.example.com/later")
        sooner = Event.objects.create(
            title="Preview", event_type="performance", ticket_site=TicketSite.objects.create(name="Preview", url="https://tickets.example.com/preview")
        )
        sooner.productions.add(show)
        EventDateTime.objects.create(event=sooner, datetime=timezone.now() + timedelta(days=3))
        html = self.shown()
        self.assertIn("https://tickets.example.com/preview", html)
        self.assertNotIn("/later", html)

    def test_other_kinds_of_event_do_not_supply_the_button(self):
        from backstage.models import Event, EventDateTime, TicketSite

        show = self.production("Show", days=10, images=[("show-promo", "promotion", True)])
        audition = Event.objects.create(
            title="Auditions", event_type="audition", ticket_site=TicketSite.objects.create(name="Odd", url="https://tickets.example.com/audition")
        )
        audition.productions.add(show)
        EventDateTime.objects.create(event=audition, datetime=timezone.now() + timedelta(days=2))
        self.assertNotIn("Buy Tickets", self.shown())

    def test_no_button_without_an_image_to_show(self):
        from backstage.models import Event, EventDateTime, TicketSite

        production = Production.objects.create(title="No poster")
        event = Event.objects.create(title="Run", event_type="performance", ticket_site=TicketSite.objects.create(name="T", url="https://tickets.example.com/x"))
        event.productions.add(production)
        EventDateTime.objects.create(event=event, datetime=timezone.now() + timedelta(days=4))
        self.assertEqual(self.shown().strip(), "")
