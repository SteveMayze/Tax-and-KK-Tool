"""Test runner that makes any real network connection fail, so all HTTP must be mocked."""
import ipaddress
import socket

from django.test.runner import DiscoverRunner


class NetworkBlocked(AssertionError):
    pass


def _is_local(address):
    if not isinstance(address, tuple):
        return True  # AF_UNIX etc.
    try:
        return ipaddress.ip_address(address[0]).is_loopback
    except ValueError:
        return address[0] == 'localhost'


class NoNetworkRunner(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self._real_connect = socket.socket.connect

        real = self._real_connect

        def guarded(sock, address):
            if not _is_local(address):
                raise NetworkBlocked(f'Real network access attempted in tests: {address!r}')
            return real(sock, address)

        socket.socket.connect = guarded

    def teardown_test_environment(self, **kwargs):
        socket.socket.connect = self._real_connect
        super().teardown_test_environment(**kwargs)
