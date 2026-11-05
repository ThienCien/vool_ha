"""DataUpdateCoordinator for Vool integration."""
import logging
import time
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_LMC_DEVICE_ID,
    CONF_SCAN_INTERVAL,
    CONF_WALLBOX_DEVICE_ID,
    DOMAIN,
)
from .vool_api import InvalidAuth, VoolAPI

_LOGGER = logging.getLogger(__name__)

# configuration / health / LMC link change rarely: refresh them at most this often
SLOW_REFRESH_S = 900


class VoolCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Vool data."""

    def __init__(self, hass: HomeAssistant, entry):
        """Initialize."""
        lmc_device_id = entry.data.get(CONF_LMC_DEVICE_ID)
        self.lmc_api = (
            VoolAPI(entry.data["email"], entry.data["password"], lmc_device_id)
            if lmc_device_id
            else None
        )
        self.wallbox_api = VoolAPI(entry.data["email"], entry.data["password"], entry.data[CONF_WALLBOX_DEVICE_ID])
        self._extra = {"wallbox_device": None, "wallbox_config": None, "site_health": None, "lmc_comm": None}
        self._slow_at = 0.0

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=entry.data[CONF_SCAN_INTERVAL]),
        )

    async def _safe(self, coro, what):
        """Run an optional request; a failure keeps the previous value."""
        try:
            return await coro
        except Exception as err:  # noqa: BLE001 - optional data must never break the update
            _LOGGER.debug("VOOL: could not fetch %s: %s", what, err)
            return None

    async def _async_update_data(self):
        """Fetch data from Vool."""
        try:
            wallbox_data = await self.wallbox_api.get_device_status()

            lmc_data = None
            if self.lmc_api is not None:
                lmc_data = await self.lmc_api.get_device_status()
                # Ensure the device ID is included in the data structure
                if lmc_data and 'deviceStatus' in lmc_data:
                    lmc_data['deviceStatus']['deviceId'] = self.lmc_api.device_id

            if wallbox_data and 'deviceStatus' in wallbox_data:
                wallbox_data['deviceStatus']['deviceId'] = self.wallbox_api.device_id
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed from err
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        # charger details (online, connector state, firmware) on every update
        device = await self._safe(self.wallbox_api.get_device(), "device details")
        if device is not None:
            self._extra["wallbox_device"] = device

        # slow-changing data
        if time.monotonic() - self._slow_at >= SLOW_REFRESH_S or self._extra["wallbox_config"] is None:
            self._slow_at = time.monotonic()
            config = await self._safe(self.wallbox_api.get_device_configuration(), "configuration")
            if config is not None:
                self._extra["wallbox_config"] = config
            site_id = (self._extra["wallbox_device"] or {}).get("siteUuid")
            if site_id:
                health = await self._safe(self.wallbox_api.get_site_health(site_id), "site health")
                if health is not None:
                    self._extra["site_health"] = health
            if self.lmc_api is not None:
                comm = await self._safe(self.lmc_api.get_lmc_chargers_communication(), "LMC communication")
                if comm is not None:
                    self._extra["lmc_comm"] = comm

        return {
            "lmc": lmc_data,
            "wallbox": wallbox_data,
            **self._extra,
        }

    async def async_refresh(self):
        """Refresh data from Vool."""
        await self.async_request_refresh()
