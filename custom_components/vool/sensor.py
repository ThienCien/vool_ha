"""Sensor platform for Vool integration."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VoolCoordinator


@dataclass(frozen=True, kw_only=True)
class VoolSensorEntityDescription(SensorEntityDescription):
    """Describes a VOOL sensor entity."""

    value_fn: Callable[[dict[str, Any]], Any] | None = None
    convert_kw: bool = False


# Sensor definitions matching the reference integration's power units
SENSOR_DESCRIPTIONS: tuple[VoolSensorEntityDescription, ...] = (
    VoolSensorEntityDescription(
        key="active_power",
        translation_key="active_power",
        name="Active Power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("active_power"),
        convert_kw=False,  # Already in kW from API
    ),
    VoolSensorEntityDescription(
        key="current_l1",
        translation_key="current_l1",
        name="Current L1",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("current_l1"),
    ),
    VoolSensorEntityDescription(
        key="current_l2",
        translation_key="current_l2",
        name="Current L2",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("current_l2"),
    ),
    VoolSensorEntityDescription(
        key="current_l3",
        translation_key="current_l3",
        name="Current L3",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("current_l3"),
    ),
    VoolSensorEntityDescription(
        key="voltage_l1",
        translation_key="voltage_l1",
        name="Voltage L1",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("voltage_l1"),
    ),
    VoolSensorEntityDescription(
        key="voltage_l2",
        translation_key="voltage_l2",
        name="Voltage L2",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("voltage_l2"),
    ),
    VoolSensorEntityDescription(
        key="voltage_l3",
        translation_key="voltage_l3",
        name="Voltage L3",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("voltage_l3"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Vool sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    device_types = ['wallbox']
    # Only add LMC sensors if an LMC device is configured
    if coordinator.lmc_api is not None:
        device_types.append('lmc')

    entities = []
    for device_type in device_types:
        for description in SENSOR_DESCRIPTIONS:
            entities.append(VoolSensor(coordinator, device_type, description))

    # extra charger sensors (connector state, configuration, health)
    for description in EXTRA_SENSOR_DESCRIPTIONS:
        entities.append(VoolExtraSensor(coordinator, description))

    async_add_entities(entities)


class VoolSensor(CoordinatorEntity, SensorEntity):
    """Representation of a VOOL Sensor."""

    entity_description: VoolSensorEntityDescription

    def __init__(
        self,
        coordinator: VoolCoordinator,
        device_type: str,
        description: VoolSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._device_type = device_type
        self.entity_description = description
        
        # Safely get the device ID, falling back to the one from config if not found in data
        device_id = self._get_device_id(coordinator, device_type)
        self._attr_unique_id = f"{device_id}_{description.key}"
        self._attr_name = f"VOOL {device_type.upper()} {description.name}"

    def _get_device_id(self, coordinator: VoolCoordinator, device_type: str) -> str:
        """Safely get the device ID."""
        try:
            return coordinator.data[device_type]['deviceStatus']['deviceId']
        except (KeyError, TypeError):
            # Fallback to the device ID from the config entry
            return getattr(coordinator, f"{device_type}_api").device_id

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        if self.coordinator.data:
            try:
                connectors = self.coordinator.data[self._device_type]['deviceStatus']['connectors']
                if connectors and self.entity_description.value_fn:
                    connector = connectors[0]
                    # VOOL does not report a live active_power reading for LMC devices (always a
                    # fixed placeholder value), so approximate it from the per-phase V*I instead.
                    if self.entity_description.key == 'active_power' and self._device_type == 'lmc':
                        total_w = sum(
                            connector.get(f'voltage_l{p}', 0) * connector.get(f'current_l{p}', 0)
                            for p in (1, 2, 3)
                        )
                        return round(total_w / 1000, 3)
                    value = self.entity_description.value_fn(connector)
                    return value
            except (KeyError, TypeError, IndexError):
                pass
        return None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information about this VOOL device."""
        device_id = self._get_device_id(self.coordinator, self._device_type)
        return DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=f"VOOL {self._device_type.upper()}",
            manufacturer="VOOL",
            model="Charger" if self._device_type == "wallbox" else "LMC",
            sw_version=self.coordinator.data[self._device_type].get("firmwareVersion") if self.coordinator.data else None,
        )

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success

