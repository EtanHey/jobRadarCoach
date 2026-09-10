"""Pinned HTTPS transport for allowlisted public job hosts."""

import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urlparse


class _Response:
    def __init__(self, response, url):
        self._response, self.status, self.headers, self._url = (
            response,
            response.status,
            response.headers,
            url,
        )

    def read(self, size=-1):
        return self._response.read(size)

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._response.close()


def pinned_open(
    request,
    *,
    timeout=10,
    resolver=socket.getaddrinfo,
    connector=socket.create_connection,
    context=None,
):
    parsed = urlparse(request.full_url)
    host = parsed.hostname or ""
    addresses = {item[4][0] for item in resolver(host, 443, type=socket.SOCK_STREAM)}
    if not addresses or any(
        not ipaddress.ip_address(address).is_global for address in addresses
    ):
        raise OSError("job host did not resolve exclusively to public addresses")
    raw = connector((sorted(addresses)[0], 443), timeout)
    tls = (context or ssl.create_default_context()).wrap_socket(
        raw, server_hostname=host
    )
    connection = http.client.HTTPSConnection(host, timeout=timeout)
    connection.sock = tls
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    headers = dict(request.header_items())
    headers["Host"] = host
    connection.request(request.get_method(), path, headers=headers)
    return _Response(connection.getresponse(), request.full_url)
