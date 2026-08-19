"""Sensor platform for Groupe-E."""
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            GroupeEEnergySensor(coordinator),
            GroupeEDailyEnergySensor(coordinator),
            GroupeEYesterdayEnergySensor(coordinator),
            GroupeEMonthlyEnergySensor(coordinator),
        ]
    )

class GroupeEEnergySensor(CoordinatorEntity, SensorEntity):
    """Groupe-E Energy Sensor."""

    def __init__(self, coordinator):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = "Groupe-E Energy Consumption"
        self._attr_unique_id = f"{coordinator.premise}_energy"
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.coordinator.data.get("total_consumption")

class GroupeEDailyEnergySensor(CoordinatorEntity, SensorEntity):
    """Groupe-E Daily Energy Sensor."""

    def __init__(self, coordinator):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = "Groupe-E Daily Energy Consumption"
        self._attr_unique_id = f"{coordinator.premise}_daily_energy"
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.coordinator.data.get("daily_consumption")

class GroupeEYesterdayEnergySensor(CoordinatorEntity, SensorEntity):
    """Groupe-E Yesterday Energy Sensor."""

    def __init__(self, coordinator):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = "Groupe-E Yesterday Energy Consumption"
        self._attr_unique_id = f"{coordinator.premise}_yesterday_energy"
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.coordinator.data.get("yesterday_consumption")

class GroupeEMonthlyEnergySensor(CoordinatorEntity, SensorEntity):
    """Groupe-E Monthly Energy Sensor."""

    def __init__(self, coordinator):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = "Groupe-E Monthly Energy Consumption"
        self._attr_unique_id = f"{coordinator.premise}_monthly_energy"
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.coordinator.data.get("monthly_consumption")