# ---------------------------------------------------------------------------
# Extra charger data (local patch): connector state, configuration, health.
# value_fn receives the whole coordinator.data dict.
# ---------------------------------------------------------------------------

def _connector_state(data: dict[str, Any]) -> dict[str, Any] | None:
    device = data.get("wallbox_device") or {}
    states = device.get("stateOfConnectors") or []
    return states[0] if states else None


def _cfg(key: str) -> Callable[[dict[str, Any]], Any]:
    return lambda data: (data.get("wallbox_config") or {}).get(key)


def _energy_kwh(data: dict[str, Any]) -> float | None:
    try:
        wh = data["wallbox"]["deviceStatus"]["connectors"][0]["energy_imported"]
    except (KeyError, TypeError, IndexError):
        return None
    return round(wh / 1000, 3) if isinstance(wh, (int, float)) else None


def _health(key: str) -> Callable[[dict[str, Any]], Any]:
    return lambda data: (data.get("site_health") or {}).get(key)


@dataclass(frozen=True, kw_only=True)
class VoolExtraSensorEntityDescription(SensorEntityDescription):
    """Describes an extra VOOL charger sensor."""

    value_fn: Callable[[dict[str, Any]], Any]
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None
    source: str = "wallbox_device"


EXTRA_SENSOR_DESCRIPTIONS: tuple[VoolExtraSensorEntityDescription, ...] = (
    VoolExtraSensorEntityDescription(
        key="connector_status",
        name="Connector Status",
        icon="mdi:ev-plug-type2",
        value_fn=lambda data: (_connector_state(data) or {}).get("computedStatus"),
        attrs_fn=lambda data: {
            k: (_connector_state(data) or {}).get(k)
            for k in ("ocppStatus", "errorCode", "vendorErrorCode", "vendorErrorMessage", "transactionStatus")
        },
    ),
    VoolExtraSensorEntityDescription(
        key="energy_total",
        name="Energy Total",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=_energy_kwh,
        source="wallbox",
    ),
    VoolExtraSensorEntityDescription(
        key="max_charging_current",
        name="Max Charging Current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        value_fn=_cfg("maximum_charging_current"),
        source="wallbox_config",
    ),
    VoolExtraSensorEntityDescription(
        key="gsm_signal",
        name="GSM Signal",
        icon="mdi:signal",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_cfg("gsm_signal_strength"),
        source="wallbox_config",
    ),
    VoolExtraSensorEntityDescription(
        key="highest_alarm_code",
        name="Highest Alarm Code",
        icon="mdi:alert-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_cfg("highest_alarm_code"),
        source="wallbox_config",
    ),
    VoolExtraSensorEntityDescription(
        key="health_errors",
        name="Health Errors",
        icon="mdi:alert-octagon-outline",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_health("errorCount"),
        source="site_health",
    ),
    VoolExtraSensorEntityDescription(
        key="health_warnings",
        name="Health Warnings",
        icon="mdi:alert-outline",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_health("warningCount"),
        source="site_health",
    ),
)


def wallbox_device_info(coordinator: VoolCoordinator) -> DeviceInfo:
    """Device info shared by the extra charger entities (same device as the base sensors)."""
    device = (coordinator.data or {}).get("wallbox_device") or {}
    fw = device.get("firmwareComponentVersions") or {}
    sw = device.get("firmwareVersion")
    if sw and fw:
        sw = f"{sw} (MCU {fw.get('mcu') or '-'}, GW {fw.get('gateway') or '-'}, FP {fw.get('frontPanel') or '-'})"
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.wallbox_api.device_id)},
        name="VOOL WALLBOX",
        manufacturer="VOOL",
        model=device.get("model") or "Charger",
        serial_number=device.get("serialNumber"),
        sw_version=sw,
    )


class VoolExtraSensor(CoordinatorEntity, SensorEntity):
    """Extra VOOL charger sensor."""

    entity_description: VoolExtraSensorEntityDescription

    def __init__(self, coordinator: VoolCoordinator, description: VoolExtraSensorEntityDescription) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.wallbox_api.device_id}_{description.key}"
        self._attr_name = f"VOOL WALLBOX {description.name}"

    @property
    def native_value(self) -> Any:
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
