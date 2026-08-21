"""Sensor platform for Groupe-E statistics."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CURRENCY, DOMAIN, ENERGY_PRICE_UNIT
from .coordinator import GroupeEDataUpdateCoordinator


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            GroupeETariffSensor(coordinator, "normal_tariff", "Normal Tariff"),
            GroupeETariffSensor(coordinator, "high_tariff", "High Tariff"),
            GroupeETariffSensor(coordinator, "total_energy", "Grid Energy"),
            GroupeECostSensor(coordinator),
            GroupeEPriceSensor(coordinator),
        ]
    )


_SUFFIX_TO_LATEST_KEY = {
    "normal_tariff": "nt",
    "high_tariff": "ht",
    "total_energy": "total",
}


def _device_info(coordinator: GroupeEDataUpdateCoordinator) -> DeviceInfo:
    """Return the shared device for all Groupe-E entities of an entry."""
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
        name=f"Groupe-E {coordinator.label}",
        manufacturer="Groupe-E",
        model="Smart meter",
        entry_type=DeviceEntryType.SERVICE,
    )


class GroupeEBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class wiring common attributes for Groupe-E sensors."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: GroupeEDataUpdateCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_device_info = _device_info(coordinator)


class GroupeETariffSensor(GroupeEBaseSensor):
    """Expose the latest cumulative sum for an energy statistic."""

    def __init__(
        self,
        coordinator: GroupeEDataUpdateCoordinator,
        suffix: str,
        label: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._statistic_id = coordinator.statistic_id_for(suffix)
        self._latest_key = _SUFFIX_TO_LATEST_KEY[suffix]
        self._attr_name = label
        self._attr_unique_id = f"{coordinator.premise}_{suffix}"
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    @property
    def native_value(self) -> float | None:
        """Return the latest cumulative sum from the coordinator."""
        return self.coordinator.latest_sums[self._latest_key]


class GroupeECostSensor(GroupeEBaseSensor):
    """Expose the latest cumulative cost in CHF."""

    def __init__(self, coordinator: GroupeEDataUpdateCoordinator) -> None:
        """Initialize the cost sensor."""
        super().__init__(coordinator)
        self._statistic_id = coordinator.statistic_id_for("cost")
        self._attr_name = "Energy Cost"
        self._attr_unique_id = f"{coordinator.premise}_cost"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_native_unit_of_measurement = CURRENCY

    @property
    def native_value(self) -> float | None:
        """Return the latest cumulative cost from the coordinator."""
        return self.coordinator.latest_sums["cost"]


class GroupeEPriceSensor(GroupeEBaseSensor):
    """Expose the current electricity price based on the active tariff."""

    def __init__(self, coordinator: GroupeEDataUpdateCoordinator) -> None:
        """Initialize the price sensor."""
        super().__init__(coordinator)
        self._attr_name = "Electricity Price"
        self._attr_unique_id = f"{coordinator.premise}_price"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = ENERGY_PRICE_UNIT

    @property
    def native_value(self) -> float:
        """Return the active tariff price."""
        return self.coordinator.current_price

    @property
    def extra_state_attributes(self) -> dict:
        """Expose the active tariff as an attribute."""
        return {
            "tariff": self.coordinator.current_tariff,
            "currency": CURRENCY,
        }
