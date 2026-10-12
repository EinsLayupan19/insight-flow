"""Refuse state-changing requests that another website makes a browser send (cross-site request forgery).

The owner signs in at the reverse proxy (HTTP Basic auth). Browsers attach those credentials to every request to
the site, including a form another website submits, so the sign-in alone does not stop such requests.

Policy for every method except GET, HEAD, and OPTIONS (they change nothing; reading an answer cross-site is
already blocked by the browser):
1. Sec-Fetch-Site, when present, must be "same-origin" or "none" (started by the user, such as a bookmark).
   "cross-site", "same-site" (another subdomain, for example someone else's *.duckdns.org site), and unknown
   values are refused. Pages cannot set this header; browsers do.
2. Origin, when present, must be this site's own origin: the request's scheme (https behind nginx, taken from
   X-Forwarded-Proto, which Uvicorn trusts only from 127.0.0.1) and its Host header, which TrustedHostMiddleware
   has already checked against ALLOWED_HOSTS. So the allowed origin follows the configuration, with no host name
   written here. "null" and malformed values are refused.
3. Neither header: allowed. Current browsers send at least one of them with any request another site can make
   them send, so such a request comes from a non-browser client (curl, a script, the server's own checks), which
   has no stored credentials to misuse. The checks the server runs on itself are GET requests anyway.
A refused request gets 403 before its body is read.

nginx applies the same rules first, with the public origin written into its configuration
(deploy/nginx/insightflow-https.conf). This check stays authoritative, so the policy holds if the proxy changes.
"""

from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
ALLOWED_FETCH_SITES = frozenset({"same-origin", "none"})
DEFAULT_PORTS = {"http": 80, "https": 443}
REFUSED_MESSAGE = "This request came from another website, so InsightFlow refused it. Open InsightFlow directly and try again."

Origin = tuple[str, str, int]  # scheme, lower-case host, port


class CrossSiteRequestGuard:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] not in SAFE_METHODS and _from_another_site(scope):
            response = JSONResponse({"detail": REFUSED_MESSAGE}, status_code=403)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _from_another_site(scope: Scope) -> bool:
    headers = Headers(scope=scope)
    fetch_site = headers.get("sec-fetch-site")
    if fetch_site is not None and fetch_site.strip().lower() not in ALLOWED_FETCH_SITES:
        return True
    origin = headers.get("origin")
    if origin is None:
        return False
    own = _origin(scope["scheme"], f"//{headers.get('host', '')}")
    return own is None or _origin_header(origin) != own


def _origin_header(value: str) -> Origin | None:
    """The origin a browser sent: exactly scheme://host[:port], nothing else."""
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return None
    if parts.path or parts.query or parts.fragment or parts.username is not None or parts.password is not None:
        return None
    return _origin(parts.scheme, value.strip()[len(parts.scheme) + 1 :] if parts.scheme else "")


def _origin(scheme: str, netloc_url: str) -> Origin | None:
    """Scheme, host, and port of `//host[:port]`, or None if it is not a valid web origin."""
    scheme = scheme.lower()
    if scheme not in DEFAULT_PORTS or not netloc_url.startswith("//"):
        return None
    try:
        parts = urlsplit(netloc_url)
        host, port = parts.hostname, parts.port
    except ValueError:  # an invalid port or address
        return None
    if not host:
        return None
    return scheme, host, port if port is not None else DEFAULT_PORTS[scheme]
