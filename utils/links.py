from urllib.parse import urlparse

HOSTS_GOOGLE_DRIVE = {"drive.google.com", "docs.google.com"}


def link_do_google_drive(url: str) -> bool:
    url = (url or "").strip()
    if any(c in url for c in "<>| \n"):
        return False
    try:
        partes = urlparse(url)
    except ValueError:
        return False
    return partes.scheme == "https" and (partes.hostname or "").lower() in HOSTS_GOOGLE_DRIVE
