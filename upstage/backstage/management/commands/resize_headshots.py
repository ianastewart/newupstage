import os
import shutil
from datetime import datetime

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from PIL import Image as PILImage
from PIL import ImageChops

from backstage.fields import HEADSHOT_SIZE
from backstage.models import Image


def is_black_and_white(photo):
    """
    Whether an opened photo has no colour. A greyscale file is; so is a colour-mode file whose three channels match
    (WebP cannot store a single grey channel, and its compression leaves a difference of at most 1 or 2).
    """
    if photo.mode in ("L", "LA"):
        return True
    if photo.mode not in ("RGB", "RGBA"):
        return False
    red, green, blue = photo.convert("RGB").split()
    return all(ImageChops.difference(a, b).getextrema()[1] <= 2 for a, b in ((red, green), (green, blue)))


class Command(BaseCommand):
    help = (
        "Redo the existing headshots in the image library like new uploads: black and white, scaled to cover "
        f"{HEADSHOT_SIZE[0]} x {HEADSHOT_SIZE[1]} and cropped from the centre. Each original is copied to a backup "
        "folder first. Headshots that are already done are skipped, so it is safe to run again."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Show what would change without changing anything")
        parser.add_argument(
            "--backup-dir",
            help="Where to copy the original files (default: media_backups/headshots-<date and time> beside manage.py)",
        )

    def handle(self, *args, **options):
        self.dry_run = options["dry_run"]
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.backup_dir = options["backup_dir"] or os.path.join(settings.BASE_DIR, "media_backups", f"headshots-{stamp}")
        target = tuple(HEADSHOT_SIZE)

        done, skipped, missing, failed, upscaled = [], [], [], [], []
        before_bytes = after_bytes = 0
        headshots = Image.objects.filter(image_type=Image.ImageType.HEADSHOT).exclude(image="").order_by("id")
        self.stdout.write(f"{headshots.count()} headshots")

        for image in headshots:
            name = image.image.name
            if not os.path.exists(image.image.path):
                missing.append(name)
                continue
            with PILImage.open(image.image.path) as current:
                size, grey = current.size, is_black_and_white(current)
            if size == target and grey:
                skipped.append(name)  # already black and white at the right size
                continue
            if size[0] < target[0] or size[1] < target[1]:
                upscaled.append((name, size))  # the photo is smaller than the new size, so it is enlarged
            size_before = os.path.getsize(image.image.path)
            if self.dry_run:
                done.append(name)
                before_bytes += size_before
                continue
            try:
                new_name = self.redo(image)
            except Exception as error:  # the original has been put back: carry on with the others
                failed.append((name, error))
                continue
            done.append(name)
            before_bytes += size_before
            after_bytes += os.path.getsize(image.image.path)
            if new_name != name:
                self.stdout.write(f"  renamed {name} -> {new_name}")

        verb = "Would redo" if self.dry_run else "Redone"
        self.stdout.write(self.style.SUCCESS(f"{verb} {len(done)} headshots"))
        self.stdout.write(f"{len(skipped)} were already done and were left alone")
        if missing:
            self.stdout.write(self.style.WARNING(f"{len(missing)} have no file and were skipped: " + ", ".join(missing)))
        if upscaled:
            self.stdout.write(
                self.style.WARNING(f"{len(upscaled)} are smaller than {target[0]} x {target[1]} so are enlarged (they will look soft):")
            )
            for name, size in upscaled:
                self.stdout.write(f"    {name} ({size[0]} x {size[1]})")
        for name, error in failed:
            self.stdout.write(self.style.ERROR(f"FAILED {name}: {error} (the original was put back)"))
        if not self.dry_run and done:
            self.stdout.write(f"Files went from {before_bytes // 1024} KB to {after_bytes // 1024} KB")
            self.stdout.write(f"The originals are copied in {self.backup_dir}")

    def redo(self, image):
        """Back the original up, then replace the image with its new version. On failure the original is put back."""
        storage = image.image.storage
        old_name = image.image.name
        os.makedirs(self.backup_dir, exist_ok=True)
        backup = os.path.join(self.backup_dir, old_name.replace("/", os.sep))
        os.makedirs(os.path.dirname(backup), exist_ok=True)
        shutil.copy2(image.image.path, backup)
        with open(backup, "rb") as original:
            data = original.read()
        storage.delete(old_name)  # so that the new file can take the same name
        try:
            image.image.save(os.path.basename(old_name), ContentFile(data), save=True)
        except Exception:
            # Put the original file and its name back.
            if storage.exists(old_name):
                storage.delete(old_name)
            storage.save(old_name, ContentFile(data))
            image.image.name = old_name
            image.save(update_fields=["image"])
            raise
        return image.image.name
