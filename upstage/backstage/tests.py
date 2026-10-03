from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from backstage.forms import ProductionTeamForm
from backstage.models import Cast, Person, Production, ProductionTeam, Role


class ProductionTeamFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        actor, director = Role.objects.get_or_create(name="Actor")[0], Role.objects.get_or_create(name="Director")[0]
        make = lambda first, last, *roles: Person.objects.create(first_name=first, last_name=last)
        cls.zed = make("Zoe", "Zed")
        cls.zed.roles.add(director)
        cls.abel = make("Abe", "Abel")  # no roles yet: still a possible team member
        cls.baker = make("Bea", "Baker")
        cls.baker.roles.add(director, actor)  # an actor who also directs
        cls.actor_only = make("Al", "Actor")
        cls.actor_only.roles.add(actor)
        cls.divya = make("Divya", "")  # known by one name
        cls.divya.roles.add(director)
        cls.production = Production.objects.create(title="A Play")

    def people(self, **kwargs):
        form = ProductionTeamForm(**kwargs)
        return list(form.fields["person"].queryset)

    def test_alphabetical_by_first_name_and_actors_left_out(self):
        # Abe, Bea, Divya, Zoe
        self.assertEqual(self.people(), [self.abel, self.baker, self.divya, self.zed])

    def test_sorted_by_first_name_not_surname(self):
        zack = Person.objects.create(first_name="Zack", last_name="Aaron")  # surname sorts first, first name last
        self.assertEqual(self.people()[-2:], [zack, self.zed])  # Zack before Zoe

    def test_someone_already_on_the_team_stays_when_editing(self):
        member = ProductionTeam.objects.create(
            production=self.production, person=self.actor_only, role=Role.objects.get(name="Director")
        )
        self.assertIn(self.actor_only, self.people(instance=member))
        self.assertNotIn(self.actor_only, self.people())

    def test_team_page_dropdown(self):
        self.client.force_login(CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!"))
        response = self.client.get(reverse("production-team", args=[self.production.pk]))
        self.assertContains(response, "Zoe Zed")
        self.assertNotContains(response, "Al Actor")
        self.assertContains(response, "People with only an Actor role are omitted from the list")


PLAYS = [
    {  # a radio play with no cast
        "title": "Coffee", "raw_text": "Coffee. Steve Infield as James, Gary Ward as Chris. Written by Peter Bridge, Directed by Sahera Chohan.",
        "text": "", "listen_url": "x",
    },
    {  # one that already has a cast
        "title": "Jumpers", "raw_text": "Jumpers - Blurb. Rita played by Mills Ross, Paul played by Dave Andrew, Written by A.", "text": "", "listen_url": "x",
    },
    {  # no such production
        "title": "Not In The Database", "raw_text": "Starring Ann Other as Someone. Written by A.", "text": "", "listen_url": "x",
    },
]


class ImportBrooklandsCastTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.coffee = Production.objects.create(title="Coffee", type=Production.ProductionType.RADIO)
        cls.jumpers = Production.objects.create(title="Jumpers", type=Production.ProductionType.RADIO)
        cls.stage = Production.objects.create(title="Stage Coffee", type=Production.ProductionType.STAGE)
        Cast.objects.create(production=cls.jumpers, character_name="Rita")
        cls.steve = Person.objects.create(first_name="Steve", last_name="Infield")

    def run_command(self, *args):
        out = StringIO()
        with mock.patch("scraper.scrape.brooklands_plays", return_value=PLAYS):
            call_command("import_brooklands_cast", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_changes_nothing_but_reports(self):
        output = self.run_command("--dry-run")
        self.assertIn("Would change 1 productions", output)
        self.assertIn("James: Steve Infield", output)
        self.assertFalse(self.coffee.cast.exists())
        self.assertFalse(Person.objects.filter(last_name="Ward").exists())
        self.assertFalse(Role.objects.filter(name="Actor").exists())

    def test_adds_a_cast_creating_people_and_the_actor_role(self):
        output = self.run_command()
        self.assertIn("Changed 1 productions", output)
        self.assertEqual(
            sorted((c.character_name, str(c.actor)) for c in self.coffee.cast.all()),
            [("Chris", "Gary Ward"), ("James", "Steve Infield")],
        )
        actor = Role.objects.get(name="Actor")
        self.assertIn(actor, self.steve.roles.all())  # an existing person is made an actor
        self.assertIn(actor, Person.objects.get(first_name="Gary", last_name="Ward").roles.all())  # a new person
        self.assertIn("Gary Ward (1)", output)  # new people are listed
        self.assertEqual(self.steve, Person.objects.get(first_name="Steve"))  # not duplicated

    def test_a_production_with_a_cast_is_left_alone(self):
        self.run_command()
        self.assertEqual([c.character_name for c in self.jumpers.cast.all()], ["Rita"])

    def test_running_again_changes_nothing(self):
        self.run_command()
        output = self.run_command()
        self.assertIn("Changed 0 productions", output)
        self.assertEqual(self.coffee.cast.count(), 2)

    def test_unmatched_plays_are_listed(self):
        self.assertIn("Not In The Database", self.run_command("--dry-run"))


    def test_team_members_that_are_missing_are_added_and_existing_ones_are_not(self):
        writer = Role.objects.create(name="Writer")
        bridge = Person.objects.create(first_name="Peter", last_name="Bridge")
        ProductionTeam.objects.create(production=self.coffee, person=bridge, role=writer)  # already the writer
        output = self.run_command()
        team = sorted((m.role.name, str(m.person)) for m in self.coffee.team.all())
        self.assertEqual(team, [("Director", "Sahera Chohan"), ("Writer", "Peter Bridge")])
        self.assertIn("Team: Director: Sahera Chohan", output)
        self.assertNotIn("Team: Writer", output)
        self.assertEqual(Person.objects.filter(last_name="Bridge").count(), 1)
        self.assertTrue(Role.objects.filter(name="Director").exists())
        self.assertIn(Role.objects.get(name="Director"), Person.objects.get(last_name="Chohan").roles.all())

    def test_team_is_added_even_when_the_production_already_has_a_cast(self):
        # Jumpers has a cast, so it gets no new cast, but a team can still be added to.
        plays = [{"title": "Jumpers", "raw_text": "Jumpers - Blurb. Written and directed by Dave Andrew. Rita played by A B.", "text": "", "listen_url": "x"}]
        with mock.patch("scraper.scrape.brooklands_plays", return_value=plays):
            call_command("import_brooklands_cast", stdout=StringIO())
        self.assertEqual([c.character_name for c in self.jumpers.cast.all()], ["Rita"])
        self.assertEqual(sorted(m.role.name for m in self.jumpers.team.all()), ["Director", "Writer"])

    def test_dry_run_adds_no_team(self):
        self.run_command("--dry-run")
        self.assertFalse(ProductionTeam.objects.filter(production=self.coffee).exists())


class SeparateThemesTests(TestCase):
    """The backstage pages and the public pages have their own themes; the backstage lets you choose both."""

    PASSWORD = "a-Long-pa55word!"

    @classmethod
    def setUpTestData(cls):
        from home.models import WebPage

        cls.user = CustomUser.objects.create_user("member", "member@example.com", cls.PASSWORD)
        WebPage.objects.create(title="Home", slug="home")  # the home view shows the page with this slug

    def choose(self, theme, **extra):
        self.client.force_login(self.user)
        return self.client.post(reverse("public-theme"), {"public_theme": theme, **extra})

    def public_page(self):
        return self.client.get(reverse("auditions")).content.decode()

    def test_the_themes_are_one_list(self):
        from backstage.themes import THEMES, is_theme

        names = [value for value, _ in THEMES]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(names[:2], ["upstage", "upstage-dark"])
        self.assertTrue(is_theme("abyss") and is_theme("dark") and is_theme("upstage"))
        self.assertFalse(is_theme("") or is_theme("nonsense") or is_theme("abyss; x"))
        self.assertEqual(len(names), 37)

    def test_the_public_pages_start_on_automatic(self):
        html = self.public_page()
        self.assertIn("prefers-color-scheme", html)  # Upstage, or Upstage dark on a dark device
        self.assertIn('<html lang="en">', html)  # no theme fixed on the <html> tag
        self.assertNotIn("localStorage", html)  # and never a backstage person's own choice

    def test_choosing_a_public_theme_fixes_it_for_every_visitor(self):
        response = self.choose("abyss")
        self.assertEqual(response.status_code, 302)
        self.client.logout()  # a visitor
        html = self.public_page()
        self.assertIn('<html lang="en" data-theme="abyss">', html)
        self.assertNotIn("prefers-color-scheme", html)
        self.assertNotIn("localStorage", html)  # no personal choice on the public pages

    def test_it_applies_to_all_the_public_pages(self):
        self.choose("cupcake")
        self.client.logout()
        for name in ("home", "auditions", "public-actors", "radio-archive"):
            self.assertIn('data-theme="cupcake"', self.client.get(reverse(name)).content.decode(), name)

    def test_the_backstage_pages_keep_their_own_theme(self):
        self.choose("abyss")
        html = self.client.get(reverse("production-list")).content.decode()
        self.assertIn("localStorage.getItem('theme')", html)  # this browser's own choice, as before
        self.assertNotIn('<html lang="en" data-theme="abyss">', html)  # the public theme is not forced on the backstage

    def test_automatic_goes_back_to_the_default(self):
        self.choose("abyss")
        self.choose("")
        self.client.logout()
        html = self.public_page()
        self.assertNotIn('data-theme="abyss"', html)
        self.assertIn("prefers-color-scheme", html)

    def test_only_a_known_theme_can_be_chosen(self):
        self.choose("nord")
        self.choose("<script>")
        self.choose("not-a-theme")
        from backstage.models import SiteSettings

        self.assertEqual(SiteSettings.load().public_theme, "nord")  # the bad choices changed nothing

    def test_choosing_needs_a_login_and_a_post(self):
        self.assertEqual(self.client.post(reverse("public-theme"), {"public_theme": "abyss"}).status_code, 302)  # to the login page
        from backstage.models import SiteSettings

        self.assertEqual(SiteSettings.load().public_theme, "")
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("public-theme")).status_code, 405)

    def test_it_goes_back_to_where_you_were_but_only_on_this_site(self):
        response = self.choose("abyss", next="/backstage/person/")
        self.assertEqual(response["Location"], "/backstage/person/")
        response = self.choose("abyss", next="https://evil.example/steal")
        self.assertEqual(response["Location"], reverse("production-list"))

    def test_the_backstage_navbar_offers_both(self):
        self.choose("dracula")
        html = self.client.get(reverse("production-list")).content.decode()
        self.assertIn("The theme of these backstage pages", html)
        self.assertIn("The theme visitors see on the public pages", html)
        self.assertEqual(html.count('class="theme-controller'), 37)  # the backstage list
        self.assertEqual(html.count('name="public_theme"'), 38)  # the public list: automatic, then every theme
        self.assertIn(f'action="{reverse("public-theme")}"', html)
        # The public choice is ticked, and its radios must not be theme-controllers (that would restyle the backstage).
        self.assertRegex(html, r'name="public_theme" value="dracula"[^>]*checked')
        self.assertNotRegex(html, r'theme-controller[^>]*name="public_theme"|name="public_theme"[^>]*theme-controller')

    def test_automatic_is_ticked_until_a_theme_is_chosen(self):
        self.client.force_login(self.user)
        html = self.client.get(reverse("production-list")).content.decode()
        self.assertRegex(html, r'name="public_theme" value=""[^>]*checked')

    def test_the_public_navbar_has_no_theme_picker(self):
        self.assertNotIn('name="public_theme"', self.public_page())
        self.assertNotIn("theme-controller", self.public_page())


