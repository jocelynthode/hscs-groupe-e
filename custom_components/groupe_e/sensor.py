"""Sensor platform for Groupe-E statistics."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CURRENCY, DOMAIN, ENERGY_PRICE_UNIT


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


_SUFFIX_TO_LATEST = {
    "normal_tariff": "_latest_nt_sum",
    "high_tariff": "_latest_ht_sum",
    "total_energy": "_latest_total_sum",
}


class GroupeETariffSensor(CoordinatorEntity, SensorEntity):
    """Expose the latest cumulative sum for an energy statistic."""

    def __init__(self, coordinator, suffix, label):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._statistic_id = getattr(coordinator, f"_{suffix}_qh_id")
        self._latest_attr = _SUFFIX_TO_LATEST[suffix]
        self._attr_name = f"Groupe-E {label} {coordinator._label}"
        self._attr_unique_id = f"{coordinator.premise}_{suffix}"
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_available = True

    @property
    def available(self):
        return True

    @property
    def native_value(self):
        """Return the latest sum from coordinator in-memory data."""
        return getattr(self.coordinator, self._latest_attr, None)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update sensor when coordinator refreshes."""
        self.async_write_ha_state()

    async def async_update(self):
        """Fetch the latest sum from the coordinator."""
        self.async_write_ha_state()


class GroupeECostSensor(CoordinatorEntity, SensorEntity):
    """Expose the latest cumulative cost in CHF."""

    def __init__(self, coordinator):
        """Initialize the cost sensor."""
        super().__init__(coordinator)
        self._statistic_id = coordinator._cost_qh_id
        self._attr_name = f"Groupe-E Energy Cost {coordinator._label}"
        self._attr_unique_id = f"{coordinator.premise}_cost"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_native_unit_of_measurement = CURRENCY
        self._attr_available = True

    @property
    def available(self):
        return True

    @property
    def native_value(self):
        """Return the latest cost from coordinator in-memory data."""
        return self.coordinator._latest_cost_sum

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update sensor when coordinator refreshes."""
        self.async_write_ha_state()

    async def async_update(self):
        """Fetch the latest cost from the coordinator."""
        self.async_write_ha_state()


class GroupeEPriceSensor(CoordinatorEntity, SensorEntity):
    """Expose the current electricity price based on the active tariff."""

    def __init__(self, coordinator):
        """Initialize the price sensor."""
        super().__init__(coordinator)
        self._attr_name = f"Groupe-E Electricity Price {coordinator._label}"
        self._attr_unique_id = f"{coordinator.premise}_price"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = ENERGY_PRICE_UNIT
        self._attr_available = True

    @property
    def available(self):
        return True

    @property
    def native_value(self):
        return self.coordinator.current_price

    @property
    def extra_state_attributes(self):
        return {
            "tariff": self.coordinator.current_tariff,
            "currency": CURRENCY,
        }
