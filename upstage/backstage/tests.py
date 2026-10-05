from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, TransactionTestCase
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
        self.assertIn(f'href="{reverse("actor-new")}"', html)  # the three step wizard
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

    def test_each_headshot_fills_its_card_and_every_card_is_the_same_shape(self):
        from backstage.models import Image

        photo = Image.objects.create(description="Ann", image="images/ann.jpg", image_type="headshot")
        Person.objects.filter(first_name="Alice").update(image=photo)
        html = self.client.get(reverse("actor-list")).content.decode()
        import re

        cards = re.split(r'<a href="/backstage/person/\d+/', html)[1:]  # one piece for each actor's card
        self.assertEqual(len(cards), 4)
        for card in cards:
            self.assertIn('<figure class="aspect-[4/5] w-full bg-base-300">', card)  # 4:5, as wide as the card
        with_photo = [card for card in cards if "<img" in card]
        self.assertEqual(len(with_photo), 1)
        self.assertIn('class="h-full w-full object-cover"', with_photo[0])  # fills the card, no bars round it
        self.assertNotIn("object-contain", html.split("</form>")[-1])  # no more shrinking the photo inside a square
        self.assertNotIn("aspect-square", html.split("</form>")[-1])
        # A card with no photo (initials) is the same 4:5 shape, so the grid lines up.
        no_photo = next(card for card in cards if "<img" not in card)
        self.assertIn('class="flex h-full w-full items-center justify-center bg-neutral', no_photo)


class ImageLibraryOrderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from backstage.models import Image

        cls.user = CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!")
        make = lambda description, name, kind="production": Image.objects.create(description=description, image=f"images/{name}", image_type=kind)
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
        self.assertEqual(self.link_queries(html, "Production"), {"type": "production", "sort": "newest"})  # another type, keeping the sort
        self.assertEqual(self.link_queries(html, "All"), {"sort": "newest"})
        self.assertRegex(html, r'class="tab tab-active"[^>]*>\s*Headshot|Headshot\s*</a>')
        by_name = self.client.get(reverse("image-list") + "?type=headshot").content.decode()
        self.assertEqual(self.link_queries(by_name, "Production"), {"type": "production"})  # no sort in the links when it is the default

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
        self.assertEqual(self.selected_type(self.client.get(reverse("image-create"))), ["production"])

    def test_an_unknown_type_is_ignored(self):
        self.assertEqual(self.selected_type(self.client.get(reverse("image-create") + "?type=nonsense")), ["production"])

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
        self.assertEqual(self.selected_type(response), ["production"])
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


    def test_only_production_kinds_are_offered_and_production_is_the_start(self):
        production = Production.objects.create(title="A Play")
        response = self.uploader(f"?production={production.pk}")
        form = response.context["form"]
        self.assertEqual([value for value, _ in form.fields["image_type"].choices], ["production", "promotion", "audition", "gallery"])
        self.assertEqual(form.initial["image_type"], "production")
        self.assertContains(self.client.get(reverse("production-images", args=[production.pk])), "Add image")

    def test_other_kinds_are_refused_and_a_good_one_returns_to_the_production(self):
        from backstage.models import Image

        production = Production.objects.create(title="A Play")
        response = self.upload(production=production.pk, image_type="headshot")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Image.objects.count(), 0)
        response = self.upload(production=production.pk, image_type="gallery")
        self.assertRedirects(response, reverse("production-images", args=[production.pk]))
        self.assertEqual(Image.objects.get().image_type, "gallery")

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
            self.assertRegex(response.content.decode(), rf'<input type="hidden" name="image" value="{photo.pk}"', url)

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
        make = lambda description, name, kind="production": Image.objects.create(description=description, image=f"images/{name}", image_type=kind)
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
                               ("Production", {"q": "ann", "type": "production"}), ("All", {"q": "ann"}), ("Clear", {"type": "headshot"})):
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


