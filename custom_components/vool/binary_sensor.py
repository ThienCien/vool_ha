"""Binary sensor platform for Vool integration (local patch: charger health)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VoolCoordinator
from .sensor import wallbox_device_info


def _cfg_bool(key: str) -> Callable[[dict[str, Any]], bool | None]:
    def fn(data: dict[str, Any]) -> bool | None:
        value = (data.get("wallbox_config") or {}).get(key)
        return bool(value) if value is not None else None
    return fn


def _online(data: dict[str, Any]) -> bool | None:
    status = (data.get("wallbox_device") or {}).get("status")
    return status == "online" if status else None


def _lmc_link(data: dict[str, Any]) -> bool | None:
    serial = ((data.get("wallbox_device") or {}).get("serialNumber") or "").upper()
    for item in data.get("lmc_comm") or []:
        if not serial or (item.get("deviceSerialNumber") or "").upper() == serial:
            ok = item.get("isCommunicationOk")
            return bool(ok) if ok is not None else None
    return None


def _lmc_attrs(data: dict[str, Any]) -> dict[str, Any] | None:
    serial = ((data.get("wallbox_device") or {}).get("serialNumber") or "").upper()
    for item in data.get("lmc_comm") or []:
        if not serial or (item.get("deviceSerialNumber") or "").upper() == serial:
            return {"interface": item.get("interface")}
    return None


@dataclass(frozen=True, kw_only=True)
class VoolBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes a VOOL binary sensor."""

    value_fn: Callable[[dict[str, Any]], bool | None]
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None
    source: str = "wallbox_device"
    needs_lmc: bool = False


BINARY_SENSOR_DESCRIPTIONS: tuple[VoolBinarySensorEntityDescription, ...] = (
    VoolBinarySensorEntityDescription(
        key="online",
        name="Online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=_online,
        attrs_fn=lambda data: {
            "last_connection_event": (data.get("wallbox_device") or {}).get("lastConnectionEventTime"),
        },
    ),
    VoolBinarySensorEntityDescription(
        key="charger_enabled",
        name="Charger Enabled",
        icon="mdi:ev-station",
        value_fn=_cfg_bool("charger_enabled"),
        source="wallbox_config",
    ),
    VoolBinarySensorEntityDescription(
        key="auto_start",
        name="Auto Start",
        icon="mdi:play-circle-outline",
        value_fn=_cfg_bool("automatically_start_charging"),
        attrs_fn=lambda data: {
            "enabled_control_channels": (data.get("wallbox_config") or {}).get("enabled_control_channels"),
        },
        source="wallbox_config",
    ),
    VoolBinarySensorEntityDescription(
        key="lmc_communication",
        name="LMC Communication",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=_lmc_link,
        attrs_fn=_lmc_attrs,
        source="lmc_comm",
        needs_lmc=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Vool binary sensors."""
    coordinator: VoolCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        VoolBinarySensor(coordinator, description)
        for description in BINARY_SENSOR_DESCRIPTIONS
        if not description.needs_lmc or coordinator.lmc_api is not None
    )


class VoolBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """VOOL charger binary sensor."""

    entity_description: VoolBinarySensorEntityDescription

    def __init__(self, coordinator: VoolCoordinator, description: VoolBinarySensorEntityDescription) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.wallbox_api.device_id}_{description.key}"
        self._attr_name = f"VOOL WALLBOX {description.name}"

    @property
    def is_on(self) -> bool | None:
        """Return the state."""
        if not self.coordinator.data:
            return None
        try:
            return self.entity_description.value_fn(self.coordinator.data)
        except (KeyError, TypeError, IndexError, AttributeError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        if not self.coordinator.data or not self.entity_description.attrs_fn:
            return None
        try:
            return self.entity_description.attrs_fn(self.coordinator.data)
        except (KeyError, TypeError, IndexError, AttributeError):
            return None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return wallbox_device_info(self.coordinator)

    @property
    def available(self) -> bool:
        """Available while the coordinator works and this data source has been fetched."""
        return (
            self.coordinator.last_update_success
            and bool(self.coordinator.data)
            and self.coordinator.data.get(self.entity_description.source) is not None
        )
