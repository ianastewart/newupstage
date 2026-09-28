from .import_performers import Command as ImportPerformersCommand


class Command(ImportPerformersCommand):
    help = (
        "Import the team from the Upstage Theatre Company 'who we are' page: existing people "
        "get the roles from their job titles, anyone new is created with them"
    )
    role_name = None  # Each team member's roles come from their job title.
    kind = "team members"

    def scrape(self, url):
        from scraper.scrape import TEAM_URL, scrape_team

        team = scrape_team(url or TEAM_URL)
        for member in team:
            if not member["roles"]:
                self.stderr.write(self.style.WARNING(f"  No roles for {member['name']} ({member['title'] or 'no title'})"))
        return team