class ActorListTests(TestCase):
    PASSWORD = "a-Long-pa55word!"

    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user("member", "member@example.com", cls.PASSWORD)
        cls.actor = Role.objects.get_or_create(name="Actor")[0]
        # Surname order: Abbott, Brown, Divya (one name), Zane. First name order: Alice, Bea, Divya, Zack.
        for first, last in (("Zack", "Abbott"), ("Alice", "Zane"), ("Bea", "Brown"), ("Divya", "")):
            Person.objects.create(first_name=first, last_name=last).roles.add(cls.actor)
        Person.objects.create(first_name="Not", last_name="Anactor")  # no Actor role: never listed

    def setUp(self):
        self.client.force_login(self.user)

    def names(self, query=""):
        response = self.client.get(reverse("actor-list") + query)
        self.assertEqual(response.status_code, 200)
        return [person.first_name for person in response.context["actors"]]

    def test_sorted_by_last_name_by_default(self):
        self.assertEqual(self.names(), ["Zack", "Bea", "Divya", "Alice"])

    def test_sorted_by_first_name(self):
        self.assertEqual(self.names("?sort=first"), ["Alice", "Bea", "Divya", "Zack"])

    def test_the_sort_works_in_the_details_view_too(self):
        self.assertEqual(self.names("?view=details&sort=first"), ["Alice", "Bea", "Divya", "Zack"])
        self.assertEqual(self.names("?view=details"), ["Zack", "Bea", "Divya", "Alice"])

    def test_an_unknown_sort_means_last_name(self):
        self.assertEqual(self.names("?sort=nonsense"), ["Zack", "Bea", "Divya", "Alice"])
        self.assertEqual(self.client.get(reverse("actor-list") + "?sort=nonsense").context["sort"], "last")

    def test_the_sort_choices_keep_the_view_and_the_views_keep_the_sort(self):
        html = self.client.get(reverse("actor-list") + "?sort=first&view=details").content.decode()
        self.assertIn('href="?sort=first&amp;view=details"', html)  # First name, staying on details
        self.assertIn('href="?view=details"', html)  # Last name, staying on details
        self.assertIn('href="?sort=first"', html)  # Photos, keeping the sort
        self.assertRegex(html, r'href="\?sort=first&amp;view=details" class="tab tab-active"')  # first name is the active sort
        photos = self.client.get(reverse("actor-list") + "?sort=first").content.decode()
        self.assertIn('href="?view=details&amp;sort=first"', photos)  # Details, keeping the sort

    def test_there_is_a_new_actor_button(self):
        html = self.client.get(reverse("actor-list")).content.decode()
        self.assertIn(f'href="{reverse("person-create")}?role=Actor"', html)
        self.assertIn("New actor", html)

    def test_the_new_actor_form_has_the_actor_role_ticked(self):
        response = self.client.get(reverse("person-create") + "?role=Actor")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["form"].initial["roles"]), [self.actor])
        self.assertRegex(response.content.decode(), rf'value="{self.actor.pk}"[^>]*checked')

    def test_a_new_person_has_no_role_ticked_without_the_button(self):
        response = self.client.get(reverse("person-create"))
        self.assertNotIn("roles", response.context["form"].initial)

    def test_an_unknown_role_in_the_link_is_ignored(self):
        response = self.client.get(reverse("person-create") + "?role=Nonsense")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["form"].initial["roles"]), [])

    def test_creating_an_actor_from_the_button(self):
        response = self.client.post(reverse("person-create") + "?role=Actor", {
            "first_name": "New", "last_name": "Actor", "roles": [self.actor.pk],
        })
        self.assertEqual(response.status_code, 302)
        person = Person.objects.get(first_name="New", last_name="Actor")
        self.assertIn(self.actor, person.roles.all())
        self.assertIn("New", [p.first_name for p in self.client.get(reverse("actor-list")).context["actors"]])


class ImageLibraryOrderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from backstage.models import Image

        cls.user = CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!")
        make = lambda description, name, kind="base": Image.objects.create(description=description, image=f"images/{name}", image_type=kind)
        # Created in an order that is neither alphabetical nor reverse alphabetical.
        cls.mango = make("mango", "1.jpg")
        cls.apple = make("Apple", "2.jpg", "headshot")
        cls.cherry = make("cherry", "3.jpg")
        cls.banana = make("Banana", "4.jpg", "headshot")
        cls.unnamed = make("", "kiwi.jpg")  # no description: listed by its file name, as its card shows it ("images/kiwi.jpg")

    def setUp(self):
        self.client.force_login(self.user)

    def ids(self, query=""):
        response = self.client.get(reverse("image-list") + query)
        self.assertEqual(response.status_code, 200)
        return [image.pk for image in response.context["object_list"]]

    def test_images_are_sorted_by_description_ignoring_case(self):
        # Apple, Banana, cherry, images/kiwi.jpg (no description: sorted under "i"), mango
        self.assertEqual(self.ids(), [self.apple.pk, self.banana.pk, self.cherry.pk, self.unnamed.pk, self.mango.pk])

    def test_the_sort_holds_when_filtered_by_type(self):
        self.assertEqual(self.ids("?type=headshot"), [self.apple.pk, self.banana.pk])

    def test_images_with_the_same_description_keep_a_steady_order(self):
        from backstage.models import Image

        first = Image.objects.create(description="Same", image="images/a.jpg")
        second = Image.objects.create(description="same", image="images/b.jpg")
        order = self.ids()
        self.assertLess(order.index(first.pk), order.index(second.pk))

    def test_pages_continue_the_alphabetical_order(self):
        from backstage.models import Image

        for number in range(30):
            Image.objects.create(description=f"Zzz {number:02d}", image=f"images/z{number}.jpg")
        first_page = self.ids()
        second_page = self.ids("?page=2")
        names = [Image.objects.get(pk=pk).description or "images/kiwi.jpg" for pk in first_page + second_page]
        self.assertEqual([n.lower() for n in names], sorted(n.lower() for n in names))
        self.assertEqual(len(first_page), 24)

    def test_name_is_the_default_sort(self):
        response = self.client.get(reverse("image-list"))
        self.assertEqual(response.context["current_sort"], "name")

    def test_newest_first_is_an_option(self):
        # Created: mango, Apple, cherry, Banana, then the unnamed one: newest first is the reverse of that.
        self.assertEqual(self.ids("?sort=newest"), [self.unnamed.pk, self.banana.pk, self.cherry.pk, self.apple.pk, self.mango.pk])
        self.assertEqual(self.client.get(reverse("image-list") + "?sort=newest").context["current_sort"], "newest")

    def test_an_unknown_sort_means_name(self):
        self.assertEqual(self.ids("?sort=nonsense"), self.ids())
        self.assertEqual(self.client.get(reverse("image-list") + "?sort=nonsense").context["current_sort"], "name")

    def test_newest_first_works_with_the_type_filter(self):
        self.assertEqual(self.ids("?type=headshot&sort=newest"), [self.banana.pk, self.apple.pk])

    @staticmethod
    def link_queries(html, text):
        """The query (as a dict) of the tab or link whose text is `text`."""
        import re
        from urllib.parse import parse_qs

        match = re.search(r'<a [^>]*href="\?([^"]*)"[^>]*>\s*' + re.escape(text) + r"\s*</a>", html)
        assert match, text
        return {key: values[0] for key, values in parse_qs(match.group(1).replace("&amp;", "&")).items()}

    def test_the_sort_choices_keep_the_type_and_the_types_keep_the_sort(self):
        html = self.client.get(reverse("image-list") + "?type=headshot&sort=newest").content.decode()
        self.assertEqual(self.link_queries(html, "Name"), {"type": "headshot"})  # Name, keeping the type
        self.assertEqual(self.link_queries(html, "Newest first"), {"type": "headshot", "sort": "newest"})
        self.assertEqual(self.link_queries(html, "Base"), {"type": "base", "sort": "newest"})  # another type, keeping the sort
        self.assertEqual(self.link_queries(html, "All"), {"sort": "newest"})
        self.assertRegex(html, r'class="tab tab-active"[^>]*>\s*Headshot|Headshot\s*</a>')
        by_name = self.client.get(reverse("image-list") + "?type=headshot").content.decode()
        self.assertEqual(self.link_queries(by_name, "Base"), {"type": "base"})  # no sort in the links when it is the default

    def test_the_page_links_keep_the_sort_and_type(self):
        from backstage.models import Image

        for number in range(30):
            Image.objects.create(description=f"Extra {number:02d}", image=f"images/e{number}.jpg", image_type="headshot")
        html = self.client.get(reverse("image-list") + "?type=headshot&sort=newest").content.decode()
        self.assertIn("type=headshot&amp;sort=newest&amp;page=2", html)
        second = self.client.get(reverse("image-list") + "?type=headshot&sort=newest&page=2")
        self.assertIn("type=headshot&amp;sort=newest&amp;page=1", second.content.decode())
        newest = [image.pk for image in Image.objects.filter(image_type="headshot").order_by("-id")]
        self.assertEqual([i.pk for i in second.context["object_list"]], newest[24:])


