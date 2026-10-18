"""Builds the example hub from the assignment (25 stations, 5 meters) as a sanity check for the ChargingHub/Meter/ChargingStation/Car classes. No real optimization here yet."""

import logging
import os
import sys
from typing import List

from charging_hub_optimization import Car, ChargingHub, ChargingStation, Meter


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


def optimize(logger: logging.Logger, charging_hub: ChargingHub) -> None:
    """Optimize charging of charging hub.

    Dummy implementation for testing purposes.

    Args:
        logger (logging.Logger): logger
        charging_hub (ChargingHub): Charging hub to optimize
    """
    logger.info("Dummy optimization starting")
    # This is not an optimization, it's just to set some values for representation
    for car in charging_hub.get_all_cars():
        car.set_current(6.0)

    logger.info("Dummy optimization done")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("charging_hub_optimization")

    charging_hub = build_example_hub(logger)
    charging_hub.create_graph(os.path.join("tmp", "input_hub.dot"))

    if not charging_hub.check_consistency():
        logger.critical(
            "Charging hub is not consistent. Will not proceed with optimization!"
        )
        sys.exit(1)

    optimize(logger, charging_hub)

    if not charging_hub.check_consistency():
        logger.critical("Charging hub is not consistent after optimization!")

    charging_hub.create_graph(os.path.join("tmp", "optimized_hub.dot"))
