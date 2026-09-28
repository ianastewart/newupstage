import os
from urllib.parse import unquote, urlparse

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from backstage.models import Image, Person, Role


class Command(BaseCommand):
    help = "Import performers from the Upstage Theatre Company website as people with the Actor role"
    role_name = "Actor"
    kind = "performers"

    def scrape(self, url):
        from scraper.scrape import PERFORMERS_URL, scrape_performers

        return scrape_performers(url or PERFORMERS_URL)

    def add_arguments(self, parser):
        parser.add_argument("--url", help=f"{self.kind.capitalize()} page URL; add #Anchor to import one entry")
        parser.add_argument("--limit", type=int, help=f"Only import the first N {self.kind}")
        parser.add_argument("--no-images", action="store_true", help="Don't download photos")
        parser.add_argument("--overwrite", action="store_true", help="Replace existing biographies and photos")
        parser.add_argument("--dry-run", action="store_true", help="Show what would happen without saving")

    def handle(self, *args, **options):
        # Imported here: requests/bs4 are development dependencies.
        import requests

        from scraper.scrape import HEADERS

        self.requests = requests
        self.headers = HEADERS
        performers = self.scrape(options["url"])
        if options["limit"]:
            performers = performers[: options["limit"]]
        self.stdout.write(f"Found {len(performers)} {self.kind}")

        counts = {"created": 0, "updated": 0, "unchanged": 0, "images": 0, "failed": 0}

        for performer in performers:
            try:
                with transaction.atomic():
                    outcome, downloaded = self.import_performer(performer, options)
                counts[outcome] += 1
                counts["images"] += downloaded
            except Exception as error:  # Keep going if one performer fails.
                counts["failed"] += 1
                self.stderr.write(self.style.ERROR(f"  {performer['name']}: {error}"))

        prefix = "Dry run: would have " if options["dry_run"] else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}created {counts['created']}, updated {counts['updated']}, "
                f"unchanged {counts['unchanged']}, photos {counts['images']}, failed {counts['failed']}"
            )
        )

    def import_performer(self, performer, options):
        """Create or update one person. Returns (outcome, photos downloaded)."""
        person = Person.objects.filter(
            first_name__iexact=performer["first_name"], last_name__iexact=performer["last_name"]
        ).first()
        words = performer["name"].split()
        if not person and len(words) > 2:
            # "John Louis Williams" may already be in as "John Williams" (e.g. from a radio cast list).
            person = Person.objects.filter(first_name__iexact=words[0], last_name__iexact=words[-1]).first()
        created = person is None
        want_bio = performer["biography"] and (created or options["overwrite"] or not person.biography)
        want_photo = (
            not options["no_images"]
            and performer["image_url"]
            and (created or options["overwrite"] or not person.image_id)
        )
        # Scraped entries may carry their own roles (e.g. the team page); otherwise use the command's role.
        role_names = performer.get("roles") or [name for name in [self.role_name] if name]
        existing = set() if created else set(person.roles.values_list("name", flat=True))
        new_roles = [name for name in role_names if name not in existing]

        if options["dry_run"]:
            changes = [c for c, wanted in [("biography", want_bio), ("photo", want_photo), (f"{' + '.join(new_roles)} role", new_roles)] if wanted]
            self.stdout.write(f"  {'create' if created else 'update'} {performer['name']}: {', '.join(changes) or 'no changes'}")
            return ("created" if created else "updated" if changes else "unchanged"), 0

        if created:
            person = Person(first_name=performer["first_name"], last_name=performer["last_name"])
        if want_bio:
            person.biography = performer["biography"]
        downloaded = 0
        if want_photo:
            person.image = self.download_photo(performer)
            downloaded = 1
        person.save()
        if new_roles:
            person.roles.add(*(Role.objects.get_or_create(name=name)[0] for name in new_roles))

        changed = created or want_bio or want_photo or new_roles
        outcome = "created" if created else "updated" if changed else "unchanged"
        self.stdout.write(f"  {outcome} {performer['name']}")
        return outcome, downloaded

    def download_photo(self, performer):
        """Download the performer's photo into the image library as a headshot."""
        response = self.requests.get(performer["image_url"], headers=self.headers, timeout=60)
        response.raise_for_status()
        extension = os.path.splitext(unquote(urlparse(performer["image_url"]).path))[1].lower() or ".jpg"
        image = Image(description=performer["name"], image_type=Image.ImageType.HEADSHOT)
        image.image.save(f"{slugify(performer['name'])}{extension}", ContentFile(response.content), save=False)
        image.save()
        return image
