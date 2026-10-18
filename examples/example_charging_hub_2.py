"""Builds the example hub from the assignment (25 stations, 5 meters) as a sanity check for the ChargingHub/Meter/ChargingStation/Car classes."""

import logging
import os
import sys
from typing import List

from charging_hub_optimization import Car, ChargingHub, ChargingStation, Meter
from charging_hub_optimization.optimizer import optimize


def build_example_hub(logger: logging.Logger) -> ChargingHub:
    hub = ChargingHub(logger)

    # Creating meters
    meter_1: Meter = hub.create_meter("Meter 1", capacity_amps=250)
    meter_2: Meter = hub.create_meter("Meter 2", capacity_amps=150)
    meter_3: Meter = hub.create_meter("Meter 3", capacity_amps=200)
    meter_4: Meter = hub.create_meter("Meter 4", capacity_amps=100)
    meter_5: Meter = hub.create_meter("Meter 5", capacity_amps=150)

    # Connecting meters together
    meter_1.add_child_meter(meter_2)
    meter_1.add_child_meter(meter_3)
    meter_3.add_child_meter(meter_4)
    meter_3.add_child_meter(meter_5)

    # Creating charging stations and connecting to respective meter
    meter_2_stations: List[ChargingStation] = []
    for idx in range(10):
        charging_station = hub.create_charging_station(f"Station_2_{idx}", 6.0, 15.0)
        meter_2.add_charging_station(charging_station)
        meter_2_stations.append(charging_station)

    meter_4_stations: List[ChargingStation] = []
    for idx in range(5):
        charging_station = hub.create_charging_station(f"Station_4_{idx}", 6.0, 15.0)
        meter_4.add_charging_station(charging_station)
        meter_4_stations.append(charging_station)

    meter_5_stations: List[ChargingStation] = []
    for idx in range(10):
        charging_station = hub.create_charging_station(f"Station_5_{idx}", 6.0, 15.0)
        meter_5.add_charging_station(charging_station)
        meter_5_stations.append(charging_station)

    # Creating cars
    cars: List[Car] = []
    cars.append(hub.create_car("car_0", 2))
    cars.append(hub.create_car("car_1", 1))
    cars.append(hub.create_car("car_2", 5))
    cars.append(hub.create_car("car_3", 7))
    cars.append(hub.create_car("car_4", 9))
    cars.append(hub.create_car("car_5", 10))
    cars.append(hub.create_car("car_6", 2))

    # Connecting cars to respective charging station
    meter_2_stations[0].connect_car(cars[0])
    meter_2_stations[4].connect_car(cars[1])
    meter_2_stations[9].connect_car(cars[2])

    meter_4_stations[0].connect_car(cars[3])
    meter_4_stations[4].connect_car(cars[4])

    meter_5_stations[0].connect_car(cars[5])
    meter_5_stations[9].connect_car(cars[6])

    return hub


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("charging_hub_optimization")

    charging_hub = build_example_hub(logger)
    charging_hub.create_graph(os.path.join("tmp", "input_hub_2.dot"))
    if not charging_hub.check_consistency():
        logger.critical(
            "Charging hub is not consistent. Will not proceed with optimization!"
        )
        sys.exit(1)

    car_charging_assignement = optimize(logger, charging_hub)

    logger.info("Will update Charging Hub with current assignement.")
    charging_hub.apply_current(car_charging_assignement)
    logger.info("Charging Hub updated")

    if not charging_hub.check_consistency():
        logger.critical("Charging hub is not consistent after optimization!")

    charging_hub.create_graph(os.path.join("tmp", "optimized_hub_2.dot"))