class HeadshotResizeTests(TestCase):
    """Headshots are stored 400 wide by 500 high, cropped from the centre, in black and white; other images are left alone."""

    # How bright a pure colour is once converted to grey (the usual weights: 0.299 red, 0.587 green, 0.114 blue).
    RED, GREEN, BLUE = 76, 150, 29

    def setUp(self):
        import tempfile

        from django.test import override_settings

        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        override = override_settings(MEDIA_ROOT=self.media.name)
        override.enable()
        self.addCleanup(override.disable)

    @staticmethod
    def bands(width, height, across=True, fmt="PNG", **save_options):
        """An image in three equal bands, red, green and blue: left to right if `across`, else top to bottom."""
        from io import BytesIO

        from PIL import Image as PILImage

        image = PILImage.new("RGB", (width, height))
        for index, colour in enumerate(((255, 0, 0), (0, 255, 0), (0, 0, 255))):
            if across:
                box = (width * index // 3, 0, width * (index + 1) // 3, height)
            else:
                box = (0, height * index // 3, width, height * (index + 1) // 3)
            image.paste(colour, box)
        buffer = BytesIO()
        image.save(buffer, fmt, **save_options)
        return buffer.getvalue()

    def store(self, data, image_type="headshot", name="photo.png"):
        from django.core.files.base import ContentFile

        from backstage.models import Image

        image = Image(description="test", image_type=image_type)
        image.image.save(name, ContentFile(data), save=True)
        return Image.objects.get(pk=image.pk)

    @staticmethod
    def opened(image):
        from PIL import Image as PILImage

        with PILImage.open(image.image.path) as stored:
            stored.load()
            return stored

    def test_a_headshot_is_stored_400_wide_by_500_high(self):
        for width, height in ((1000, 400), (400, 1200), (400, 500), (900, 900), (3000, 2000), (300, 500)):
            stored = self.opened(self.store(self.bands(width, height), name=f"{width}x{height}.png"))
            self.assertEqual(stored.size, (400, 500), (width, height))

    def test_it_is_cropped_from_the_centre_not_squashed(self):
        # A wide image: red, green, blue from left to right. Scaled to 500 high it is 1500 wide, and the centre 400 is
        # all green (grey 150 once in black and white). A left or squashed crop would show red or blue as well.
        stored = self.opened(self.store(self.bands(1500, 500)))
        for x in (0, 200, 399):
            self.assertEqual(stored.convert("RGB").getpixel((x, 250)), (self.GREEN,) * 3, x)
        # A tall image: red, green, blue from top to bottom: the middle 500 of 1500 is all green.
        stored = self.opened(self.store(self.bands(400, 1500, across=False)))
        for y in (0, 250, 499):
            self.assertEqual(stored.convert("RGB").getpixel((200, y)), (self.GREEN,) * 3, y)

    def test_other_types_of_image_are_not_resized(self):
        from backstage.models import Image

        for image_type in ("production", "promotion", "gallery", "audition", "logo", "other"):
            stored = self.opened(self.store(self.bands(1000, 400), image_type=image_type, name=f"{image_type}.png"))
            self.assertEqual(stored.size, (1000, 400), image_type)

    def test_other_types_keep_their_exact_file(self):
        data = self.bands(1000, 400)
        image = self.store(data, image_type="production")
        with open(image.image.path, "rb") as stored:
            self.assertEqual(stored.read(), data)  # byte for byte

    def test_a_jpeg_stays_a_jpeg_with_a_jpg_name(self):
        image = self.store(self.bands(800, 600, fmt="JPEG"), name="face.jpg")
        self.assertTrue(image.image.name.endswith(".jpg"), image.image.name)
        self.assertEqual(self.opened(image).format, "JPEG")
        self.assertEqual(self.opened(image).size, (400, 500))

    def test_a_png_stays_a_png(self):
        image = self.store(self.bands(800, 600), name="face.png")
        self.assertTrue(image.image.name.endswith(".png"), image.image.name)
        self.assertEqual(self.opened(image).format, "PNG")

    def test_the_photos_metadata_is_removed(self):
        from PIL import Image as PILImage

        exif = PILImage.Exif()
        exif[305] = "Secret Camera App"  # Software
        exif[315] = "Somebody"  # Artist
        data = self.bands(800, 600, fmt="JPEG", exif=exif.tobytes())
        with PILImage.open(__import__("io").BytesIO(data)) as source:
            self.assertEqual(dict(source.getexif()).get(305), "Secret Camera App")  # it was there to begin with
        stored = self.opened(self.store(data, name="face.jpg"))
        self.assertEqual(dict(stored.getexif()), {})

    def test_a_sideways_phone_photo_is_turned_the_right_way_up(self):
        from PIL import Image as PILImage

        # 600 x 300 pixels, marked "rotate 270 to view" (orientation 6): it is a 300 x 600 portrait photo. The red band
        # is on the left of the stored pixels, which is the top of the photo once turned.
        exif = PILImage.Exif()
        exif[274] = 6
        stored = self.opened(self.store(self.bands(600, 300, fmt="JPEG", exif=exif.tobytes()), name="phone.jpg")).convert("RGB")
        self.assertEqual(stored.size, (400, 500))
        top, bottom = stored.getpixel((200, 5)), stored.getpixel((200, 494))
        # Turned clockwise: red, from the left, is now at the top (grey 76) and blue, from the right, at the bottom
        # (grey 29), so it is not left sideways. (JPEG is lossy, so the greys are only nearly exact.)
        self.assertAlmostEqual(top[0], self.RED, delta=6)
        self.assertAlmostEqual(bottom[0], self.BLUE, delta=6)

    def test_a_small_headshot_is_scaled_up_to_fill_the_size(self):
        self.assertEqual(self.opened(self.store(self.bands(30, 50))).size, (400, 500))

    def test_uploading_a_headshot_through_the_uploader_resizes_it(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        user = CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!")
        self.client.force_login(user)
        response = self.client.post(reverse("image-create"), {
            "image": SimpleUploadedFile("face.jpg", self.bands(1200, 800, fmt="JPEG"), content_type="image/jpeg"),
            "description": "A face", "image_type": "headshot",
        })
        self.assertEqual(response.status_code, 302)
        from backstage.models import Image

        self.assertEqual(self.opened(Image.objects.get(description="A face")).size, (400, 500))

    def test_uploading_another_type_through_the_uploader_does_not(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        user = CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!")
        self.client.force_login(user)
        self.client.post(reverse("image-create"), {
            "image": SimpleUploadedFile("poster.png", self.bands(1200, 800), content_type="image/png"),
            "description": "A poster", "image_type": "promotion",
        })
        from backstage.models import Image

        self.assertEqual(self.opened(Image.objects.get(description="A poster")).size, (1200, 800))

    def test_a_file_that_is_not_an_image_is_still_refused(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        user = CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!")
        self.client.force_login(user)
        response = self.client.post(reverse("image-create"), {
            "image": SimpleUploadedFile("notes.txt", b"not an image", content_type="text/plain"),
            "description": "Nope", "image_type": "headshot",
        })
        self.assertEqual(response.status_code, 200)
        from backstage.models import Image

        self.assertFalse(Image.objects.filter(description="Nope").exists())

    def test_saving_again_does_not_resize_again(self):
        image = self.store(self.bands(1000, 400))
        path_before = image.image.path
        image.description = "renamed"
        image.save()
        image.refresh_from_db()
        self.assertEqual(image.image.path, path_before)
        self.assertEqual(self.opened(image).size, (400, 500))

    def test_the_field_settings(self):
        from backstage.fields import HEADSHOT_CROP, HEADSHOT_SIZE
        from backstage.models import Image

        field = Image._meta.get_field("image")
        self.assertEqual((field.size, field.crop, field.keep_meta), (HEADSHOT_SIZE, HEADSHOT_CROP, False))
        self.assertEqual(HEADSHOT_SIZE, [400, 500])  # width, height

    # ---- black and white

    def test_a_headshot_is_made_black_and_white(self):
        stored = self.opened(self.store(self.bands(900, 600))).convert("RGB")
        pixels = [stored.getpixel((x, y)) for x in range(0, 400, 25) for y in range(0, 500, 25)]
        self.assertTrue(all(r == g == b for r, g, b in pixels))  # no colour left in any pixel

    def test_the_stored_file_itself_is_greyscale(self):
        for fmt, name in (("PNG", "face.png"), ("JPEG", "face.jpg")):
            self.assertEqual(self.opened(self.store(self.bands(900, 600, fmt=fmt), name=name)).mode, "L", fmt)

    def test_colours_become_their_usual_brightness(self):
        # Red, green and blue bands: scaled to 500 high, the 1500 wide image has them at x 0-500, 500-1000, 1000-1500;
        # use a tall image so each band is easy to find.
        stored = self.opened(self.store(self.bands(400, 500, across=False)))
        grey = lambda y: stored.convert("L").getpixel((200, y))
        self.assertEqual((grey(50), grey(250), grey(450)), (self.RED, self.GREEN, self.BLUE))
        self.assertGreater(self.GREEN, self.RED)  # green looks brighter than red, and red than blue
        self.assertGreater(self.RED, self.BLUE)

    def test_a_black_and_white_photo_is_unchanged_in_tone(self):
        from io import BytesIO

        from PIL import Image as PILImage

        buffer = BytesIO()
        PILImage.new("L", (800, 1000), 128).save(buffer, "PNG")
        stored = self.opened(self.store(buffer.getvalue()))
        self.assertEqual(stored.convert("L").getpixel((200, 250)), 128)

    def test_a_jpeg_is_not_visibly_recompressed_by_the_conversion(self):
        # A smooth gradient survives the conversion and resize with only a small error.
        from io import BytesIO

        from PIL import Image as PILImage

        gradient = PILImage.new("L", (400, 500))
        gradient.putdata([int(255 * x / 399) for y in range(500) for x in range(400)])
        buffer = BytesIO()
        gradient.convert("RGB").save(buffer, "JPEG", quality=95)
        stored = self.opened(self.store(buffer.getvalue(), name="gradient.jpg")).convert("L")
        for x in (10, 130, 260, 390):
            self.assertAlmostEqual(stored.getpixel((x, 250)), int(255 * x / 399), delta=6, msg=x)

    def test_a_png_with_transparency_keeps_it(self):
        from io import BytesIO

        from PIL import Image as PILImage

        photo = PILImage.new("RGBA", (400, 500), (200, 30, 30, 255))
        photo.paste((0, 0, 0, 0), (0, 0, 400, 100))  # a transparent band across the top
        buffer = BytesIO()
        photo.save(buffer, "PNG")
        stored = self.opened(self.store(buffer.getvalue()))
        self.assertEqual(stored.mode, "LA")
        self.assertEqual(stored.getpixel((200, 10))[1], 0)  # still transparent at the top
        self.assertEqual(stored.getpixel((200, 300))[1], 255)  # and solid below
        self.assertEqual(stored.getpixel((200, 300))[0], stored.convert("RGBA").getpixel((200, 300))[0])

    def test_a_photo_with_a_colour_profile_is_converted(self):
        from io import BytesIO

        from PIL import Image as PILImage

        buffer = BytesIO()
        PILImage.new("CMYK", (800, 600), (0, 255, 255, 0)).save(buffer, "JPEG")  # a red CMYK photo, as print-ready JPEGs are
        stored = self.opened(self.store(buffer.getvalue(), name="cmyk.jpg"))
        self.assertEqual((stored.size, stored.mode), ((400, 500), "L"))

    def test_other_types_keep_their_colour(self):
        from PIL import Image as PILImage

        image = self.store(self.bands(900, 600), image_type="promotion")
        with PILImage.open(image.image.path) as stored:
            self.assertEqual(stored.mode, "RGB")
            self.assertEqual(stored.getpixel((10, 10)), (255, 0, 0))  # still red

    def test_the_uploader_makes_a_headshot_black_and_white(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from backstage.models import Image

        user = CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!")
        self.client.force_login(user)
        response = self.client.post(reverse("image-create"), {
            "image": SimpleUploadedFile("face.jpg", self.bands(1200, 800, fmt="JPEG"), content_type="image/jpeg"),
            "description": "A face", "image_type": "headshot",
        })
        self.assertEqual(response.status_code, 302)
        stored = self.opened(Image.objects.get(description="A face"))
        self.assertEqual((stored.size, stored.mode), ((400, 500), "L"))

    def test_the_uploader_keeps_other_types_in_colour(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from backstage.models import Image

        user = CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!")
        self.client.force_login(user)
        self.client.post(reverse("image-create"), {
            "image": SimpleUploadedFile("poster.png", self.bands(600, 400), content_type="image/png"),
            "description": "A poster", "image_type": "gallery",
        })
        self.assertEqual(self.opened(Image.objects.get(description="A poster")).mode, "RGB")

    def test_a_file_that_is_not_an_image_still_fails_cleanly(self):
        from django.core.files.base import ContentFile

        from backstage.models import Image

        image = Image(description="bad", image_type="headshot")
        with self.assertRaises(Exception):
            image.image.save("bad.png", ContentFile(b"not an image"), save=True)
        self.assertFalse(Image.objects.filter(description="bad").exists())


class ResizeHeadshotsCommandTests(TestCase):
    """The resize_headshots command redoes headshots that were uploaded before they were processed on upload."""

    def setUp(self):
        import tempfile

        from django.test import override_settings

        self.media = tempfile.TemporaryDirectory()
        self.backups = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.addCleanup(self.backups.cleanup)
        override = override_settings(MEDIA_ROOT=self.media.name)
        override.enable()
        self.addCleanup(override.disable)

    def make(self, name, width, height, image_type="headshot", fmt="JPEG", colour=(200, 40, 40)):
        """An image in the library whose file is stored exactly as given, as an old upload would have been."""
        import os
        from io import BytesIO

        from PIL import Image as PILImage

        from backstage.models import Image

        buffer = BytesIO()
        PILImage.new("RGB", (width, height), colour).save(buffer, fmt)
        data = buffer.getvalue()
        os.makedirs(os.path.join(self.media.name, "images"), exist_ok=True)
        with open(os.path.join(self.media.name, "images", name), "wb") as f:
            f.write(data)
        image = Image.objects.create(description=name, image=f"images/{name}", image_type=image_type)
        return image, data

    def run_command(self, *args):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("resize_headshots", *args, "--backup-dir", self.backups.name + "/b", stdout=out)
        return out.getvalue()

    @staticmethod
    def details(image):
        from PIL import Image as PILImage

        image.refresh_from_db()
        with PILImage.open(image.image.path) as stored:
            return stored.size, stored.mode, stored.format

    def test_headshots_are_redone_as_new_uploads_are(self):
        big, _ = self.make("big.jpg", 1200, 1600)
        small, _ = self.make("small.jpg", 200, 250)
        output = self.run_command()
        self.assertIn("Redone 2 headshots", output)
        for image in (big, small):
            self.assertEqual(self.details(image), ((400, 500), "L", "JPEG"))

    def test_the_name_and_url_stay_the_same(self):
        image, _ = self.make("ann.jpg", 1000, 1000)
        self.run_command()
        image.refresh_from_db()
        self.assertEqual(image.image.name, "images/ann.jpg")  # anything linking to it still works

    def test_a_dry_run_changes_nothing(self):
        import os

        image, data = self.make("ann.jpg", 1000, 1000)
        output = self.run_command("--dry-run")
        self.assertIn("Would redo 1 headshots", output)
        with open(image.image.path, "rb") as stored:
            self.assertEqual(stored.read(), data)
        self.assertFalse(os.path.exists(self.backups.name + "/b"))  # not even the backup folder

    def test_the_originals_are_backed_up_byte_for_byte(self):
        import os

        image, data = self.make("ann.jpg", 1000, 1000)
        output = self.run_command()
        backup = os.path.join(self.backups.name, "b", "images", "ann.jpg")
        with open(backup, "rb") as saved:
            self.assertEqual(saved.read(), data)
        self.assertIn("The originals are copied in", output)

    def test_other_types_of_image_are_not_touched(self):
        image, data = self.make("poster.jpg", 1200, 800, image_type="promotion")
        self.make("ann.jpg", 1000, 1000)
        self.run_command()
        with open(image.image.path, "rb") as stored:
            self.assertEqual(stored.read(), data)

    def test_running_it_again_leaves_done_headshots_alone(self):
        import os

        image, _ = self.make("ann.jpg", 1000, 1000)
        self.run_command()
        with open(image.image.path, "rb") as stored:
            after_first = stored.read()
        output = self.run_command()
        self.assertIn("Redone 0 headshots", output)
        self.assertIn("1 were already done", output)
        with open(image.image.path, "rb") as stored:
            self.assertEqual(stored.read(), after_first)  # not recompressed a second time

    def test_an_image_with_no_file_is_reported_and_the_rest_carry_on(self):
        from backstage.models import Image

        Image.objects.create(description="gone", image="images/not-there.jpg", image_type="headshot")
        good, _ = self.make("ann.jpg", 1000, 1000)
        output = self.run_command()
        self.assertIn("1 have no file", output)
        self.assertIn("images/not-there.jpg", output)
        self.assertEqual(self.details(good)[0], (400, 500))

    def test_small_photos_are_listed_as_enlarged(self):
        self.make("tiny.jpg", 144, 144)
        self.make("ok.jpg", 800, 1000)
        output = self.run_command("--dry-run")
        self.assertIn("1 are smaller than 400 x 500", output)
        self.assertIn("images/tiny.jpg (144 x 144)", output)
        self.assertNotIn("images/ok.jpg (", output)

    def test_a_png_stays_a_png_and_a_jpeg_a_jpeg(self):
        png, _ = self.make("a.png", 900, 900, fmt="PNG")
        jpg, _ = self.make("b.jpg", 900, 900)
        self.run_command()
        self.assertEqual(self.details(png)[2], "PNG")
        self.assertEqual(self.details(jpg)[2], "JPEG")

    def test_a_failure_puts_the_original_back_and_the_others_are_still_done(self):
        from unittest import mock

        bad, bad_data = self.make("bad.jpg", 1000, 1000)
        good, _ = self.make("good.jpg", 1000, 1000)
        real = __import__("backstage.fields", fromlist=["monochrome"]).monochrome

        # Make the conversion fail for the first photo only.
        calls = {"n": 0}

        def fail_first(content, focal=(0.5, 0.5), tone=(0, 0)):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("cannot convert")
            return real(content, focal, tone)

        with mock.patch("backstage.fields.monochrome", side_effect=fail_first):
            output = self.run_command()
        self.assertIn("FAILED images/bad.jpg", output)
        self.assertIn("Redone 1 headshots", output)
        with open(bad.image.path, "rb") as restored:
            self.assertEqual(restored.read(), bad_data)  # the original is back, untouched
        bad.refresh_from_db()
        self.assertEqual(bad.image.name, "images/bad.jpg")
        self.assertEqual(self.details(good)[0], (400, 500))

    def test_the_file_sizes_are_reported(self):
        self.make("big.jpg", 2000, 2500)
        self.assertRegex(self.run_command(), r"Files went from \d+ KB to \d+ KB")

    def test_a_black_and_white_webp_counts_as_done(self):
        # WebP stores three channels even for a grey picture, so it is judged by whether the channels match.
        image, _ = self.make("w.webp", 900, 900, fmt="WEBP")
        self.run_command()
        self.assertEqual(self.details(image)[0], (400, 500))
        output = self.run_command()
        self.assertIn("Redone 0 headshots", output)
        self.assertIn("1 were already done", output)

    def test_a_colour_photo_of_the_right_size_is_not_counted_as_done(self):
        image, _ = self.make("c.jpg", 400, 500, colour=(200, 40, 40))  # the right size, but in colour
        output = self.run_command()
        self.assertIn("Redone 1 headshots", output)
        self.assertEqual(self.details(image)[1], "L")

    def test_is_black_and_white(self):
        from PIL import Image as PILImage

        from backstage.management.commands.resize_headshots import is_black_and_white

        self.assertTrue(is_black_and_white(PILImage.new("L", (4, 4), 100)))
        self.assertTrue(is_black_and_white(PILImage.new("LA", (4, 4), (100, 255))))
        self.assertTrue(is_black_and_white(PILImage.new("RGB", (4, 4), (90, 91, 90))))  # within WebP's rounding
        self.assertFalse(is_black_and_white(PILImage.new("RGB", (4, 4), (200, 40, 40))))
        self.assertFalse(is_black_and_white(PILImage.new("RGBA", (4, 4), (10, 90, 10, 255))))
        self.assertFalse(is_black_and_white(PILImage.new("P", (4, 4))))


class FocalPointTests(TestCase):
    """A headshot is cropped around the focus point chosen when it is uploaded."""

    def setUp(self):
        import tempfile

        from django.test import override_settings

        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        override = override_settings(MEDIA_ROOT=self.media.name)
        override.enable()
        self.addCleanup(override.disable)

    # ---- the sum

    def test_the_crop_window_has_the_headshots_shape_and_fits_the_photo(self):
        from backstage.fields import focal_crop_box

        for width, height in ((1500, 500), (400, 1500), (900, 900), (400, 500), (4000, 3000), (50, 400), (3, 3)):
            for focal in ((0, 0), (0.5, 0.5), (1, 1), (0.2, 0.9)):
                left, top, right, bottom = focal_crop_box(width, height, focal)
                self.assertTrue(0 <= left < right <= width and 0 <= top < bottom <= height, (width, height, focal))
                self.assertAlmostEqual((right - left) / (bottom - top), 0.8, delta=0.8 / min(right - left, bottom - top) + 0.01)

    def test_the_default_is_the_middle(self):
        from backstage.fields import focal_crop_box

        self.assertEqual(focal_crop_box(1500, 500), (550, 0, 950, 500))  # a 400 x 500 window, centred
        self.assertEqual(focal_crop_box(400, 1500), (0, 500, 400, 1000))

    def test_the_window_is_centred_on_the_focus_point(self):
        from backstage.fields import focal_crop_box

        # In a wide photo, a focus point 30% across (x = 450 of 1500) puts the 400 wide window at 250 to 650.
        self.assertEqual(focal_crop_box(1500, 500, (0.3, 0.5)), (250, 0, 650, 500))
        # In a tall photo, 25% down (y = 375 of 1500) puts the 500 high window at 125 to 625.
        self.assertEqual(focal_crop_box(400, 1500, (0.5, 0.25)), (0, 125, 400, 625))

    def test_the_window_stays_inside_the_photo(self):
        from backstage.fields import focal_crop_box

        self.assertEqual(focal_crop_box(1500, 500, (0, 0.5)), (0, 0, 400, 500))  # at the left edge
        self.assertEqual(focal_crop_box(1500, 500, (1, 0.5)), (1100, 0, 1500, 500))  # at the right edge
        self.assertEqual(focal_crop_box(400, 1500, (0.5, 0)), (0, 0, 400, 500))  # at the top
        self.assertEqual(focal_crop_box(400, 1500, (0.5, 1)), (0, 1000, 400, 1500))  # at the bottom
        self.assertEqual(focal_crop_box(1500, 500, (0.01, 0.5))[0], 0)  # so near the edge that the window would stick out

    def test_a_photo_that_is_already_the_right_shape_is_not_cropped(self):
        from backstage.fields import focal_crop_box

        for focal in ((0, 0), (0.5, 0.5), (1, 1)):
            self.assertEqual(focal_crop_box(800, 1000, focal), (0, 0, 800, 1000))

    def test_nonsense_focus_points_mean_the_middle_or_the_nearest_edge(self):
        from backstage.fields import clamp, focal_crop_box

        self.assertEqual(clamp("abc"), 0.5)
        self.assertEqual(clamp(None), 0.5)
        self.assertEqual(clamp(""), 0.5)
        self.assertEqual(clamp("nan"), 0.5)
        self.assertEqual(clamp(-3), 0.0)
        self.assertEqual(clamp(7), 1.0)
        self.assertEqual(clamp("0.25"), 0.25)
        self.assertEqual(focal_crop_box(1500, 500, ("x", None)), focal_crop_box(1500, 500))
        self.assertEqual(focal_crop_box(1500, 500, (-5, 9)), focal_crop_box(1500, 500, (0, 1)))

    # ---- the stored photo

    @staticmethod
    def bands(width, height, across=True):
        return HeadshotResizeTests.bands(width, height, across=across)

    def store(self, data, focal=None, name="photo.png"):
        from django.core.files.base import ContentFile

        from backstage.models import Image

        image = Image(description="test", image_type="headshot")
        if focal is not None:
            image.focal_point = focal
        image.image.save(name, ContentFile(data), save=True)
        return Image.objects.get(pk=image.pk)

    @staticmethod
    def grey_at(image, point):
        from PIL import Image as PILImage

        with PILImage.open(image.image.path) as stored:
            return stored.convert("L").getpixel(point)

    def test_a_wide_photo_is_cropped_around_the_focus_point(self):
        # Red, green and blue bands left to right (each 500 wide): a window at the left sees only red (76 grey), in the
        # middle only green (150), at the right only blue (29).
        data = self.bands(1500, 500)
        red, green, blue = HeadshotResizeTests.RED, HeadshotResizeTests.GREEN, HeadshotResizeTests.BLUE
        for focal, expected in (((0.0, 0.5), red), ((0.5, 0.5), green), ((1.0, 0.5), blue), (None, green)):
            image = self.store(data, focal)
            for x in (0, 200, 399):
                self.assertEqual(self.grey_at(image, (x, 250)), expected, (focal, x))

    def test_a_tall_photo_is_cropped_around_the_focus_point(self):
        data = self.bands(400, 1500, across=False)  # red, green, blue from top to bottom
        red, green, blue = HeadshotResizeTests.RED, HeadshotResizeTests.GREEN, HeadshotResizeTests.BLUE
        for focal, expected in (((0.5, 0.0), red), ((0.5, 0.5), green), ((0.5, 1.0), blue)):
            image = self.store(data, focal)
            for y in (0, 250, 499):
                self.assertEqual(self.grey_at(image, (200, y)), expected, (focal, y))

    def test_the_result_is_still_400_by_500_and_black_and_white(self):
        from PIL import Image as PILImage

        image = self.store(self.bands(1500, 500), (0.1, 0.5))
        with PILImage.open(image.image.path) as stored:
            self.assertEqual((stored.size, stored.mode), ((400, 500), "L"))

    def test_a_focus_point_in_a_sideways_photo_is_in_the_upright_picture(self):
        from PIL import Image as PILImage

        # 600 x 300 pixels marked "rotate to view": the upright photo is 300 x 600 with the red band at the top. A focus
        # point at the top (y = 0) must show the red end, one at the bottom (y = 1) the blue end.
        exif = PILImage.Exif()
        exif[274] = 6
        data = HeadshotResizeTests.bands(600, 300, fmt="JPEG", exif=exif.tobytes())
        top = self.grey_at(self.store(data, (0.5, 0.0), name="a.jpg"), (200, 5))
        bottom = self.grey_at(self.store(data, (0.5, 1.0), name="b.jpg"), (200, 494))
        self.assertAlmostEqual(top, HeadshotResizeTests.RED, delta=6)
        self.assertAlmostEqual(bottom, HeadshotResizeTests.BLUE, delta=6)

    def test_other_types_ignore_the_focus_point(self):
        from django.core.files.base import ContentFile

        from backstage.models import Image

        data = self.bands(1500, 500)
        image = Image(description="poster", image_type="promotion")
        image.focal_point = (0.0, 0.0)
        image.image.save("p.png", ContentFile(data), save=True)
        with open(Image.objects.get(pk=image.pk).image.path, "rb") as stored:
            self.assertEqual(stored.read(), data)

    # ---- the uploader

    def upload(self, data, **fields):
        from django.core.files.uploadedfile import SimpleUploadedFile

        user = CustomUser.objects.filter(username="member").first() or CustomUser.objects.create_user(
            "member", "member@example.com", "a-Long-pa55word!"
        )
        self.client.force_login(user)
        post = {"image": SimpleUploadedFile("face.png", data, content_type="image/png"), "description": "A face", "image_type": "headshot"}
        post.update(fields)
        return self.client.post(reverse("image-create"), post)

    def stored(self):
        from backstage.models import Image

        return Image.objects.get(description="A face")

    def test_the_uploader_crops_around_the_chosen_focus(self):
        data = self.bands(1500, 500)
        self.assertEqual(self.upload(data, focal_x="0", focal_y="0.5").status_code, 302)
        self.assertEqual(self.grey_at(self.stored(), (200, 250)), HeadshotResizeTests.RED)

    def test_the_uploader_goes_to_the_middle_without_a_focus_or_with_rubbish(self):
        data = self.bands(1500, 500)
        for fields in ({}, {"focal_x": "", "focal_y": ""}, {"focal_x": "abc", "focal_y": "<script>"}):
            from backstage.models import Image

            Image.objects.all().delete()
            self.assertEqual(self.upload(data, **fields).status_code, 302, fields)
            self.assertEqual(self.grey_at(self.stored(), (200, 250)), HeadshotResizeTests.GREEN, fields)

    def test_out_of_range_values_do_not_stop_the_upload(self):
        self.assertEqual(self.upload(self.bands(1500, 500), focal_x="5", focal_y="-2").status_code, 302)
        self.assertEqual(self.grey_at(self.stored(), (200, 250)), HeadshotResizeTests.BLUE)  # 5 means the far right

    def test_the_uploader_form_has_the_focus_fields(self):
        user = CustomUser.objects.create_user("member2", "member2@example.com", "a-Long-pa55word!")
        self.client.force_login(user)
        html = self.client.get(reverse("image-create")).content.decode()
        self.assertIn('name="focal_x"', html)
        self.assertIn('name="focal_y"', html)
        self.assertIn('type="hidden"', html.split('name="focal_x"')[0].rsplit("<input", 1)[1])  # they are hidden fields

    def test_the_focus_is_not_stored(self):
        from backstage.models import Image

        self.upload(self.bands(1500, 500), focal_x="0.1", focal_y="0.9")
        self.assertFalse(hasattr(Image.objects.get(description="A face"), "focal_point"))
        self.assertNotIn("focal_x", [f.name for f in Image._meta.get_fields()])

    def test_the_upload_page_has_the_focus_tool_and_the_preview(self):
        user = CustomUser.objects.create_user("member3", "member3@example.com", "a-Long-pa55word!")
        self.client.force_login(user)
        for url in (reverse("image-create"), reverse("image-create") + "?type=headshot&for_person=new"):
            html = self.client.get(url).content.decode()
            for needle in ('id="headshot-tool"', 'id="focus-area"', 'id="focus-frame"', 'id="focus-dot"', 'id="headshot-preview"',
                           'id="focus-reset"', 'width="400" height="500"', "Centre the crop", "How it will look", "grayscale",
                           "ArrowLeft", "pointerdown"):
                self.assertIn(needle, html, (url, needle))
            # The tool starts hidden: it shows when a headshot's file is chosen.
            self.assertRegex(html, r'id="headshot-tool" class="[^"]*\bhidden\b')
            # The page's crop sum uses the same shape as the server's.
            self.assertIn("const WIDTH = 400, HEIGHT = 500", html)

    def test_the_page_and_the_server_agree_on_the_shape(self):
        from backstage.fields import HEADSHOT_SIZE

        user = CustomUser.objects.create_user("member4", "member4@example.com", "a-Long-pa55word!")
        self.client.force_login(user)
        html = self.client.get(reverse("image-create")).content.decode()
        self.assertIn(f"const WIDTH = {HEADSHOT_SIZE[0]}, HEIGHT = {HEADSHOT_SIZE[1]}", html)
        self.assertIn(f'width="{HEADSHOT_SIZE[0]}" height="{HEADSHOT_SIZE[1]}"', html)

    def test_the_uploader_accepts_dropped_pictures(self):
        user = CustomUser.objects.create_user("member5", "member5@example.com", "a-Long-pa55word!")
        self.client.force_login(user)
        html = self.client.get(reverse("image-create")).content.decode()
        for needle in ('id="drop-zone"', 'id="drop-message"', "Drop an image here", "or click to choose a file",
                       "window.addEventListener('drop'", "window.addEventListener('dragover'", "dataTransfer.files",
                       "event.preventDefault()", "'Files'", "input.dispatchEvent(new Event('change'"):
            self.assertIn(needle, html, needle)
        # The file chooser only offers pictures, and the drop box is a label for it (so a click opens the chooser).
        self.assertRegex(html, r'<input type="file" name="image" accept="image/\*"')
        self.assertIn('for="id_image"', html)

    def test_replacing_an_images_file_offers_a_drop_box_too(self):
        from backstage.models import Image

        user = CustomUser.objects.create_user("member6", "member6@example.com", "a-Long-pa55word!")
        self.client.force_login(user)
        image = Image.objects.create(description="x", image="images/x.jpg")
        html = self.client.get(reverse("image-update", args=[image.pk])).content.decode()
        self.assertIn("Drop a new image here", html)


class PersonPhotoUploadOnlyTests(TestCase):
    """The only way to give a person a photo is to upload one: there is no list of existing photos to choose from."""

    @classmethod
    def setUpTestData(cls):
        from backstage.models import Image

        cls.user = CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!")
        cls.photo = Image.objects.create(description="Ann", image="images/ann.jpg", image_type="headshot")
        cls.other = Image.objects.create(description="Bob", image="images/bob.jpg", image_type="headshot")
        cls.person = Person.objects.create(first_name="Ann", last_name="Actor", image=cls.photo)

    def setUp(self):
        self.client.force_login(self.user)

    def pages(self):
        return (reverse("person-create"), reverse("person-update", args=[self.person.pk]))

    def test_there_is_no_list_of_photos_to_choose_from(self):
        for url in self.pages():
            html = self.client.get(url).content.decode()
            self.assertNotIn('<select name="image"', html, url)
            self.assertNotIn("Ann</option>", html, url)  # none of the library's photos are offered
            self.assertNotIn("Bob</option>", html, url)

    def test_the_photo_is_a_hidden_field_not_something_to_type_or_pick(self):
        html = self.client.get(reverse("person-update", args=[self.person.pk])).content.decode()
        self.assertIn(f'<input type="hidden" name="image" value="{self.photo.pk}"', html)
        html = self.client.get(reverse("person-create")).content.decode()
        self.assertRegex(html, r'<input type="hidden" name="image"(?! value="\d)')  # empty for a new person

    def test_the_only_photo_control_is_an_upload_button(self):
        html = self.client.get(reverse("person-create")).content.decode()
        self.assertRegex(html, r'<a id="upload-photo-link" href="[^"]*type=headshot[^"]*for_person=new" class="btn btn-primary btn-sm">Upload photo</a>')
        self.assertNotIn("Photo not listed", html)
        self.assertIn("You choose the crop when you upload", html)

    def test_the_upload_button_comes_back_to_the_person_being_edited(self):
        html = self.client.get(reverse("person-update", args=[self.person.pk])).content.decode()
        self.assertIn(f"for_person={self.person.pk}", html)

    def test_a_person_with_a_photo_can_have_it_removed(self):
        with_photo = self.client.get(reverse("person-update", args=[self.person.pk])).content.decode()
        self.assertIn('id="remove-photo"', with_photo)
        self.assertNotRegex(with_photo, r'id="remove-photo" class="[^"]*hidden')  # shown, as there is a photo
        without = self.client.get(reverse("person-create")).content.decode()
        self.assertRegex(without, r'id="remove-photo" class="[^"]*hidden')  # hidden until there is a photo

    def test_saving_with_the_photo_field_empty_removes_it(self):
        response = self.client.post(reverse("person-update", args=[self.person.pk]), {"first_name": "Ann", "last_name": "Actor", "image": ""})
        self.assertEqual(response.status_code, 302)
        self.person.refresh_from_db()
        self.assertIsNone(self.person.image)

    def test_saving_keeps_the_photo_that_the_hidden_field_carries(self):
        response = self.client.post(reverse("person-update", args=[self.person.pk]), {"first_name": "Ann", "last_name": "Actor", "image": self.photo.pk})
        self.assertEqual(response.status_code, 302)
        self.person.refresh_from_db()
        self.assertEqual(self.person.image, self.photo)

    def test_a_new_person_gets_the_uploaded_photo(self):
        response = self.client.post(reverse("person-create"), {"first_name": "New", "last_name": "Person", "image": self.other.pk})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Person.objects.get(first_name="New").image, self.other)

    def test_only_headshots_can_be_set_as_a_photo(self):
        from backstage.models import Image

        poster = Image.objects.create(description="Poster", image="images/poster.jpg", image_type="promotion")
        response = self.client.post(reverse("person-create"), {"first_name": "Bad", "last_name": "Photo", "image": poster.pk})
        self.assertEqual(response.status_code, 200)  # refused: not a headshot
        self.assertFalse(Person.objects.filter(first_name="Bad").exists())

    def test_the_page_shows_the_current_photo_and_what_the_buttons_do(self):
        html = self.client.get(reverse("person-update", args=[self.person.pk])).content.decode()
        self.assertIn('id="photo-preview"', html)
        self.assertIn('aspect-[4/5]', html)  # a rectangular thumbnail
        self.assertNotIn('rounded-full', html)  # not a circle
        self.assertIn("Upload a new photo", html)  # the button says so once there is a photo
        self.assertIn("link.textContent = photo.value", html)
        self.assertIn("removeButton.addEventListener('click'", html)


class BrightnessContrastTests(TestCase):
    """Headshots can be made brighter or darker and with more or less contrast when they are uploaded."""

    def setUp(self):
        import tempfile

        from django.test import override_settings

        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        override = override_settings(MEDIA_ROOT=self.media.name)
        override.enable()
        self.addCleanup(override.disable)

    @staticmethod
    def expected(grey, brightness=0, contrast=0):
        """What a grey value should become: brightness (x 2 ** (b / 100)), then contrast about 127.5, kept in range."""
        level = min(max(grey / 255 * 2 ** (brightness / 100), 0), 1)
        level = min(max((level - 0.5) * 2 ** (contrast / 100) + 0.5, 0), 1)
        return int(level * 255 + 0.5)

    # ---- the arithmetic

    def test_no_change_is_the_identity(self):
        from backstage.fields import tone_lut

        self.assertEqual(tone_lut(0, 0), list(range(256)))
        self.assertEqual(tone_lut(), list(range(256)))

    def test_brightness_scales_the_greys(self):
        from backstage.fields import tone_lut

        # +100 is x2 (so 100 becomes 200 and anything over 127 is white); -100 is x0.5.
        self.assertEqual(tone_lut(100, 0)[100], 200)
        self.assertEqual(tone_lut(100, 0)[128], 255)
        self.assertEqual(tone_lut(-100, 0)[100], 50)
        self.assertEqual(tone_lut(-100, 0)[255], 128)
        self.assertEqual((tone_lut(50, 0)[100], 141), (141, 141))  # x 1.414

    def test_contrast_pushes_greys_away_from_the_middle(self):
        from backstage.fields import tone_lut

        more = tone_lut(0, 100)  # x2 about the middle grey
        self.assertEqual((more[191], more[64], more[0], more[255]), (255, 0, 0, 255))
        self.assertAlmostEqual(more[128], 128, delta=1)  # the middle is unchanged
        less = tone_lut(0, -100)  # x0.5 about the middle grey
        self.assertEqual((less[0], less[255]), (64, 191))
        self.assertAlmostEqual(less[128], 128, delta=1)

    def test_it_matches_the_formula_for_every_grey_and_setting(self):
        from backstage.fields import tone_lut

        for brightness, contrast in ((0, 0), (40, 0), (0, -60), (-35, 70), (100, 100), (-100, -100), (13, -87)):
            table = tone_lut(brightness, contrast)
            for grey in range(256):
                self.assertEqual(table[grey], self.expected(grey, brightness, contrast), (brightness, contrast, grey))

    def test_brightness_comes_first_then_contrast(self):
        from backstage.fields import tone_lut

        import math

        # Brightness x1.5 (a setting of 100 * log2(1.5)): 100 becomes 150 (0.588), then contrast x2:
        # (0.588 - 0.5) * 2 + 0.5 = 0.676, which is 172.5, so 173. The other way round gives
        # (100/255 - 0.5) * 2 + 0.5 = 0.28, then x1.5 = 0.42, which is 107.
        brightness = 100 * math.log2(1.5)
        self.assertEqual(tone_lut(brightness, 100)[100], 173)
        self.assertNotEqual(tone_lut(brightness, 100)[100], 107)

    def test_the_table_stays_between_0_and_255_and_never_goes_backwards(self):
        from backstage.fields import tone_lut

        for brightness in (-100, -30, 0, 55, 100):
            for contrast in (-100, -30, 0, 55, 100):
                table = tone_lut(brightness, contrast)
                self.assertEqual(len(table), 256)
                self.assertTrue(all(0 <= v <= 255 for v in table))
                self.assertTrue(all(a <= b for a, b in zip(table, table[1:])), (brightness, contrast))  # lighter stays lighter

    def test_settings_are_clamped_and_rubbish_is_zero(self):
        from backstage.fields import clamp_tone, tone_lut

        self.assertEqual(clamp_tone("55"), 55.0)
        self.assertEqual(clamp_tone("-12.5"), -12.5)
        self.assertEqual(clamp_tone(500), 100.0)
        self.assertEqual(clamp_tone(-500), -100.0)
        for rubbish in ("abc", "", None, "nan", "<script>", [], "1e999999"):
            self.assertIn(clamp_tone(rubbish), (0.0, 100.0), rubbish)  # "1e999999" is infinity: clamped
        self.assertEqual(tone_lut("abc", None), list(range(256)))
        self.assertEqual(tone_lut(500, 0), tone_lut(100, 0))

    # ---- the stored photo

    @staticmethod
    def grey_photo(*levels):
        """A PNG in vertical bands of the given grey levels, 600 wide by 750 high (so the crop keeps all of it)."""
        from io import BytesIO

        from PIL import Image as PILImage

        image = PILImage.new("L", (len(levels) * 200, 750))
        for index, level in enumerate(levels):
            image.paste(level, (index * 200, 0, (index + 1) * 200, 750))
        buffer = BytesIO()
        image.save(buffer, "PNG")
        return buffer.getvalue()

    def store(self, data, tone=None, image_type="headshot", name="photo.png"):
        from django.core.files.base import ContentFile

        from backstage.models import Image

        image = Image(description="test", image_type=image_type)
        if tone is not None:
            image.tone = tone
        image.image.save(name, ContentFile(data), save=True)
        return Image.objects.get(pk=image.pk)

    @staticmethod
    def levels(image, xs=(66, 200, 333)):
        from PIL import Image as PILImage

        with PILImage.open(image.image.path) as stored:
            return [stored.convert("L").getpixel((x, 250)) for x in xs]

    def test_without_settings_the_greys_are_unchanged(self):
        # A 600 x 750 photo is cropped to 600 x 750 (it is 4:5 already) and scaled to 400 x 500: bands are at 0-133 etc.
        self.assertEqual(self.levels(self.store(self.grey_photo(60, 128, 200))), [60, 128, 200])

    def test_brightness_changes_the_stored_photo(self):
        image = self.store(self.grey_photo(60, 100, 128), tone=(100, 0))
        self.assertEqual(self.levels(image), [self.expected(60, 100), self.expected(100, 100), 255])
        self.assertEqual(self.levels(self.store(self.grey_photo(60, 100, 200), tone=(-100, 0), name="d.png")), [30, 50, 100])

    def test_contrast_changes_the_stored_photo(self):
        image = self.store(self.grey_photo(64, 128, 191), tone=(0, 100))
        self.assertEqual(self.levels(image), [self.expected(64, 0, 100), self.expected(128, 0, 100), self.expected(191, 0, 100)])
        flat = self.store(self.grey_photo(64, 128, 191), tone=(0, -100), name="f.png")
        self.assertEqual(self.levels(flat), [self.expected(64, 0, -100), self.expected(128, 0, -100), self.expected(191, 0, -100)])

    def test_both_together(self):
        image = self.store(self.grey_photo(40, 100, 160), tone=(30, -40))
        self.assertEqual(self.levels(image), [self.expected(g, 30, -40) for g in (40, 100, 160)])

    def test_it_is_applied_after_the_black_and_white(self):
        from io import BytesIO

        from PIL import Image as PILImage

        buffer = BytesIO()
        red = PILImage.new("RGB", (600, 750), (200, 40, 40))
        red.save(buffer, "PNG")
        grey = red.convert("L").getpixel((0, 0))  # the red as a grey: 88
        stored = self.store(buffer.getvalue(), tone=(0, 100))
        self.assertEqual(self.levels(stored)[0], self.expected(grey, 0, 100))
        self.assertNotEqual(self.levels(stored)[0], grey)  # the contrast really did something

    def test_a_colour_jpeg_with_a_setting_is_still_a_greyscale_400_by_500(self):
        from io import BytesIO

        from PIL import Image as PILImage

        buffer = BytesIO()
        PILImage.new("RGB", (900, 700), (30, 90, 160)).save(buffer, "JPEG")
        stored = self.store(buffer.getvalue(), tone=(25, 25), name="c.jpg")
        with PILImage.open(stored.image.path) as image:
            self.assertEqual((image.size, image.mode, image.format), ((400, 500), "L", "JPEG"))

    def test_transparency_is_left_alone(self):
        from io import BytesIO

        from PIL import Image as PILImage

        photo = PILImage.new("RGBA", (600, 750), (100, 100, 100, 255))
        photo.paste((0, 0, 0, 0), (0, 0, 600, 100))
        buffer = BytesIO()
        photo.save(buffer, "PNG")
        stored = self.store(buffer.getvalue(), tone=(100, 100))
        with PILImage.open(stored.image.path) as image:
            self.assertEqual(image.mode, "LA")
            self.assertEqual(image.getpixel((200, 10))[1], 0)  # still see-through at the top
            self.assertEqual(image.getpixel((200, 400))[1], 255)  # and solid below
            self.assertEqual(image.getpixel((200, 400))[0], self.expected(100, 100, 100))

    def test_other_types_ignore_it(self):
        data = self.grey_photo(60, 128, 200)
        image = self.store(data, tone=(100, 100), image_type="promotion")
        with open(image.image.path, "rb") as stored:
            self.assertEqual(stored.read(), data)

    # ---- the uploader

    def upload(self, data, **fields):
        from django.core.files.uploadedfile import SimpleUploadedFile

        user = CustomUser.objects.filter(username="member").first() or CustomUser.objects.create_user(
            "member", "member@example.com", "a-Long-pa55word!"
        )
        self.client.force_login(user)
        post = {"image": SimpleUploadedFile("face.png", data, content_type="image/png"), "description": "A face", "image_type": "headshot"}
        post.update(fields)
        return self.client.post(reverse("image-create"), post)

    def stored(self):
        from backstage.models import Image

        return Image.objects.get(description="A face")

    def test_the_uploader_applies_the_chosen_settings(self):
        self.assertEqual(self.upload(self.grey_photo(60, 100, 128), brightness="100", contrast="0").status_code, 302)
        self.assertEqual(self.levels(self.stored()), [self.expected(60, 100), self.expected(100, 100), 255])

    def test_settings_work_with_the_focus_point(self):
        # Three bands; focus at the far left shows the darkest band only, which is then brightened.
        wide = __import__("io").BytesIO()
        from PIL import Image as PILImage

        image = PILImage.new("L", (1500, 500))
        for i, level in enumerate((60, 128, 200)):
            image.paste(level, (i * 500, 0, (i + 1) * 500, 500))
        image.save(wide, "PNG")
        self.upload(wide.getvalue(), focal_x="0", focal_y="0.5", brightness="50", contrast="0")
        self.assertEqual(self.levels(self.stored(), xs=(5, 200, 395)), [self.expected(60, 50)] * 3)

    def test_missing_or_rubbish_settings_mean_no_change(self):
        from backstage.models import Image

        for fields in ({}, {"brightness": "", "contrast": ""}, {"brightness": "abc", "contrast": "<script>"}):
            Image.objects.all().delete()
            self.assertEqual(self.upload(self.grey_photo(60, 128, 200), **fields).status_code, 302, fields)
            self.assertEqual(self.levels(self.stored()), [60, 128, 200], fields)

    def test_out_of_range_settings_are_clamped_not_refused(self):
        self.assertEqual(self.upload(self.grey_photo(60, 100, 128), brightness="900", contrast="-900").status_code, 302)
        # +100 brightness then -100 contrast (the nearest the settings can go).
        self.assertEqual(self.levels(self.stored()), [self.expected(g, 100, -100) for g in (60, 100, 128)])

    def test_decimal_settings_are_fine(self):
        self.assertEqual(self.upload(self.grey_photo(60, 128, 200), brightness="12.5", contrast="-7.25").status_code, 302)
        self.assertEqual(self.levels(self.stored()), [self.expected(g, 12.5, -7.25) for g in (60, 128, 200)])

    def test_the_settings_are_not_stored(self):
        from backstage.models import Image

        self.upload(self.grey_photo(60, 128, 200), brightness="40", contrast="40")
        names = [f.name for f in Image._meta.get_fields()]
        self.assertNotIn("brightness", names)
        self.assertNotIn("contrast", names)
        self.assertFalse(hasattr(Image.objects.get(description="A face"), "tone"))

    def test_the_form_has_the_hidden_setting_fields(self):
        user = CustomUser.objects.create_user("member7", "member7@example.com", "a-Long-pa55word!")
        self.client.force_login(user)
        html = self.client.get(reverse("image-create")).content.decode()
        self.assertRegex(html, r'<input type="hidden" name="brightness" value="0"[^>]*id="id_brightness"')
        self.assertRegex(html, r'<input type="hidden" name="contrast" value="0"[^>]*id="id_contrast"')

    def test_the_page_has_the_sliders_and_the_matching_preview_filter(self):
        user = CustomUser.objects.create_user("member8", "member8@example.com", "a-Long-pa55word!")
        self.client.force_login(user)
        html = self.client.get(reverse("image-create")).content.decode()
        for needle in ('id="brightness-slider"', 'id="contrast-slider"', 'type="range" min="-100" max="100" step="1" value="0"',
                       ">Brightness <", ">Contrast <", 'id="brightness-value"', 'id="contrast-value"', 'id="tone-reset"',
                       "Reset brightness and contrast", "2 ** (Number(setting) / 100)",
                       "grayscale(1) brightness(", "contrast(${toneFactor(contrast)})"):
            self.assertIn(needle, html, needle)
        # The preview is no longer made grey by a class: the filter does it, together with the sliders.
        self.assertNotIn("shadow-sm grayscale", html)


class NewActorWizardTests(TestCase):
    """New actor: 1. details and biography (saved), 2. photo (can be skipped), 3. review and set roles."""

    def setUp(self):
        import tempfile

        from django.test import override_settings

        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        override = override_settings(MEDIA_ROOT=self.media.name)
        override.enable()
        self.addCleanup(override.disable)
        self.user = CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!")
        self.client.force_login(self.user)
        self.actor = Role.objects.get_or_create(name="Actor")[0]
        self.director = Role.objects.get_or_create(name="Director")[0]

    def step_one(self, **extra):
        data = {"first_name": "Wendy", "last_name": "Wizard", "biography": "<p>Loves <b>panto</b>.</p>"}
        return self.client.post(reverse("actor-new"), {**data, **extra})

    def photo(self):
        from io import BytesIO

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image as PILImage

        buffer = BytesIO()
        PILImage.new("RGB", (600, 750), (200, 40, 40)).save(buffer, "PNG")
        return SimpleUploadedFile("wendy.png", buffer.getvalue(), content_type="image/png")

    # ---- step 1
    def test_step_one_shows_the_steps_and_the_detail_fields(self):
        html = self.client.get(reverse("actor-new")).content.decode()
        self.assertIn("step 1 of 3", html)
        for name in ("first_name", "last_name", "email", "mobile", "gender", "dob", "biography"):
            self.assertIn(f'name="{name}"', html)
        self.assertNotIn('name="roles"', html)
        self.assertNotIn('name="image"', html)

    def test_step_one_saves_the_person_and_goes_to_the_photo_step(self):
        response = self.step_one()
        person = Person.objects.get(first_name="Wendy")
        self.assertEqual(person.biography, "<p>Loves <b>panto</b>.</p>")
        self.assertEqual(person.roles.count(), 0)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("image-create"), response.url)
        self.assertIn(f"for_person={person.pk}", response.url)
        self.assertIn("wizard=1", response.url)

    def test_step_one_needs_a_name(self):
        response = self.client.post(reverse("actor-new"), {"first_name": "", "last_name": ""})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Person.objects.exists())

    # ---- step 2
    def test_step_two_hides_the_description_and_type_and_can_be_skipped(self):
        person = Person.objects.create(first_name="Wendy", last_name="Wizard")
        url = f"{reverse('image-create')}?type=headshot&for_person={person.pk}&wizard=1"
        html = self.client.get(url).content.decode()
        self.assertIn("step 2 of 3", html)
        self.assertRegex(html, r'<input type="hidden" name="description" value="Wendy Wizard"')
        self.assertRegex(html, r'<input type="hidden" name="image_type" value="headshot"')
        self.assertNotIn("<select", html)
        self.assertIn(f'href="{reverse("actor-roles", args=[person.pk])}" class="btn btn-ghost">Skip photo', html)

    def test_uploading_sets_the_photo_and_goes_to_step_three(self):
        person = Person.objects.create(first_name="Wendy", last_name="Wizard")
        response = self.client.post(
            reverse("image-create"),
            {"image": self.photo(), "for_person": person.pk, "wizard": "1", "description": "", "image_type": "promotion"},
        )
        self.assertRedirects(response, reverse("actor-roles", args=[person.pk]))
        person.refresh_from_db()
        self.assertEqual(person.image.image_type, "headshot")  # whatever was posted, it is a headshot
        self.assertEqual(person.image.description, "Wendy Wizard")

    def test_the_ordinary_uploader_still_asks_for_description_and_type(self):
        html = self.client.get(reverse("image-create")).content.decode()
        self.assertIn("<select", html)
        self.assertIn('name="description"', html)
        self.assertNotIn("step 2 of 3", html)

    # ---- step 3
    def test_step_three_shows_the_name_biography_and_roles_with_actor_ticked(self):
        person = Person.objects.create(first_name="Wendy", last_name="Wizard", biography="<p>Loves panto.</p>")
        response = self.client.get(reverse("actor-roles", args=[person.pk]))
        html = response.content.decode()
        self.assertIn("step 3 of 3", html)
        self.assertIn("Wendy Wizard", html)
        self.assertIn("<p>Loves panto.</p>", html)
        self.assertRegex(html, rf'value="{self.actor.pk}"[^>]*checked')
        self.assertNotRegex(html, rf'value="{self.director.pk}"[^>]*checked')

    def test_step_three_saves_the_roles(self):
        person = Person.objects.create(first_name="Wendy", last_name="Wizard")
        response = self.client.post(reverse("actor-roles", args=[person.pk]), {"roles": [self.actor.pk, self.director.pk]})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(set(person.roles.all()), {self.actor, self.director})

    # ---- the whole way through
    def test_the_whole_wizard_with_a_photo(self):
        response = self.step_one()
        response = self.client.post(
            reverse("image-create"),
            {"image": self.photo(), "for_person": Person.objects.get().pk, "wizard": "1"},
            follow=False,
        )
        person = Person.objects.get()
        self.client.post(reverse("actor-roles", args=[person.pk]), {"roles": [self.actor.pk]})
        person.refresh_from_db()
        self.assertIsNotNone(person.image)
        self.assertEqual(list(person.roles.all()), [self.actor])
        self.assertIn(person, self.client.get(reverse("actor-list")).context["actors"])

    def test_the_whole_wizard_skipping_the_photo(self):
        self.step_one()
        person = Person.objects.get()
        self.assertEqual(self.client.get(reverse("actor-roles", args=[person.pk])).status_code, 200)
        self.client.post(reverse("actor-roles", args=[person.pk]), {"roles": [self.actor.pk]})
        person.refresh_from_db()
        self.assertIsNone(person.image)
        self.assertEqual(list(person.roles.all()), [self.actor])

    def test_the_wizard_needs_a_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("actor-new")).status_code, 302)
        self.assertEqual(self.client.get(reverse("actor-roles", args=[1])).status_code, 302)


class DeletePersonPhotoTests(TestCase):
    """Deleting a person asks whether their photo should go too."""

    def setUp(self):
        from backstage.models import Image

        self.client.force_login(CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!"))
        self.photo = Image.objects.create(description="Ann", image="images/ann.jpg", image_type="headshot")
        self.person = Person.objects.create(first_name="Ann", last_name="Actor", image=self.photo)

    def delete(self, **data):
        return self.client.post(reverse("person-delete", args=[self.person.pk]), data)

    def test_the_page_asks_about_the_photo(self):
        html = self.client.get(reverse("person-delete", args=[self.person.pk])).content.decode()
        self.assertIn('name="delete_image"', html)
        self.assertIn("Also delete their photo", html)
        self.assertIn("Otherwise the photo stays", html)

    def test_a_person_without_a_photo_is_not_asked(self):
        self.person.image = None
        self.person.save()
        html = self.client.get(reverse("person-delete", args=[self.person.pk])).content.decode()
        self.assertNotIn("delete_image", html)

    def test_by_default_the_photo_is_kept(self):
        from backstage.models import Image

        self.assertEqual(self.delete().status_code, 302)
        self.assertFalse(Person.objects.filter(pk=self.person.pk).exists())
        self.assertTrue(Image.objects.filter(pk=self.photo.pk).exists())

    def test_ticking_the_box_deletes_the_photo_too(self):
        from backstage.models import Image

        self.assertEqual(self.delete(delete_image="1").status_code, 302)
        self.assertFalse(Person.objects.filter(pk=self.person.pk).exists())
        self.assertFalse(Image.objects.filter(pk=self.photo.pk).exists())

    def test_the_page_warns_when_the_photo_is_used_elsewhere(self):
        Person.objects.create(first_name="Bo", last_name="Twin", image=self.photo)
        production = Production.objects.create(title="Panto")
        from backstage.models import ProductionImage

        ProductionImage.objects.create(production=production, image=self.photo)
        html = self.client.get(reverse("person-delete", args=[self.person.pk])).content.decode()
        self.assertIn("1 other person", html)
        self.assertIn("1 production", html)
        self.assertNotIn("Otherwise the photo stays", html)


class ImageDetailPeopleTests(TestCase):
    """A headshot's page says whose photo it is."""

    def setUp(self):
        import tempfile

        from django.test import override_settings

        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        override = override_settings(MEDIA_ROOT=self.media.name)
        override.enable()
        self.addCleanup(override.disable)
        self.client.force_login(CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!"))
        self.photo = self.make_image("Ann", "headshot")

    def make_image(self, description, image_type):
        from io import BytesIO

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image as PILImage

        from backstage.models import Image

        buffer = BytesIO()
        PILImage.new("RGB", (80, 100), (120, 120, 120)).save(buffer, "PNG")
        file = SimpleUploadedFile(f"{description.lower()}.png", buffer.getvalue(), content_type="image/png")
        return Image.objects.create(description=description, image=file, image_type=image_type)

    def page(self, image=None):
        return self.client.get(reverse("image-detail", args=[(image or self.photo).pk])).content.decode()

    def test_the_person_is_named_with_a_link(self):
        person = Person.objects.create(first_name="Ann", last_name="Actor", image=self.photo)
        html = self.page()
        self.assertIn("Photo of", html)
        self.assertIn(f'href="{reverse("person-detail", args=[person.pk])}" class="link font-semibold">Ann Actor</a>', html)

    def test_everyone_using_it_is_named(self):
        Person.objects.create(first_name="Ann", last_name="Actor", image=self.photo)
        Person.objects.create(first_name="Bo", last_name="Twin", image=self.photo)
        html = self.page()
        self.assertIn("Ann Actor", html)
        self.assertIn("Bo Twin", html)

    def test_a_headshot_nobody_uses_says_nothing(self):
        self.assertNotIn("Photo of", self.page())

    def test_other_types_of_image_do_not_say(self):
        poster = self.make_image("Poster", "promotion")
        Person.objects.create(first_name="Cy", last_name="Odd", image=poster)  # not a headshot, but used as a photo
        self.assertNotIn("Photo of", self.page(poster))


class UnusedHeadshotBadgeTests(TestCase):
    """The image library marks headshots that no person uses."""

    def setUp(self):
        from backstage.models import Image

        self.client.force_login(CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!"))
        self.used = Image.objects.create(description="Used", image="images/used.jpg", image_type="headshot")
        self.unused = Image.objects.create(description="Spare", image="images/spare.jpg", image_type="headshot")
        self.poster = Image.objects.create(description="Poster", image="images/poster.jpg", image_type="promotion")
        Person.objects.create(first_name="Ann", last_name="Actor", image=self.used)

    def badges(self, query=""):
        response = self.client.get(reverse("image-list") + query)
        return {image.description: image.has_person for image in response.context["object_list"]}, response.content.decode()

    def test_only_an_unused_headshot_gets_the_badge(self):
        import re

        _, html = self.badges()
        self.assertEqual(html.count(">Unused</span>"), 1)
        card = lambda name: re.search(rf'<a href="[^"]*" class="card[^>]*>(?:(?!</a>).)*{name}(?:(?!</a>).)*</a>', html, re.S).group(0)
        self.assertIn("Unused", card("Spare"))
        self.assertNotIn("Unused", card("Used"))
        self.assertNotIn("Unused", card("Poster"))

    def test_a_headshot_becomes_used_once_a_person_has_it(self):
        Person.objects.create(first_name="Bo", last_name="New", image=self.unused)
        _, html = self.badges()
        self.assertNotIn(">Unused</span>", html)

    def test_it_costs_no_extra_queries_per_image(self):
        from backstage.models import Image
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.client.get(reverse("image-list"))  # warm up: the first request does some one-off work
        with CaptureQueriesContext(connection) as few:
            self.client.get(reverse("image-list"))
        for n in range(10):
            Image.objects.create(description=f"More {n}", image=f"images/more{n}.jpg", image_type="headshot")
        with CaptureQueriesContext(connection) as many:
            self.client.get(reverse("image-list"))
        self.assertEqual(len(few), len(many))


class MissingImageFileTests(TestCase):
    """An image whose file has gone missing still has a page, instead of an error."""

    def setUp(self):
        from backstage.models import Image

        self.client.force_login(CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!"))
        self.image = Image.objects.create(description="Jan", image="images/not-there.jpg", image_type="headshot")

    def test_the_detail_page_says_the_file_is_missing(self):
        response = self.client.get(reverse("image-detail", args=[self.image.pk]))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('id="image-missing"', html)
        self.assertIn("The image file is missing", html)
        self.assertNotIn("not-there.jpg\" alt", html)  # no broken picture
        self.assertIn(reverse("image-update", args=[self.image.pk]), html)  # it can still be edited and replaced

    def test_the_library_and_the_edit_page_still_work(self):
        self.assertEqual(self.client.get(reverse("image-list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("image-update", args=[self.image.pk])).status_code, 200)

    def test_dimensions_are_none_without_the_file(self):
        self.assertFalse(self.image.file_exists)
        self.assertIsNone(self.image.dimensions)


class EventsTabEditButtonTests(TestCase):
    """On a production's Events tab each event has an Edit button; its title is not a link."""

    def setUp(self):
        from backstage.models import Event

        self.client.force_login(CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!"))
        self.production = Production.objects.create(title="Panto")
        self.other = Production.objects.create(title="Other")
        self.event = Event.objects.create(event_type="performance")
        self.event.productions.add(self.production)
        self.tab = reverse("production-events", args=[self.production.pk])

    def html(self):
        return self.client.get(self.tab).content.decode()

    def test_each_event_has_an_edit_button(self):
        html = self.html()
        self.assertIn(f'<a href="{reverse("event-update", args=[self.event.pk])}?production={self.production.pk}" class="btn btn-sm"', html)
        self.assertIn(">Edit</a>", html)

    def test_the_event_type_is_shown_in_large_text_not_a_badge_and_is_not_a_link(self):
        html = self.html()
        self.assertIn('<h3 class="text-3xl font-bold">Performance</h3>', html)
        self.assertNotIn("badge-success", html)  # the type used to be a coloured badge
        self.assertNotRegex(html, r'<span class="badge[^>]*>Performance</span>')
        self.assertNotIn(f'href="{reverse("event-detail", args=[self.event.pk])}"', html)
        self.assertNotIn("Opening night", html)  # events have no title

    def test_the_edit_page_goes_back_to_the_events_tab(self):
        url = reverse("event-update", args=[self.event.pk]) + f"?production={self.production.pk}"
        html = self.client.get(url).content.decode()
        self.assertIn(f'name="production" value="{self.production.pk}"', html)
        self.assertIn(f'href="{self.tab}" class="btn btn-ghost">Cancel', html)

    def test_saving_goes_back_to_the_events_tab(self):
        url = reverse("event-update", args=[self.event.pk])
        response = self.client.post(url, {
            "event_type": "rehearsal", "publish": "not_published", "description": "Run through", "venue": "",
            "production": self.production.pk,
        })
        self.assertRedirects(response, self.tab)
        self.event.refresh_from_db()
        self.assertEqual((self.event.event_type, self.event.description), ("rehearsal", "Run through"))

    def test_a_production_the_event_is_not_part_of_is_ignored(self):
        url = reverse("event-update", args=[self.event.pk])
        response = self.client.post(url, {
            "event_type": "performance", "publish": "not_published", "description": "", "venue": "", "ticket_site": "",
            "production": self.other.pk,
        })
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(response.url, reverse("production-events", args=[self.other.pk]))

    def test_editing_without_coming_from_a_production_is_as_before(self):
        html = self.client.get(reverse("event-update", args=[self.event.pk])).content.decode()
        self.assertNotIn('name="production"', html)
        self.assertEqual(self.client.get(reverse("event-update", args=[self.event.pk])).status_code, 200)


class EventTicketWebsiteTests(TestCase):
    """The ticket website of an event is a web address that is typed in, not a choice from a list."""

    def setUp(self):
        from backstage.models import Event

        self.client.force_login(CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!"))
        self.production = Production.objects.create(title="Panto")
        self.event = Event.objects.create(event_type="performance")
        self.event.productions.add(self.production)
        self.edit_url = reverse("event-update", args=[self.event.pk])

    def post_edit(self, **extra):
        data = {"event_type": "performance", "publish": "not_published", "description": "", "venue": "", **extra}
        return self.client.post(self.edit_url, data)

    def test_the_edit_page_has_a_web_address_field_and_no_ticket_site_list(self):
        html = self.client.get(self.edit_url).content.decode()
        self.assertRegex(html, r'<input type="url" name="ticket_url"[^>]*placeholder="https://\.\.\."')
        self.assertIn("Ticket website", html)
        self.assertNotIn('name="ticket_site"', html)
        self.assertNotIn("<select name=\"ticket_site\"", html)

    def test_the_new_event_dialog_has_it_too(self):
        html = self.client.get(reverse("production-events", args=[self.production.pk])).content.decode()
        self.assertRegex(html, r'<input type="url" name="ticket_url"')
        self.assertNotIn('name="ticket_site"', html)

    def test_typing_an_address_sets_the_events_ticket_site(self):
        from backstage.models import TicketSite

        response = self.post_edit(ticket_url="https://www.tickets.example.com/panto")
        self.assertEqual(response.status_code, 302)
        self.event.refresh_from_db()
        self.assertEqual(self.event.ticket_site.url, "https://www.tickets.example.com/panto")
        self.assertEqual(self.event.ticket_site.name, "tickets.example.com")  # named after the website
        self.assertEqual(TicketSite.objects.count(), 1)

    def test_the_same_address_uses_the_same_ticket_site(self):
        from backstage.models import Event, TicketSite

        other = Event.objects.create(event_type="performance")
        self.post_edit(ticket_url="https://tickets.example.com/panto")
        self.client.post(reverse("event-update", args=[other.pk]), {
            "title": "Matinee", "event_type": "performance", "publish": "not_published", "description": "", "venue": "", "ticket_url": "https://tickets.example.com/panto",
        })
        other.refresh_from_db()
        self.event.refresh_from_db()
        self.assertEqual(self.event.ticket_site, other.ticket_site)
        self.assertEqual(TicketSite.objects.count(), 1)

    def test_the_edit_page_shows_the_current_address(self):
        self.post_edit(ticket_url="https://tickets.example.com/panto")
        html = self.client.get(self.edit_url).content.decode()
        self.assertIn('value="https://tickets.example.com/panto"', html)

    def test_blank_removes_the_ticket_website(self):
        self.post_edit(ticket_url="https://tickets.example.com/panto")
        self.post_edit(ticket_url="")
        self.event.refresh_from_db()
        self.assertIsNone(self.event.ticket_site)

    def test_an_address_without_https_is_given_it(self):
        self.post_edit(ticket_url="tickets.example.com/panto")
        self.event.refresh_from_db()
        self.assertEqual(self.event.ticket_site.url, "https://tickets.example.com/panto")

    def test_something_that_is_not_an_address_is_refused(self):
        response = self.post_edit(ticket_url="not a web address")
        self.assertEqual(response.status_code, 200)
        self.event.refresh_from_db()
        self.assertIsNone(self.event.ticket_site)

    def test_creating_an_event_from_the_events_tab_with_an_address(self):
        response = self.client.post(reverse("production-events", args=[self.production.pk]), {
            "action": "create", "event_type": "performance", "publish": "not_published", "venue": "", "description": "",
            "ticket_url": "https://tickets.example.com/gala", "first_datetime": "",
        })
        self.assertEqual(response.status_code, 302)
        gala = self.production.events.get(ticket_site__url="https://tickets.example.com/gala")
        self.assertEqual(gala.ticket_site.url, "https://tickets.example.com/gala")

    def test_the_tab_shows_the_ticket_link(self):
        self.post_edit(ticket_url="https://tickets.example.com/panto")
        html = self.client.get(reverse("production-events", args=[self.production.pk])).content.decode()
        self.assertIn('href="https://tickets.example.com/panto"', html)

    def test_the_address_gives_the_promotion_block_its_buy_tickets_button(self):
        from datetime import timedelta

        from django.template.loader import render_to_string
        from django.utils import timezone

        from backstage.models import EventDateTime, Image, ProductionImage
        from home.models import Block

        EventDateTime.objects.create(event=self.event, datetime=timezone.now() + timedelta(days=5))
        poster = Image.objects.create(description="poster", image="images/poster.jpg", image_type="promotion")
        ProductionImage.objects.create(production=self.production, image=poster, is_default=True)
        self.post_edit(ticket_url="https://tickets.example.com/panto", publish="promoted")  # the promotion block uses promoted events
        block = Block.objects.create(name="Promo", block_type="promotion")
        self.assertIn('href="https://tickets.example.com/panto"', render_to_string(block.template, {"block": block}))


class BroadcastEventTests(TestCase):
    """A production's broadcast date is the date of its Broadcast event."""

    def setUp(self):
        from datetime import datetime, timezone as dt_timezone

        self.when = datetime(2026, 5, 22, 0, 0, tzinfo=dt_timezone.utc)
        self.client.force_login(CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!"))

    def test_broadcast_is_an_event_type(self):
        from backstage.models import Event

        self.assertIn(("broadcast", "Broadcast"), Event.EventType.choices)

    def test_the_production_has_no_broadcast_field_any_more(self):
        self.assertNotIn("broadcast_datetime", [f.name for f in Production._meta.get_fields()])

    def test_a_production_without_a_broadcast_event_has_no_date(self):
        production = Production.objects.create(title="Unaired")
        self.assertIsNone(production.broadcast_datetime)
        self.assertIsNone(Production.objects.with_broadcast_date().get().broadcast_at)

    def test_set_broadcast_makes_a_broadcast_event_connected_to_the_production(self):
        from backstage.models import Event

        production = Production.objects.create(title="Aired")
        production.set_broadcast(self.when)
        event = production.events.get()
        self.assertEqual(event.event_type, "broadcast")
        self.assertEqual(str(event), "Broadcast")
        self.assertEqual([d.datetime for d in event.datetimes.all()], [self.when])
        self.assertEqual(production.broadcast_datetime, self.when)
        self.assertEqual(Production.objects.with_broadcast_date().get().broadcast_at, self.when)
        self.assertEqual(Event.objects.count(), 1)

    def test_set_broadcast_again_changes_the_date_not_makes_another_event(self):
        from datetime import timedelta

        production = Production.objects.create(title="Aired")
        production.set_broadcast(self.when)
        production.set_broadcast(self.when + timedelta(days=7))
        self.assertEqual(production.events.count(), 1)
        self.assertEqual(production.broadcast_datetime, self.when + timedelta(days=7))

    def test_only_broadcast_events_count_for_the_date(self):
        from datetime import timedelta

        from backstage.models import Event, EventDateTime

        production = Production.objects.create(title="Show")
        for kind in ("performance", "audition", "rehearsal", "other"):
            event = Event.objects.create(event_type=kind)
            event.productions.add(production)
            EventDateTime.objects.create(event=event, datetime=self.when - timedelta(days=30))
        self.assertIsNone(production.broadcast_datetime)
        production.set_broadcast(self.when)
        self.assertEqual(production.broadcast_datetime, self.when)

    def test_the_first_broadcast_date_is_the_production_date(self):
        from datetime import timedelta

        from backstage.models import EventDateTime

        production = Production.objects.create(title="Repeated")
        production.set_broadcast(self.when)
        EventDateTime.objects.create(event=production.events.get(), datetime=self.when + timedelta(days=60))  # a repeat
        self.assertEqual(production.broadcast_datetime, self.when)
        self.assertEqual(Production.objects.with_broadcast_date().get().broadcast_at, self.when)

    def test_the_production_page_shows_the_date(self):
        production = Production.objects.create(title="Aired")
        production.set_broadcast(self.when)
        html = self.client.get(reverse("production-detail", args=[production.pk])).content.decode()
        self.assertIn("22 May 2026", html)

    def test_the_events_tab_lists_it_as_a_broadcast(self):
        production = Production.objects.create(title="Aired")
        production.set_broadcast(self.when)
        html = self.client.get(reverse("production-events", args=[production.pk])).content.decode()
        self.assertIn('<h3 class="text-3xl font-bold">Broadcast</h3>', html)
        self.assertNotIn("Aired broadcast", html)  # events have no title

    def test_the_production_form_no_longer_asks_for_a_broadcast_date(self):
        html = self.client.get(reverse("production-create")).content.decode()
        self.assertNotIn("broadcast_datetime", html)

    def test_the_production_list_sorts_by_the_broadcast_date(self):
        from datetime import timedelta

        early = Production.objects.create(title="Early")
        early.set_broadcast(self.when)
        late = Production.objects.create(title="Late")
        late.set_broadcast(self.when + timedelta(days=100))
        Production.objects.create(title="Undated")
        newest = [p.title for p in self.client.get(reverse("production-list") + "?sort=newest").context["object_list"]]
        oldest = [p.title for p in self.client.get(reverse("production-list") + "?sort=oldest").context["object_list"]]
        self.assertEqual(newest[:2], ["Late", "Early"])
        self.assertEqual(newest[-1], "Undated")  # no date goes last
        self.assertEqual(oldest[:2], ["Early", "Late"])
        self.assertEqual(oldest[-1], "Undated")

    def test_a_persons_productions_are_newest_broadcast_first(self):
        from datetime import timedelta

        from backstage.views import person_productions

        person = Person.objects.create(first_name="Ann", last_name="Actor")
        director = Role.objects.get_or_create(name="Director")[0]
        for title, days in (("Early", 0), ("Late", 100)):
            production = Production.objects.create(title=title)
            production.set_broadcast(self.when + timedelta(days=days))
            Cast.objects.create(production=production, character_name=title, actor=person)
            ProductionTeam.objects.create(production=production, person=person, role=director)
        cast_in, credits = person_productions(person)
        self.assertEqual([p.title for p, _ in cast_in], ["Late", "Early"])
        self.assertEqual([p.title for p in credits[0][1]], ["Late", "Early"])


class BroadcastMigrationTests(TransactionTestCase):
    """The data migration turns each production's broadcast date into a Broadcast event, and back again."""

    before = [("backstage", "0013_event_type_broadcast")]
    after = [("backstage", "0014_broadcast_events")]

    def apps_at(self, targets):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())  # leave the database as the code expects

    def test_forwards_and_backwards(self):
        from datetime import datetime, timezone as dt_timezone

        when = datetime(2025, 10, 2, 23, 0, tzinfo=dt_timezone.utc)
        old = self.apps_at(self.before)
        OldProduction = old.get_model("backstage", "Production")
        aired = OldProduction.objects.create(title="Aired", broadcast_datetime=when)
        unaired = OldProduction.objects.create(title="Unaired")

        new = self.apps_at(self.after)
        Event, EventDateTime = new.get_model("backstage", "Event"), new.get_model("backstage", "EventDateTime")
        Production = new.get_model("backstage", "Production")
        event = Production.objects.get(pk=aired.pk).events.get()
        self.assertEqual((event.event_type, event.title), ("broadcast", "Aired broadcast"))
        self.assertEqual([d.datetime for d in EventDateTime.objects.filter(event=event)], [when])
        self.assertFalse(Production.objects.get(pk=unaired.pk).events.exists())  # no date, no event
        self.assertEqual(Event.objects.count(), 1)

        back = self.apps_at(self.before)
        self.assertEqual(back.get_model("backstage", "Production").objects.get(pk=aired.pk).broadcast_datetime, when)
        self.assertEqual(back.get_model("backstage", "Event").objects.count(), 0)

    def test_running_it_twice_does_not_make_a_second_event(self):
        import importlib
        from datetime import datetime, timezone as dt_timezone

        when = datetime(2025, 1, 17, 0, 0, tzinfo=dt_timezone.utc)
        old = self.apps_at(self.before)
        old.get_model("backstage", "Production").objects.create(title="Aired", broadcast_datetime=when)
        new = self.apps_at(self.after)
        module = importlib.import_module("backstage.migrations.0014_broadcast_events")
        module.broadcast_dates_to_events(new, None)  # again
        self.assertEqual(new.get_model("backstage", "Event").objects.count(), 1)


class EventPublishTests(TestCase):
    """An event is Not published, Published or Promoted."""

    def setUp(self):
        from backstage.models import Event

        self.client.force_login(CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!"))
        self.production = Production.objects.create(title="Panto")
        self.event = Event.objects.create(event_type="performance")
        self.event.productions.add(self.production)
        self.edit_url = reverse("event-update", args=[self.event.pk])
        self.tab = reverse("production-events", args=[self.production.pk])

    def post_edit(self, **extra):
        data = {"event_type": "performance", "description": "", "venue": "", **extra}
        return self.client.post(self.edit_url, data)

    def test_the_options_are_not_published_published_and_promoted(self):
        from backstage.models import Event

        self.assertEqual(
            Event.Publish.choices,
            [("not_published", "Not published"), ("published", "Published"), ("promoted", "Promoted")],
        )

    def test_an_event_starts_not_published(self):
        self.assertEqual(self.event.publish, "not_published")
        self.assertEqual(self.event.get_publish_display(), "Not published")

    def test_the_edit_page_offers_the_three_options_with_the_current_one_chosen(self):
        html = self.client.get(self.edit_url).content.decode()
        self.assertRegex(html, r'<select name="publish"')
        for value, label in (("not_published", "Not published"), ("published", "Published"), ("promoted", "Promoted")):
            self.assertIn(f'<option value="{value}"', html)
            self.assertIn(f">{label}</option>", html)
        self.assertRegex(html, r'<option value="not_published" selected>')

    def test_the_new_event_dialog_offers_it_too(self):
        html = self.client.get(self.tab).content.decode()
        self.assertRegex(html, r'<select name="publish"')
        self.assertIn(">Promoted</option>", html)

    def test_each_option_can_be_saved(self):
        for value in ("published", "promoted", "not_published"):
            self.assertEqual(self.post_edit(publish=value).status_code, 302)
            self.event.refresh_from_db()
            self.assertEqual(self.event.publish, value)

    def test_something_else_is_refused(self):
        response = self.post_edit(publish="everywhere")
        self.assertEqual(response.status_code, 200)
        self.event.refresh_from_db()
        self.assertEqual(self.event.publish, "not_published")

    def test_a_new_event_from_the_tab_can_be_published_straight_away(self):
        self.client.post(self.tab, {
            "action": "create", "event_type": "rehearsal", "publish": "promoted",
            "venue": "", "description": "", "ticket_url": "", "first_datetime": "",
        })
        self.assertEqual(self.production.events.get(event_type="rehearsal").publish, "promoted")

    def test_the_tab_shows_published_and_promoted_events(self):
        from backstage.models import Event

        for title, value in (("Quiet", "not_published"), ("Out", "published"), ("Star", "promoted")):
            Event.objects.create(event_type="performance", publish=value).productions.add(self.production)
        html = self.client.get(self.tab).content.decode()
        self.assertEqual(html.count(">Published</span>"), 1)
        self.assertEqual(html.count(">Promoted</span>"), 1)
        self.assertNotIn(">Not published</span>", html)  # the usual state is not shown


class EventWithoutTitleTests(TestCase):
    """An event has no title: the Events tab shows its type, and Delete deletes the event."""

    def setUp(self):
        from datetime import timedelta

        from django.utils import timezone

        from backstage.models import Event, EventDateTime

        self.client.force_login(CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!"))
        self.production = Production.objects.create(title="Panto")
        self.other = Production.objects.create(title="Other")
        self.event = Event.objects.create(event_type="audition")
        self.event.productions.add(self.production)
        self.when = EventDateTime.objects.create(event=self.event, datetime=timezone.now() + timedelta(days=5))
        self.tab = reverse("production-events", args=[self.production.pk])

    def test_the_model_has_no_title(self):
        from backstage.models import Event

        self.assertNotIn("title", [f.name for f in Event._meta.get_fields()])
        self.assertEqual(str(self.event), "Audition")

    def test_the_forms_do_not_ask_for_a_title(self):
        html = self.client.get(self.tab).content.decode()
        self.assertNotIn('name="title"', html[html.index('id="new-event"'):])  # the New event dialog
        edit = self.client.get(reverse("event-update", args=[self.event.pk])).content.decode()
        self.assertNotIn('name="title"', edit)
        self.assertNotIn("Title", edit)

    def test_an_event_can_be_made_without_a_title(self):
        response = self.client.post(self.tab, {
            "action": "create", "event_type": "performance", "publish": "published", "venue": "", "description": "",
            "ticket_url": "", "first_datetime": "",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.production.events.filter(event_type="performance").count(), 1)

    def test_the_type_is_the_big_heading_of_each_event(self):
        from backstage.models import Event

        for kind in ("rehearsal", "performance", "broadcast", "other"):
            Event.objects.create(event_type=kind).productions.add(self.production)
        html = self.client.get(self.tab).content.decode()
        for label in ("Audition", "Rehearsal", "Performance", "Broadcast", "Other"):
            self.assertIn(f'<h3 class="text-3xl font-bold">{label}</h3>', html)
        self.assertNotRegex(html, r'<span class="badge[^>]*>(Audition|Rehearsal|Performance|Broadcast|Other)</span>')

    def test_there_is_no_add_an_existing_event(self):
        from backstage.models import Event

        elsewhere = Event.objects.create(event_type="performance")
        elsewhere.productions.add(self.other)
        html = self.client.get(self.tab).content.decode()
        self.assertNotIn("Add an existing event", html)
        self.assertNotIn('value="attach"', html)
        # and posting it does nothing
        self.client.post(self.tab, {"action": "attach", "event": elsewhere.pk})
        self.assertNotIn(elsewhere, self.production.events.all())

    def test_remove_is_now_delete(self):
        html = self.client.get(self.tab).content.decode()
        self.assertIn('name="action" value="delete"', html)
        self.assertRegex(html, r'>Delete</button>')
        self.assertNotIn('value="unlink"', html)
        self.assertNotRegex(html, r'>Remove</button>')

    def test_delete_asks_for_confirmation(self):
        html = self.client.get(self.tab).content.decode()
        self.assertIn("return confirm('Delete this audition and its dates?')", html)

    def test_delete_deletes_the_event_and_its_dates(self):
        from backstage.models import Event, EventDateTime

        response = self.client.post(self.tab, {"action": "delete", "event": self.event.pk})
        self.assertRedirects(response, self.tab)
        self.assertFalse(Event.objects.filter(pk=self.event.pk).exists())
        self.assertFalse(EventDateTime.objects.filter(pk=self.when.pk).exists())

    def test_only_this_productions_events_can_be_deleted_from_its_tab(self):
        from backstage.models import Event

        elsewhere = Event.objects.create(event_type="performance")
        elsewhere.productions.add(self.other)
        self.client.post(self.tab, {"action": "delete", "event": elsewhere.pk})
        self.assertTrue(Event.objects.filter(pk=elsewhere.pk).exists())

    def test_the_confirmation_warns_when_other_productions_share_the_event(self):
        self.event.productions.add(self.other)
        html = self.client.get(self.tab).content.decode()
        self.assertIn("It is also an event of other productions, and will be deleted for them too.", html)

    def test_no_warning_for_an_event_of_one_production(self):
        html = self.client.get(self.tab).content.decode()
        self.assertNotIn("also an event of other productions", html)

    def test_the_other_actions_still_work(self):
        from datetime import datetime

        self.client.post(self.tab, {"action": "add_datetime", "event": self.event.pk, "datetime": "2030-01-02T19:30"})
        self.assertEqual(self.event.datetimes.count(), 2)
        self.client.post(self.tab, {"action": "remove_datetime", "datetime_id": self.when.pk})
        self.assertEqual(self.event.datetimes.count(), 1)


class EventTypeFieldsTests(TestCase):
    """A performance has a ticket website, a broadcast a listen address; other types neither."""

    def data(self, event_type, **extra):
        return {"event_type": event_type, "publish": "published", "ticket_url": "https://tickets.example.com/x",
                "listen_url": "https://listen.example.com/x", **extra}

    def test_a_broadcast_keeps_only_its_listen_address(self):
        from backstage.forms import EventDetailsForm

        form = EventDetailsForm(self.data("broadcast"))
        self.assertTrue(form.is_valid(), form.errors)
        event = form.save()
        self.assertEqual((event.listen_url, event.ticket_site), ("https://listen.example.com/x", None))

    def test_a_performance_keeps_only_its_ticket_website(self):
        from backstage.forms import EventDetailsForm

        form = EventDetailsForm(self.data("performance"))
        self.assertTrue(form.is_valid(), form.errors)
        event = form.save()
        self.assertEqual((event.listen_url, event.ticket_site.url), ("", "https://tickets.example.com/x"))

    def test_other_types_have_neither(self):
        from backstage.forms import EventDetailsForm

        form = EventDetailsForm(self.data("audition"))
        self.assertTrue(form.is_valid(), form.errors)
        event = form.save()
        self.assertEqual((event.listen_url, event.ticket_site), ("", None))

    def test_the_forms_have_the_script_that_shows_the_right_field(self):
        from accounts.models import CustomUser

        self.client.force_login(CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!"))
        production = Production.objects.create(title="A Play")
        self.assertContains(self.client.get(reverse("production-events", args=[production.pk])), "id_listen_url")
        self.assertContains(self.client.get(reverse("event-create")), "update()")


class ListenUrlOnBroadcastEventTests(TestCase):
    def test_a_production_listen_url_is_that_of_its_broadcast_event(self):
        from backstage.models import Event

        production = Production.objects.create(title="A Radio Play", type="radio")
        self.assertEqual((production.listen_url, production.public_listen_url), ("", ""))
        event = Event.objects.create(event_type="broadcast", listen_url="https://listen.example.com/a")
        event.productions.add(production)
        self.assertEqual((production.listen_url, production.public_listen_url), ("https://listen.example.com/a", ""))  # not published yet
        event.publish = "published"
        event.save()
        self.assertEqual(production.public_listen_url, "https://listen.example.com/a")

    def test_broadcast_event_makes_one_if_there_is_none(self):
        from backstage.models import Event

        production = Production.objects.create(title="A Radio Play", type="radio")
        event = production.broadcast_event()
        self.assertEqual((event.event_type, event.publish), ("broadcast", "published"))
        self.assertEqual(production.broadcast_event(), event)  # and then finds it
        self.assertEqual(Event.objects.count(), 1)

    def test_the_import_puts_the_listen_address_on_the_broadcast_event(self):
        from datetime import date

        from django.core.management import call_command
        from unittest import mock

        play = {
            "title": "Imported Play", "description": "", "credits": [], "cast": [], "image_url": None,
            "listen_url": "https://example.com/imported.mp3", "broadcast_date": date(2026, 6, 19),
        }
        with mock.patch("scraper.scrape.scrape_radio", return_value=[play]):
            call_command("import_radio_plays", "--no-images", stdout=mock.MagicMock())
        production = Production.objects.get(title="Imported Play")
        self.assertEqual(production.listen_url, "https://example.com/imported.mp3")
        self.assertEqual(production.events.filter(event_type="broadcast").count(), 1)


class ProductionPublishedFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from accounts.models import CustomUser
        from backstage.models import Event

        cls.user = CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!")

        def make(title, *publishes):
            production = Production.objects.create(title=title)
            for publish in publishes:
                Event.objects.create(event_type="performance", publish=publish).productions.add(production)

        make("Live Play", "published")
        make("Promoted Play", "not_published", "promoted")
        make("Draft Play", "not_published")
        make("No Events Play")

    def setUp(self):
        self.client.force_login(self.user)

    def titles(self, query=""):
        response = self.client.get(reverse("production-list") + query)
        return sorted(p.title for p in response.context["object_list"])

    def test_published_means_a_published_or_promoted_event(self):
        self.assertEqual(self.titles("?published=published"), ["Live Play", "Promoted Play"])

    def test_not_published_is_the_rest(self):
        self.assertEqual(self.titles("?published=not_published"), ["Draft Play", "No Events Play"])

    def test_it_is_off_by_default_and_works_with_the_other_filters(self):
        self.assertEqual(len(self.titles()), 4)
        self.assertEqual(self.titles("?published=published&q=promoted"), ["Promoted Play"])
        self.assertEqual(len(self.titles("?published=nonsense")), 4)
        self.assertContains(self.client.get(reverse("production-list")), 'name="published"')


class ProductionDetailEventBadgesTests(TestCase):
    def test_the_details_tab_shows_a_badge_for_each_event_type(self):
        from accounts.models import CustomUser
        from backstage.models import Event, EventDateTime
        from datetime import datetime, timezone as tz

        self.client.force_login(CustomUser.objects.create_user("member", "member@example.com", "a-Long-pa55word!"))
        production = Production.objects.create(title="A Play")
        self.assertContains(self.client.get(reverse("production-detail", args=[production.pk])), "<dd class=\"flex flex-wrap gap-1\">—</dd>")
        for event_type in ("performance", "performance", "broadcast", "audition"):
            Event.objects.create(event_type=event_type).productions.add(production)
        self.assertEqual(production.event_type_counts(), [("Audition", 1), ("Performance", 2), ("Broadcast", 1)])
        html = self.client.get(reverse("production-detail", args=[production.pk])).content.decode()
        for badge in ("Audition</span>", "Performance × 2</span>", "Broadcast</span>"):
            self.assertIn(badge, html)
        event = production.events.get(event_type="broadcast")
        EventDateTime.objects.create(event=event, datetime=datetime(2026, 6, 19, 14, 30, tzinfo=tz.utc))
        html = self.client.get(reverse("production-detail", args=[production.pk])).content.decode()
        self.assertIn("19 June 2026", html)
        self.assertNotIn("19 June 2026, ", html)  # no time

