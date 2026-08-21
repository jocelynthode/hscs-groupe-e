"""Tests for the Groupe-E sensor platform entities."""

from unittest.mock import MagicMock

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfEnergy

from custom_components.groupe_e.const import CURRENCY, ENERGY_PRICE_UNIT
from custom_components.groupe_e.sensor import (
    GroupeECostSensor,
    GroupeEPriceSensor,
    GroupeETariffSensor,
)


@pytest.fixture
def coordinator():
    """A coordinator mock exposing the public sensor-facing API."""
    coord = MagicMock()
    coord.premise = "106180"
    coord.label = "106180"
    coord.config_entry.entry_id = "test-entry-id"
    coord.latest_sums = {"nt": 10.0, "ht": 20.0, "total": 30.0, "cost": 6.5}
    coord.current_price = 0.3
    coord.current_tariff = "high"
    coord.statistic_id_for.side_effect = lambda suffix: (
        f"groupe_e:energy_consumption_106180_{suffix}"
    )
    return coord


def test_tariff_sensor_maps_latest_sums(coordinator):
    """Each tariff sensor reads its own key from latest_sums."""
    nt = GroupeETariffSensor(coordinator, "normal_tariff", "Normal Tariff")
    ht = GroupeETariffSensor(coordinator, "high_tariff", "High Tariff")
    total = GroupeETariffSensor(coordinator, "total_energy", "Grid Energy")

    assert nt.native_value == 10.0
    assert ht.native_value == 20.0
    assert total.native_value == 30.0


def test_energy_sensors_are_energy_dashboard_compatible(coordinator):
    """Energy sensors must be kWh with TOTAL_INCREASING to work in the dashboard."""
    for suffix in ("normal_tariff", "high_tariff", "total_energy"):
        sensor = GroupeETariffSensor(coordinator, suffix, suffix)
        assert sensor.device_class == SensorDeviceClass.ENERGY
        assert sensor.state_class == SensorStateClass.TOTAL_INCREASING
        assert sensor.native_unit_of_measurement == UnitOfEnergy.KILO_WATT_HOUR


def test_unique_ids_are_stable_and_distinct(coordinator):
    """unique_ids are premise-based and must not change between instances."""
    first = GroupeETariffSensor(coordinator, "normal_tariff", "NT")
    second = GroupeETariffSensor(coordinator, "normal_tariff", "NT")
    cost = GroupeECostSensor(coordinator)
    price = GroupeEPriceSensor(coordinator)

    assert first.unique_id == second.unique_id == "106180_normal_tariff"
    ids = {first.unique_id, cost.unique_id, price.unique_id}
    assert len(ids) == 3


def test_cost_sensor(coordinator):
    """Cost sensor is monetary CHF and reads the cost sum."""
    sensor = GroupeECostSensor(coordinator)
    assert sensor.native_value == 6.5
    assert sensor.device_class == SensorDeviceClass.MONETARY
    assert sensor.state_class == SensorStateClass.TOTAL
    assert sensor.native_unit_of_measurement == CURRENCY


def test_price_sensor_exposes_active_tariff(coordinator):
    """Price sensor reports the active tariff price and attributes."""
    sensor = GroupeEPriceSensor(coordinator)
    assert sensor.native_value == 0.3
    assert sensor.state_class == SensorStateClass.MEASUREMENT
    assert sensor.native_unit_of_measurement == ENERGY_PRICE_UNIT
    assert sensor.extra_state_attributes == {
        "tariff": "high",
        "currency": CURRENCY,
    }


def test_all_sensors_share_one_device(coordinator):
    """All entities of an entry belong to the same device."""
    sensors = [
        GroupeETariffSensor(coordinator, "normal_tariff", "NT"),
        GroupeETariffSensor(coordinator, "high_tariff", "HT"),
        GroupeETariffSensor(coordinator, "total_energy", "Total"),
        GroupeECostSensor(coordinator),
        GroupeEPriceSensor(coordinator),
    ]
    identifiers = [s.device_info["identifiers"] for s in sensors]
    assert all(i == {("groupe_e", "test-entry-id")} for i in identifiers)
