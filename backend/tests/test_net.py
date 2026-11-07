import unittest
from unittest import mock
import urllib.request

import socks
from sockshandler import SocksiPyHandler

from shutong.net import Proxy, make_opener, parse_proxy


class ParseProxyTests(unittest.TestCase):
    def test_accepts_http_and_socks(self):
        cases = {
            "http://192.168.1.2:7890": Proxy("http", "192.168.1.2", 7890),
            "https://proxy.lan:443": Proxy("https", "proxy.lan", 443),
            "socks5://192.168.1.2:7891": Proxy("socks5", "192.168.1.2", 7891),
            "socks5h://192.168.1.2:7891": Proxy("socks5h", "192.168.1.2", 7891),
            " http://me:p%40ss@192.168.1.2:7890 ": Proxy("http", "192.168.1.2", 7890, "me", "p@ss"),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_proxy(text), expected)

    def test_empty_means_no_proxy(self):
        self.assertIsNone(parse_proxy(""))
        self.assertIsNone(parse_proxy("   "))

    def test_rejects_bad_addresses(self):
        for text in ("192.168.1.2:7890", "ftp://192.168.1.2:21", "http://192.168.1.2", "socks5://:7891",
                     "http://192.168.1.2:99999"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError) as caught:
                    parse_proxy(text)
                self.assertIn("代理地址格式不对", str(caught.exception))
                self.assertIn("socks5://", str(caught.exception))


class MakeOpenerTests(unittest.TestCase):
    def test_no_proxy_is_plain_urlopen(self):
        self.assertIs(make_opener(None), urllib.request.urlopen)

    def test_http_proxy_uses_proxy_handler(self):
        with mock.patch("shutong.net.build_opener") as build:
            opener = make_opener(parse_proxy("http://me:pw@192.168.1.2:7890"))
        [handler] = build.call_args.args
        self.assertIsInstance(handler, urllib.request.ProxyHandler)
        self.assertEqual(handler.proxies, {"http": "http://me:pw@192.168.1.2:7890",
                                           "https": "http://me:pw@192.168.1.2:7890"})
        self.assertIs(opener, build.return_value.open)

    def test_socks_resolves_names_on_the_proxy(self):
        # Local DNS is often poisoned for the very hosts the proxy is for, so both spellings resolve remotely.
        for text in ("socks5h://192.168.1.2:7891", "socks5://me:pw@192.168.1.2:7891"):
            with self.subTest(text=text), mock.patch("shutong.net.build_opener") as build:
                make_opener(parse_proxy(text))
                handler = build.call_args.args[-1]
                self.assertIsInstance(handler, SocksiPyHandler)
                self.assertEqual(handler.args, (socks.SOCKS5, "192.168.1.2", 7891))
                self.assertTrue(handler.kw["rdns"])
        self.assertEqual((handler.kw["username"], handler.kw["password"]), ("me", "pw"))

    def test_socks_ignores_environment_proxies(self):
        with mock.patch.dict("os.environ", {"HTTPS_PROXY": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9"}), \
                mock.patch("shutong.net.build_opener") as build:
            make_opener(parse_proxy("socks5://192.168.1.2:7891"))
        first, second = build.call_args.args
        self.assertIsInstance(first, urllib.request.ProxyHandler)
        self.assertEqual(first.proxies, {})
        self.assertIsInstance(second, SocksiPyHandler)


if __name__ == "__main__":
    unittest.main()
