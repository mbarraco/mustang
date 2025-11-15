from django.conf import settings


def google_oauth(request):
    """
    Adds a flag so templates can hide Google SSO UI until credentials exist.
    """
    client_id = getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "")
    client_secret = getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "")
    return {
        "google_login_enabled": bool(client_id and client_secret),
    }
