"""Who may do what: the two groups that control access, and the check for each (superusers always pass)."""

BACKSTAGE_GROUP = "backstage"  # may make backstage changes, on the live site and on the sandbox
SANDBOX_GROUP = "sandbox"  # may see the sandbox site at all (only needed there)


def in_group(user, group_name):
    """Whether the user is a superuser or in the group. Looked up once per user object (so once per request)."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    cache = user.__dict__.setdefault("_group_access", {})
    if group_name not in cache:
        cache[group_name] = user.groups.filter(name=group_name).exists()
    return cache[group_name]


def can_backstage(user):
    return in_group(user, BACKSTAGE_GROUP)


def can_sandbox(user):
    return in_group(user, SANDBOX_GROUP)
