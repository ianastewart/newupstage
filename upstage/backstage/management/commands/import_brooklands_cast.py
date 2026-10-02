import difflib
import re
from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction

from backstage.models import Cast, Person, Production, ProductionTeam, Role


def _normal(title):
    """A title for comparing: lower case, no punctuation or apostrophes ("Life’s Too Long" = "Lifes too long")."""
    return re.sub(r"[^a-z0-9]+", " ", re.sub(r"['’�]", "", title.lower())).strip()


class Command(BaseCommand):
    help = (
        "Read the plays on the Brooklands Radio Playhouse page. For each one that matches a radio play production, "
        "make a cast list from the Brooklands text if the production has none, and add any writer, director or editor "
        "missing from its team. People and roles are created if needed."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Show what would change without saving anything")

    def handle(self, *args, **options):
        # Imported here: requests/bs4 are development dependencies.
        from scraper.scrape import brooklands_plays, match_name, parse_brooklands_cast, parse_brooklands_credits

        self.match_name = match_name
        self.dry_run = options["dry_run"]
        self.people = {f"{p.first_name} {p.last_name}".strip(): p for p in Person.objects.all()}
        self.roles = {role.name: role for role in Role.objects.all()}
        self.new_people = Counter()
        self.new_roles = set()
        self.given_role = {}  # person -> the roles they were given

        plays = brooklands_plays()
        self.stdout.write(f"Read {len(plays)} plays from Brooklands Radio")

        productions = list(Production.objects.filter(type=Production.ProductionType.RADIO))
        by_title = {}
        for production in productions:
            by_title.setdefault(_normal(production.title), []).append(production)

        changed, unmatched, nothing_to_add = [], [], 0
        for play in plays:
            production = self.find_production(play["title"], by_title)
            if production is None:
                unmatched.append(play["title"])
                continue
            cast = []
            if not production.cast.exists():
                cast = parse_brooklands_cast(play["raw_text"], list(self.people))
            credits = parse_brooklands_credits(play["raw_text"], play["title"])
            with transaction.atomic():
                cast_rows = self.add_cast(production, cast)
                team_rows = self.add_team(production, credits)
            if cast_rows or team_rows:
                changed.append((production, cast_rows, team_rows))
            else:
                nothing_to_add += 1

        prefix = "Would change" if self.dry_run else "Changed"
        self.stdout.write("")
        for production, cast_rows, team_rows in changed:
            self.stdout.write(self.style.SUCCESS(production.title))
            for character, actor in cast_rows:
                self.stdout.write(f"    Cast: {character}: {actor}")
            for role, name in team_rows:
                self.stdout.write(f"    Team: {role}: {name}")
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{prefix} {len(changed)} productions"))
        self.stdout.write(f"{nothing_to_add} matching productions had nothing to add")
        if unmatched:
            self.stdout.write(f"{len(unmatched)} Brooklands plays have no radio play production: " + "; ".join(unmatched))
        verb = "would be" if self.dry_run else "were"
        if self.new_roles:
            self.stdout.write(self.style.WARNING(f"Roles that {verb} created: " + ", ".join(sorted(self.new_roles))))
        if self.new_people:
            self.stdout.write(self.style.WARNING(f"People who {verb} created (check for misspellings):"))
            for name, count in sorted(self.new_people.items()):
                self.stdout.write(f"    {name} ({count})")
        if self.given_role:
            self.stdout.write(f"Existing people who {verb} given a role they didn't have:")
            for name, roles in sorted(self.given_role.items()):
                self.stdout.write(f"    {name}: {', '.join(sorted(roles))}")

    def find_production(self, title, by_title):
        """The radio play production for a Brooklands title: the same title, or a very close one."""
        wanted = _normal(title)
        candidates = by_title.get(wanted)
        if not candidates:
            close = difflib.get_close_matches(wanted, by_title, n=1, cutoff=0.9)
            candidates = by_title[close[0]] if close else []
        # If several productions share the title, one without a cast is the one to fill in.
        return next((p for p in candidates if not p.cast.exists()), candidates[0] if candidates else None)

    def role(self, name):
        """The role called `name`, created if there isn't one (in a dry run: noted, and None)."""
        if name not in self.roles:
            self.new_roles.add(name)
            if self.dry_run:
                return None
            self.roles[name] = Role.objects.create(name=name)
        return self.roles[name]

    def find_person(self, name, role_name):
        """
        The person called `name` (tolerating small typos), created if they don't exist yet, and given the role
        (Actor, Writer...) if they don't have it. In a dry run nothing is saved, and a new person comes back as None.
        """
        known = self.match_name(name, self.people)
        if known is None:
            self.new_people[name] += 1
            if self.dry_run:
                self.people[name] = None  # so each new person is counted once
                self.role(role_name)
                return None
            first_name, _, last_name = name.partition(" ")
            self.people[name] = Person.objects.create(first_name=first_name, last_name=last_name)
            known = name
        person = self.people[known]
        if person is None:
            return None  # a new person seen already in this dry run
        role = self.role(role_name)
        if role is None or not person.roles.filter(pk=role.pk).exists():
            self.given_role.setdefault(str(person), set()).add(role_name)
            if not self.dry_run:
                person.roles.add(role)
        return person

    def add_cast(self, production, cast):
        """Add the cast to the production; returns [(character, actor name)] for printing."""
        rows = []
        for entry in cast:
            for actor in entry["actors"]:
                person = self.find_person(actor, "Actor")
                if not self.dry_run:
                    Cast.objects.get_or_create(production=production, character_name=entry["character"], actor=person)
                rows.append((entry["character"], str(person) if person else actor))
        return rows

    def add_team(self, production, credits):
        """Add the writer, director and editor credits that the production's team is missing; returns [(role, name)]."""
        rows = []
        for credit in credits:
            known = self.match_name(credit["name"], self.people)
            existing = self.people.get(known) if known else None
            role = self.roles.get(credit["role"])
            if existing and role and ProductionTeam.objects.filter(production=production, person=existing, role=role).exists():
                continue  # already on the team
            person = self.find_person(credit["name"], credit["role"])
            if not self.dry_run:
                ProductionTeam.objects.get_or_create(
                    production=production, person=person, role=self.role(credit["role"])
                )
            rows.append((credit["role"], str(person) if person else credit["name"]))
        return rows
