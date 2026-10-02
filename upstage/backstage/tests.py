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
