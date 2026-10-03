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

    def test_the_sort_choices_keep_the_type_and_the_types_keep_the_sort(self):
        html = self.client.get(reverse("image-list") + "?type=headshot&sort=newest").content.decode()
        self.assertIn('href="?type=headshot"', html)  # Name, keeping the type
        self.assertIn('href="?sort=newest&amp;type=headshot"', html)  # Newest first, keeping the type
        self.assertIn('href="?type=base&amp;sort=newest"', html)  # another type, keeping the sort
        self.assertIn('href="?sort=newest"', html)  # All, keeping the sort
        self.assertRegex(html, r'href="\?sort=newest&amp;type=headshot" class="tab tab-active"')
        by_name = self.client.get(reverse("image-list") + "?type=headshot").content.decode()
        self.assertIn('href="?type=base"', by_name)  # no sort in the links when it is the default
        self.assertRegex(by_name, r'href="\?type=headshot" class="tab tab-active"')

    def test_the_page_links_keep_the_sort_and_type(self):
        from backstage.models import Image

        for number in range(30):
            Image.objects.create(description=f"Extra {number:02d}", image=f"images/e{number}.jpg", image_type="headshot")
        html = self.client.get(reverse("image-list") + "?type=headshot&sort=newest").content.decode()
        self.assertIn("type=headshot&sort=newest&page=2", html)
        second = self.client.get(reverse("image-list") + "?type=headshot&sort=newest&page=2")
        self.assertIn("type=headshot&sort=newest&page=1", second.content.decode())
        newest = [image.pk for image in Image.objects.filter(image_type="headshot").order_by("-id")]
        self.assertEqual([i.pk for i in second.context["object_list"]], newest[24:])

