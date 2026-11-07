"""Outbound HTTP through the configured proxy (HTTP or SOCKS5), for internet services only."""
from dataclasses import dataclass
from typing import Any, Callable, Optional
from urllib.parse import quote, unquote, urlsplit
from urllib.request import ProxyHandler, build_opener, urlopen

import socks
from sockshandler import SocksiPyHandler

_SCHEMES = ("http", "https", "socks5", "socks5h")
_EXAMPLE = "例如 http://192.168.1.2:7890 或 socks5://192.168.1.2:7891"


@dataclass(frozen=True)
class Proxy:
    scheme: str
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None

    @property
    def url(self) -> str:
        auth = ""
        if self.username is not None:
            auth = quote(self.username, safe="")
            if self.password is not None:
                auth += ":" + quote(self.password, safe="")
            auth += "@"
        return "{0}://{1}{2}:{3}".format(self.scheme, auth, self.host, self.port)


def parse_proxy(text: str) -> Optional[Proxy]:
    """``""`` means no proxy; anything else must be ``scheme://[user:pass@]host:port``."""
    text = (text or "").strip()
    if not text:
        return None
    error = ValueError("代理地址格式不对：{0}，{1}".format(text, _EXAMPLE))
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        raise error from None
    if parts.scheme.lower() not in _SCHEMES or not parts.hostname or port is None:
        raise error
    username = unquote(parts.username) if parts.username is not None else None
    password = unquote(parts.password) if parts.password is not None else None
    return Proxy(parts.scheme.lower(), parts.hostname, port, username, password)


def make_opener(proxy: Optional[Proxy]) -> Callable[..., Any]:
    """Something called like ``urlopen(request, timeout=...)``; a fresh one per settings read."""
    if proxy is None:
        return urlopen
    if proxy.scheme.startswith("socks5"):
        # Both spellings resolve names on the proxy: local DNS is often what the proxy is there to avoid.
        handler = SocksiPyHandler(socks.SOCKS5, proxy.host, proxy.port, rdns=True,
                                  username=proxy.username, password=proxy.password)
        # build_opener adds a default ProxyHandler that reads HTTPS_PROXY / the system proxy and would
        # send the request there first; an empty one keeps the SOCKS tunnel in charge.
        return build_opener(ProxyHandler({}), handler).open
    return build_opener(ProxyHandler({"http": proxy.url, "https": proxy.url})).open
