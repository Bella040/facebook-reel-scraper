from __future__ import annotations

import base64
import os
from typing import Dict, List, Optional, Union

class ProxyManager:
    """
    Handles common proxy formats and returns a `requests`-compatible proxies mapping.
    Supports:
      - http://user:pass@host:port
      - user:pass@host:port
      - host:port
      - DataImpulse style:
         364a87d67519885f4520__cr.us;state.alabama;city.albertville:c55e092b8405598b@gw.dataimpulse.com:10000
    """

    def __init__(self, proxies: Union[List[str], List[Dict[str, str]]]):
        self.raw = proxies or []

    def _to_url(self, p: Union[str, Dict[str, str]]) -> str:
        if isinstance(p, dict):
            scheme = p.get("scheme", "http")
            auth = ""
            if p.get("username") and p.get("password"):
                auth = f"{p['username']}:{p['password']}@"
            return f"{scheme}://{auth}{p['host']}:{p['port']}"

        s = p.strip()
        if s.startswith("http://") or s.startswith("https://") or s.startswith("socks5://"):
            return s
        # user:pass@host:port
        if "@" in s and ":" in s:
            return f"http://{s}"
        # host:port
        if ":" in s and "@" not in s:
            return f"http://{s}"
        return s

    def get_requests_proxies(self) -> Optional[Dict[str, str]]:
        if not self.raw:
            return None
        # Use the first proxy for simplicity; rotate in a more advanced scenario.
        first = self.raw[0]
        url = self._to_url(first)
        return {
            "http": url,
            "https": url.replace("http://", "http://"),  # keep same proxy for https via CONNECT
        }

    @staticmethod
    def parse_dataimpulse(proxy: str) -> Dict[str, str]:
        """
        Parse DataImpulse formatted credential string into parts.
        Example:
          364a87...__cr.us;state.alabama;city.albertville:c55e09...@gw.dataimpulse.com:10000
        """
        # Split auth and host
        auth_host = proxy.split("@", 1)
        if len(auth_host) != 2:
            raise ValueError("Invalid DataImpulse proxy: missing '@'")
        auth, hostport = auth_host
        if ":" not in hostport:
            raise ValueError("Invalid DataImpulse proxy: missing ':port'")
        host, port = hostport.split(":", 1)
        if ":" not in auth:
            raise ValueError("Invalid DataImpulse proxy: missing password separator ':'")
        username, password = auth.split(":", 1)
        return {
            "host": host,
            "port": port,
            "username": username,
            "password": password,
        }

    @staticmethod
    def as_proxy_dict(host: str, port: str, username: Optional[str] = None, password: Optional[str] = None, scheme: str = "http") -> Dict[str, str]:
        d: Dict[str, str] = {"scheme": scheme, "host": host, "port": port}
        if username:
            d["username"] = username
        if password:
            d["password"] = password
        return d

    @staticmethod
    def basic_auth_header(username: str, password: str) -> str:
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        return f"Basic {token}"