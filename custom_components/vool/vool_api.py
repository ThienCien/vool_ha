"""API client for Vool integration."""
import logging
import time

import aiohttp
import jwt

_LOGGER = logging.getLogger(__name__)

API_BASE = "https://api.vool.com/v2"


class VoolAPI:
    """API for interacting with Vool."""

    def __init__(self, email, password, device_id):
        """Initialize the API."""
        self.email = email
        self.password = password
        self.device_id = device_id
        self.token = None
        self.session = None

    async def authenticate(self):
        """Authenticate with the Vool API."""
        token = await self.get_auth_token()
        return token is not None

    async def get_auth_token(self):
        """Get authentication token."""
        url = f"{API_BASE}/auth/login"
        payload = {
            "email": self.email,
            "password": self.password
        }
        headers = {'Content-Type': 'application/json'}

        async with (
            aiohttp.ClientSession() as session,
            session.post(url, headers=headers, json=payload) as response,
        ):
            if response.status == 200:
                data = await response.json()
                self.token = data.get('token')
                return self.token
            else:
                _LOGGER.error("Failed to get auth token. Status: %s", response.status)
                return None

    def is_token_expired(self):
        """Check if the token is expired (with a 60 s margin)."""
        if not self.token:
            return True
        try:
            payload = jwt.decode(self.token, options={"verify_signature": False})
            exp_time = payload.get('exp')
            if exp_time:
                return time.time() > exp_time - 60
            return True
        except jwt.DecodeError:
            return True

    async def _get(self, path, log_errors=True):
        """GET an API path (relative to /v2) and return parsed JSON, or None."""
        if self.is_token_expired():
            await self.get_auth_token()

        if not self.token:
            _LOGGER.error("No valid token available")
            return None

        if not self.session:
            self.session = aiohttp.ClientSession()

        url = f"{API_BASE}/{path}"
        headers = {'Authorization': f'Bearer {self.token}'}
        async with self.session.get(url, headers=headers) as response:
            if response.status == 401:
                # token rejected early: log in again once
                self.token = None
                await self.get_auth_token()
                if not self.token:
                    return None
                headers = {'Authorization': f'Bearer {self.token}'}
                async with self.session.get(url, headers=headers) as retry:
                    if retry.status == 200:
                        return await retry.json()
                    if log_errors:
                        _LOGGER.error("GET %s failed. Status: %s", path, retry.status)
                    return None
            if response.status == 200:
                return await response.json()
            if log_errors:
                _LOGGER.error("GET %s failed. Status: %s", path, response.status)
            return None

    async def get_device_status(self):
        """Get live metrics of the device (voltages, currents, power, energy)."""
        return await self._get(f"devices/{self.device_id}/status")

    async def get_device(self):
        """Get device details (online status, connector state, firmware, site)."""
        data = await self._get(f"devices/{self.device_id}", log_errors=False)
        return data.get("device") if isinstance(data, dict) else None

    async def get_device_configuration(self):
        """Get device configuration as {key: value} (charger_enabled, autostart, ...)."""
        data = await self._get(f"devices/{self.device_id}/configuration?parameters=all", log_errors=False)
        if not isinstance(data, dict):
            return None
        result = {}
        for var in data.get("variables") or []:
            key = var.get("key")
            if not key or any(s in key.lower() for s in ("password", "secret", "token")):
                continue
            result[key] = var.get("value")
        return result

    async def get_site_health(self, site_id):
        """Get the Health status summary (error/warning counts) of a site."""
        data = await self._get(f"sites/{site_id}/health/summary", log_errors=False)
        return data.get("data") if isinstance(data, dict) else None

    async def get_lmc_chargers_communication(self):
        """Get LMC <-> charger communication status (this device must be the LMC)."""
        data = await self._get(f"devices/{self.device_id}/lmc-chargers-communication-status", log_errors=False)
        return data.get("data") if isinstance(data, dict) else None

    async def close(self):
        """Close the aiohttp session."""
        if self.session:
            await self.session.close()
            self.session = None


class InvalidAuth(Exception):
    """Error to indicate there is invalid auth."""
