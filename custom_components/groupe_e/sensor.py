"""Sensor platform for Groupe-E statistics."""

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import get_last_statistics
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


class GroupeETariffSensor(CoordinatorEntity, SensorEntity):
    """Expose the latest cumulative sum for an energy statistic."""

    def __init__(self, coordinator, suffix, label):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._statistic_id = getattr(coordinator, f"_{suffix}_qh_id")
        self._attr_name = f"Groupe-E {label} {coordinator._label}"
        self._attr_unique_id = f"{coordinator.premise}_{suffix}"
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_available = True

    async def _fetch_and_update(self) -> None:
        """Fetch the latest sum from the recorder and update state."""
        instance = get_instance(self.hass)
        stats = await instance.async_add_executor_job(
            get_last_statistics, self.hass, 1, self._statistic_id, True, {"sum"}
        )
        if stats and self._statistic_id in stats:
            self._attr_native_value = stats[self._statistic_id][0].get("sum")
        else:
            self._attr_native_value = None
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update sensor when coordinator refreshes."""
        self.hass.async_create_task(self._fetch_and_update())

    async def async_update(self):
        """Fetch the latest sum from the recorder."""
        instance = get_instance(self.hass)
        stats = await instance.async_add_executor_job(
            get_last_statistics, self.hass, 1, self._statistic_id, True, {"sum"}
        )
        if stats and self._statistic_id in stats:
            self._attr_native_value = stats[self._statistic_id][0].get("sum")
        else:
            self._attr_native_value = None


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

    async def _fetch_and_update(self) -> None:
        """Fetch the latest sum from the recorder and update state."""
        instance = get_instance(self.hass)
        stats = await instance.async_add_executor_job(
            get_last_statistics, self.hass, 1, self._statistic_id, True, {"sum"}
        )
        if stats and self._statistic_id in stats:
            self._attr_native_value = stats[self._statistic_id][0].get("sum")
        else:
            self._attr_native_value = None
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update sensor when coordinator refreshes."""
        self.hass.async_create_task(self._fetch_and_update())

    async def async_update(self):
        """Fetch the latest sum from the recorder."""
        instance = get_instance(self.hass)
        stats = await instance.async_add_executor_job(
            get_last_statistics, self.hass, 1, self._statistic_id, True, {"sum"}
        )
        if stats and self._statistic_id in stats:
            self._attr_native_value = stats[self._statistic_id][0].get("sum")
        else:
            self._attr_native_value = None


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
    def native_value(self):
        return self.coordinator.current_price

    @property
    def extra_state_attributes(self):
        return {
            "tariff": self.coordinator.current_tariff,
            "currency": CURRENCY,
        }
