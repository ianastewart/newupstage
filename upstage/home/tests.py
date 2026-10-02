from datetime import timedelta

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
