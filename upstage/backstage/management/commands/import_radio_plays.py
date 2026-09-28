import os
from collections import Counter
from datetime import datetime, time
from urllib.parse import unquote, urlparse

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from backstage.models import Cast, Image, Person, Production, ProductionImage, ProductionTeam, Role

CREDIT_ROLES = ["Writer", "Director", "Editor"]


class Command(BaseCommand):
    help = "Import radio plays from the Upstage Theatre Company website as productions"

    def add_arguments(self, parser):
        parser.add_argument("--url", help="Radio plays page URL")
        parser.add_argument("--limit", type=int, help="Only import the first N plays")
        parser.add_argument("--no-images", action="store_true", help="Don't download images")
        parser.add_argument("--overwrite", action="store_true", help="Replace existing descriptions and listen URLs")
        parser.add_argument("--dry-run", action="store_true", help="Show what would be imported without saving")

    def handle(self, *args, **options):
        # Imported here: requests/bs4 are development dependencies.
        import requests

        from scraper.scrape import HEADERS, RADIO_URL, match_name, scrape_radio

        self.requests, self.headers, self.match_name = requests, HEADERS, match_name
        self.people = {f"{p.first_name} {p.last_name}": p for p in Person.objects.all()}
        self.created_people = Counter()

        plays = scrape_radio(options["url"] or RADIO_URL, known_names=list(self.people))
        if options["limit"]:
            plays = plays[: options["limit"]]
        self.stdout.write(f"Found {len(plays)} radio plays")

        if not options["dry_run"]:
            self.roles = {name: Role.objects.get_or_create(name=name)[0] for name in [*CREDIT_ROLES, "Actor"]}

        counts = Counter()
        for play in plays:
            try:
                with transaction.atomic():
                    counts[self.import_play(play, options)] += 1
            except Exception as error:  # Keep going if one play fails.
                counts["failed"] += 1
                self.stderr.write(self.style.ERROR(f"  {play['title']}: {error}"))

        prefix = "Dry run: would have " if options["dry_run"] else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}created {counts['created']}, updated {counts['updated']}, failed {counts['failed']}"
        ))
        if self.created_people:
            self.stdout.write(self.style.WARNING(
                f"{prefix}created people who weren't in the database (check for misspellings):"
            ))
            for name, count in sorted(self.created_people.items()):
                self.stdout.write(f"  {name} ({count})")

    def find_person(self, name, role, dry_run=False):
        """The person called `name` (tolerating small typos), created if they don't exist yet."""
        known = self.match_name(name, self.people)
        if not known:
            self.created_people[name] += 1
            if dry_run:
                self.people[name] = None  # Count each new person once.
                return None
            first_name, _, last_name = name.partition(" ")
            self.people[name] = Person.objects.create(first_name=first_name, last_name=last_name)
            known = name
        person = self.people[known]
        if person and not dry_run:
            person.roles.add(self.roles[role])
        return person

    def import_play(self, play, options):
        production = Production.objects.filter(
            title__iexact=play["title"], type=Production.ProductionType.RADIO
        ).first()
        created = production is None

        # Credits and cast: people who aren't in the database yet are created.
        dry_run = options["dry_run"]
        team = [(self.find_person(credit["name"], credit["role"], dry_run), credit["role"]) for credit in play["credits"]]
        description = play["description"]
        cast = [
            (self.find_person(actor, "Actor", dry_run), entry["character"])
            for entry in play["cast"]
            for actor in entry["actors"]
        ]

        if dry_run:
            self.stdout.write(
                f"  {'create' if created else 'update'} {play['title']}: {len(team)} team, "
                f"{len(cast)} cast, listen {'yes' if play['listen_url'] else 'no'}"
            )
            return "created" if created else "updated"

        if created:
            production = Production(
                title=play["title"],
                type=Production.ProductionType.RADIO,
                state=Production.ProductionState.PUBLISHED,
            )
        if description and (created or options["overwrite"] or not production.description):
            production.description = description
        if play["listen_url"] and (created or options["overwrite"] or not production.listen_url):
            production.listen_url = play["listen_url"]
        if play["broadcast_date"] and (created or options["overwrite"] or not production.broadcast_datetime):
            # The podcast file name only has the date; store midnight UK time.
            production.broadcast_datetime = timezone.make_aware(datetime.combine(play["broadcast_date"], time()))
        production.save()

        for person, role in team:
            ProductionTeam.objects.get_or_create(production=production, person=person, role=self.roles[role])

        for person, character in cast:
            Cast.objects.get_or_create(production=production, character_name=character, actor=person)
            # Earlier imports kept unknown performers as "Played by <name>" placeholders.
            Cast.objects.filter(
                production=production, character_name=character, actor=None, characteristics__startswith="Played by "
            ).delete()

        wants_image = play["image_url"] and not options["no_images"] and not production.images.exists()
        if wants_image:
            ProductionImage.objects.create(production=production, image=self.download_image(play), is_default=True)

        self.stdout.write(f"  {'created' if created else 'updated'} {play['title']}")
        return "created" if created else "updated"

    def download_image(self, play):
        """Download the play's image into the image library as a promotion image."""
        response = self.requests.get(play["image_url"], headers=self.headers, timeout=60)
        response.raise_for_status()
        extension = os.path.splitext(unquote(urlparse(play["image_url"]).path))[1].lower() or ".jpg"
        image = Image(description=play["title"], image_type=Image.ImageType.PROMOTION)
        image.image.save(f"{slugify(play['title'])}{extension}", ContentFile(response.content), save=False)
        image.save()
        return image