class HeadshotUploadTests(TestCase):
    """Uploading a photo from the person form starts on the headshot type."""

    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!")
        cls.person = Person.objects.create(first_name="Ann", last_name="Actor")

    def setUp(self):
        self.client.force_login(self.user)

    @staticmethod
    def selected_type(response):
        import re

        return re.findall(r'<option value="(\w+)" selected', response.content.decode())

    def test_the_new_person_form_links_to_the_uploader_as_a_headshot(self):
        for url, target in ((reverse("person-create"), "new"), (reverse("person-update", args=[self.person.pk]), self.person.pk)):
            html = self.client.get(url).content.decode()
            self.assertIn(f'href="{reverse("image-create")}?type=headshot&amp;for_person={target}"', html, url)

    def test_the_uploader_starts_on_headshot_from_that_link(self):
        response = self.client.get(reverse("image-create") + "?type=headshot")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.selected_type(response), ["headshot"])

    def test_the_uploader_starts_on_the_default_type_otherwise(self):
        self.assertEqual(self.selected_type(self.client.get(reverse("image-create"))), ["base"])

    def test_an_unknown_type_is_ignored(self):
        self.assertEqual(self.selected_type(self.client.get(reverse("image-create") + "?type=nonsense")), ["base"])

    def test_the_type_can_still_be_changed_when_uploading(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from io import BytesIO
        from PIL import Image as PILImage

        buffer = BytesIO()
        PILImage.new("RGB", (4, 4), "white").save(buffer, "PNG")
        import tempfile
        from django.test import override_settings

        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            response = self.client.post(reverse("image-create") + "?type=headshot", {
                "image": SimpleUploadedFile("face.png", buffer.getvalue(), content_type="image/png"),
                "description": "A face", "image_type": "gallery",
            })
        self.assertEqual(response.status_code, 302)
        from backstage.models import Image

        self.assertEqual(Image.objects.get(description="A face").image_type, "gallery")  # the choice is only a starting point

    def test_uploading_from_a_production_is_unchanged(self):
        production = Production.objects.create(title="A Play")
        response = self.client.get(reverse("image-create") + f"?production={production.pk}")
        self.assertEqual(self.selected_type(response), ["base"])
        self.assertEqual(response.context["production"], production)


class UploadFromPersonFormTests(TestCase):
    """Uploading a photo from a person's form: the description starts as their name, and you come back to the form."""

    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!")
        cls.person = Person.objects.create(first_name="Ann", last_name="Actor")

    def setUp(self):
        self.client.force_login(self.user)

    def uploader(self, query):
        return self.client.get(reverse("image-create") + query)

    def upload(self, **data):
        """Post a (tiny, temporary) image to the uploader, as the uploader's form would."""
        import tempfile
        from io import BytesIO

        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        from PIL import Image as PILImage

        buffer = BytesIO()
        PILImage.new("RGB", (4, 4), "white").save(buffer, "PNG")
        fields = {"image": SimpleUploadedFile("face.png", buffer.getvalue(), content_type="image/png"), "image_type": "headshot"}
        fields.update(data)
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            return self.client.post(reverse("image-create"), fields)

    def test_the_description_starts_as_the_persons_name(self):
        response = self.uploader("?type=headshot&for_person=new&name=Ann+Actor")
        self.assertEqual(response.context["form"].initial["description"], "Ann Actor")
        self.assertEqual(response.context["form"].initial["image_type"], "headshot")
        self.assertContains(response, 'value="Ann Actor"')

    def test_the_name_is_ignored_unless_it_came_from_a_person_form(self):
        response = self.uploader("?name=Ann+Actor")
        self.assertNotIn("description", response.context["form"].initial)

    def test_no_name_leaves_the_description_empty(self):
        response = self.uploader("?type=headshot&for_person=new")
        self.assertNotIn("description", response.context["form"].initial)

    def test_the_uploader_remembers_where_it_came_from(self):
        response = self.uploader("?type=headshot&for_person=new")
        self.assertContains(response, '<input type="hidden" name="for_person" value="new" />')
        self.assertContains(response, f'href="{reverse("person-create")}?restore=1" class="btn btn-ghost"')  # Cancel goes back to the form
        response = self.uploader(f"?type=headshot&for_person={self.person.pk}")
        self.assertContains(response, f'value="{self.person.pk}"')
        self.assertContains(response, f'href="{reverse("person-update", args=[self.person.pk])}?restore=1" class="btn btn-ghost"')

    def test_uploading_from_the_new_person_form_comes_back_to_it_with_the_photo_chosen(self):
        from backstage.models import Image

        response = self.upload(description="Ann Actor", for_person="new")
        image = Image.objects.get(description="Ann Actor")
        self.assertEqual(image.image_type, "headshot")
        self.assertEqual(response["Location"], f"{reverse('person-create')}?restore=1&image={image.pk}")

    def test_uploading_from_an_existing_persons_form_comes_back_to_it(self):
        from backstage.models import Image

        response = self.upload(description="Ann Actor", for_person=str(self.person.pk))
        image = Image.objects.get(description="Ann Actor")
        self.assertEqual(response["Location"], f"{reverse('person-update', args=[self.person.pk])}?restore=1&image={image.pk}")

    def test_an_upload_not_from_a_person_form_still_goes_to_the_library(self):
        for extra in ({}, {"for_person": "abc"}, {"for_person": "999999"}):
            response = self.upload(description="Plain", **extra)
            self.assertEqual(response["Location"], reverse("image-list"), extra)

    def test_the_person_form_opens_with_the_new_photo_chosen(self):
        from backstage.models import Image

        photo = Image.objects.create(description="Ann Actor", image="images/ann.jpg", image_type="headshot")
        for url in (reverse("person-create"), reverse("person-update", args=[self.person.pk])):
            response = self.client.get(f"{url}?restore=1&image={photo.pk}")
            self.assertEqual(response.context["form"].initial["image"], photo.pk, url)
            self.assertRegex(response.content.decode(), rf'<option value="{photo.pk}" selected>', url)

    def test_only_a_headshot_can_be_chosen_this_way(self):
        from backstage.models import Image

        other = Image.objects.create(description="Poster", image="images/poster.jpg", image_type="promotion")
        for value in (str(other.pk), "999999", "abc", ""):
            response = self.client.get(f"{reverse('person-create')}?image={value}")
            self.assertNotIn("image", response.context["form"].initial, value)

    def test_the_person_form_has_what_it_needs_to_keep_what_was_typed(self):
        html = self.client.get(reverse("person-create")).content.decode()
        for needle in ('id="person-form"', 'id="upload-photo-link"', "person-form-draft", "params.has('restore')", "encodeURIComponent(name)"):
            self.assertIn(needle, html, needle)


class ImageSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from backstage.models import Image

        cls.user = CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!")
        make = lambda description, name, kind="base": Image.objects.create(description=description, image=f"images/{name}", image_type=kind)
        cls.ann = make("Ann Actor", "ann.jpg", "headshot")
        cls.annie = make("Annie Smith", "annie-smith.jpg", "headshot")
        cls.poster = make("Hamlet poster", "hamlet-2026.png", "promotion")
        cls.unnamed = make("", "spotlight-hero.jpg")  # no description: found by its file name
        cls.other = make("Zed Writer", "zed.jpg", "headshot")

    def setUp(self):
        self.client.force_login(self.user)

    def found(self, query):
        response = self.client.get(reverse("image-list") + query)
        self.assertEqual(response.status_code, 200)
        return sorted(image.pk for image in response.context["object_list"])

    def pks(self, *images):
        return sorted(image.pk for image in images)

    def test_search_finds_images_by_description_ignoring_case(self):
        self.assertEqual(self.found("?q=ann"), self.pks(self.ann, self.annie))
        self.assertEqual(self.found("?q=ANNIE"), self.pks(self.annie))
        self.assertEqual(self.found("?q=poster"), self.pks(self.poster))

    def test_search_finds_images_by_file_name(self):
        self.assertEqual(self.found("?q=spotlight"), self.pks(self.unnamed))
        self.assertEqual(self.found("?q=2026"), self.pks(self.poster))
        self.assertEqual(self.found("?q=.png"), self.pks(self.poster))

    def test_every_word_has_to_match(self):
        self.assertEqual(self.found("?q=ann+smith"), self.pks(self.annie))  # "ann" and "smith"
        self.assertEqual(self.found("?q=smith+ann"), self.pks(self.annie))  # in any order
        self.assertEqual(self.found("?q=ann+poster"), [])

    def test_a_blank_or_spaces_only_search_shows_everything(self):
        everything = self.pks(self.ann, self.annie, self.poster, self.unnamed, self.other)
        self.assertEqual(self.found("?q="), everything)
        self.assertEqual(self.found("?q=+++"), everything)

    def test_special_characters_are_searched_for_not_treated_as_patterns(self):
        for query in ("%", "_", "'", '"', "\\", "<script>"):
            self.assertEqual(self.found(f"?q={query}"), [], query)

    def test_search_works_with_the_type_filter_and_the_sort(self):
        self.assertEqual(self.found("?q=ann&type=headshot"), self.pks(self.ann, self.annie))
        self.assertEqual(self.found("?q=poster&type=headshot"), [])
        response = self.client.get(reverse("image-list") + "?q=ann&sort=newest")
        self.assertEqual([i.pk for i in response.context["object_list"]], [self.annie.pk, self.ann.pk])
        response = self.client.get(reverse("image-list") + "?q=ann")
        self.assertEqual([i.pk for i in response.context["object_list"]], [self.ann.pk, self.annie.pk])  # by name

    def test_the_search_box_keeps_its_text_the_type_and_the_sort(self):
        html = self.client.get(reverse("image-list") + "?q=ann&type=headshot&sort=newest").content.decode()
        self.assertIn('name="q" value="ann"', html)
        self.assertIn('<input type="hidden" name="type" value="headshot" />', html)
        self.assertIn('<input type="hidden" name="sort" value="newest" />', html)
        self.assertIn("2 images matching", html)

    def test_the_search_text_is_escaped(self):
        html = self.client.get(reverse("image-list") + '?q="><script>alert(1)</script>').content.decode()
        self.assertNotIn("<script>alert(1)", html)

    def test_the_other_links_keep_the_search_and_clear_removes_it(self):
        html = self.client.get(reverse("image-list") + "?q=ann&type=headshot").content.decode()
        for text, expected in (("Newest first", {"q": "ann", "type": "headshot", "sort": "newest"}),
                               ("Base", {"q": "ann", "type": "base"}), ("All", {"q": "ann"}), ("Clear", {"type": "headshot"})):
            self.assertEqual(ImageLibraryOrderTests.link_queries(html, text), expected, text)

    def test_no_clear_link_without_a_search(self):
        self.assertNotIn(">Clear<", self.client.get(reverse("image-list")).content.decode().replace("\n", "").replace("  ", ""))

    def test_nothing_found_says_so(self):
        response = self.client.get(reverse("image-list") + "?q=nothing-like-this")
        self.assertContains(response, "match &ldquo;nothing-like-this&rdquo;")
        self.assertContains(response, "Clear the search")
        self.assertNotContains(response, "Upload the first one")

    def test_an_empty_library_still_offers_to_upload(self):
        from backstage.models import Image

        Image.objects.all().delete()
        self.assertContains(self.client.get(reverse("image-list")), "Upload the first one")

    def test_the_page_links_keep_the_search(self):
        from backstage.models import Image

        for number in range(30):
            Image.objects.create(description=f"Chorus {number:02d}", image=f"images/c{number}.jpg")
        first = self.client.get(reverse("image-list") + "?q=chorus")
        self.assertEqual(first.context["paginator"].count, 30)
        self.assertEqual(len(first.context["object_list"]), 24)
        self.assertIn("q=chorus&amp;page=2", first.content.decode())
        second = self.client.get(reverse("image-list") + "?q=chorus&page=2")
        self.assertEqual(len(second.context["object_list"]), 6)
        self.assertIn("q=chorus&amp;page=1", second.content.decode())

    def test_searching_goes_back_to_the_first_page(self):
        from backstage.models import Image

        for number in range(30):
            Image.objects.create(description=f"Chorus {number:02d}", image=f"images/c{number}.jpg")
        # The search form has no page field, so a new search starts at page 1 even from page 2.
        html = self.client.get(reverse("image-list") + "?q=chorus&page=2").content.decode()
        form = html[html.index('<form method="get"'):html.index("</form>")]
        self.assertNotIn('name="page"', form)

