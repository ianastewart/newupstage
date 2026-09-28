from .import_performers import Command as ImportPerformersCommand


class Command(ImportPerformersCommand):
    help = (
        "Import writers from the Upstage Theatre Company website: existing people get the "
        "Writer role, anyone new is created with it"
    )
    role_name = "Writer"
    kind = "writers"

    def scrape(self, url):
        from scraper.scrape import WRITERS_URL, scrape_writers

        return scrape_writers(url or WRITERS_URL)
