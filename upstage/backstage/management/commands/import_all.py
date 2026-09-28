from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from backstage.models import Cast, Image, Person, Production, ProductionImage, ProductionTeam

# Order matters: people come first so the radio plays can link their cast and credits
# to people who already have biographies and photos.
IMPORTS = ["import_performers", "import_writers", "import_team", "import_radio_plays"]


class Command(BaseCommand):
    help = (
        "Import everything from the Upstage Theatre Company website: performers, writers, "
        "team, then radio plays"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--new", action="store_true",
            help="First delete all people, productions (with their cast, team and images) and the image library",
        )
        parser.add_argument("--noinput", "--no-input", action="store_false", dest="interactive",
                            help="Don't ask for confirmation before --new deletes data")
        parser.add_argument("--no-images", action="store_true", help="Don't download photos and images")
        parser.add_argument("--overwrite", action="store_true",
                            help="Replace existing biographies, photos, descriptions, listen URLs and dates")

    def handle(self, *args, **options):
        if options["new"]:
            self.wipe(options["interactive"])

        call_command("init_roles")
        shared = {"no_images": options["no_images"], "overwrite": options["overwrite"]}
        for command in IMPORTS:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n{command}"))
            call_command(command, stdout=self.stdout, stderr=self.stderr, **shared)

    def wipe(self, interactive):
        counts = {
            "people": Person.objects.count(),
            "productions": Production.objects.count(),
            "images": Image.objects.count(),
        }
        summary = ", ".join(f"{count} {name}" for name, count in counts.items())
        if interactive:
            answer = input(
                f"This deletes {summary}, plus all cast, production team and production image links "
                "and the image files. Type 'yes' to continue: "
            )
            if answer.strip().lower() != "yes":
                raise CommandError("Cancelled; nothing was deleted.")

        files = [image.image for image in Image.objects.exclude(image="")]
        with transaction.atomic():
            for model in (Cast, ProductionTeam, ProductionImage, Production, Person, Image):
                model.objects.all().delete()
        # Files are removed only once the database delete has succeeded.
        for file in files:
            file.storage.delete(file.name)
        self.stdout.write(self.style.WARNING(f"Deleted {summary} and {len(files)} image files"))
