"""Solve the Charging hub optimization problem.

High level approach:

1/ For priority in {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}
1-1/ Generate a MILP fixing priority and considering cars with priority lower than or equal to the fixed priority.
1-2/ From the optimal solution, retrieve the total current allocated to the fixed priority.
1-3/ Add new constraint to the general model where the current allocated current to cars of that priority must be higher or equal to the value obtained.
"""

import logging
from typing import Dict, List

from ortools.linear_solver import pywraplp

from charging_hub_optimization import Car, ChargingHub, ChargingStation, Meter
from charging_hub_optimization.datamodel import (
    MAX_CAR_PRIORITY,
    MIN_CAR_PRIORITY,
)


def _debug_solved_variables(
    logger: logging.Logger,
    car_charging_current_by_car_variables: Dict[Car, pywraplp.Variable],
    incoming_current_by_meter_variables: Dict[Meter, pywraplp.Variable],
    total_outgoing_current_by_meter_variables: Dict[Meter, pywraplp.Variable],
    charging_station_charging_current_by_charging_station_variables: Dict[
        ChargingStation, pywraplp.Variable
    ],
    car_is_charging_by_car_variables: Dict[Car, pywraplp.Variable],
) -> None:
    """Log the solved value of every variable in the MILP, at debug level.

    Args:
        logger (logging.Logger): logger.
        car_charging_current_by_car_variables (Dict[Car, pywraplp.Variable]): per-car
            charging current variables.
        incoming_current_by_meter_variables (Dict[Meter, pywraplp.Variable]): per-meter
            incoming current variables.
        total_outgoing_current_by_meter_variables (Dict[Meter, pywraplp.Variable]): per-meter
            total outgoing current variables.
        charging_station_charging_current_by_charging_station_variables
            (Dict[ChargingStation, pywraplp.Variable]): per-charging-station current variables.
        car_is_charging_by_car_variables (Dict[Car, pywraplp.Variable]): Whether car is charging.
    """
    logger.debug("Will output all variables value.")

    for car, car_variable in car_charging_current_by_car_variables.items():
        logger.debug(
            "Car %s, charging current %sA", car.name, car_variable.solution_value()
        )

    for (
        car,
        is_charging,
    ) in car_is_charging_by_car_variables.items():
        logger.debug(
            "Car %s, charging: %s",
            car.name,
            is_charging.solution_value(),
        )

    for meter, meter_incoming_variable in incoming_current_by_meter_variables.items():
        logger.debug(
            "Meter %s, incoming current %sA",
            meter.name,
            meter_incoming_variable.solution_value(),
        )

    for (
        meter,
        meter_outgoing_variable,
    ) in total_outgoing_current_by_meter_variables.items():
        logger.debug(
            "Meter %s, outgoing current %sA",
            meter.name,
            meter_outgoing_variable.solution_value(),
        )

    for (
        charging_station,
        station_variable,
    ) in charging_station_charging_current_by_charging_station_variables.items():
        logger.debug(
            "Charging station %s, current %sA",
            charging_station.name,
            station_variable.solution_value(),
        )


def _solve_for_priority(
    logger: logging.Logger,
    all_cars: List[Car],
    root_meter: Meter,
    priority_threshold: int,
    min_total_current_by_priority: Dict[int, float],
) -> Dict[Car, float]:
    """Solve the MILP maximizing total current for cars with priority equal to the priority_threshold.

    Cars with priority strictly greater than the priority_threshold are ignored entirely:
    We are not creating any variables for them.

    https://developers.google.com/optimization/mip/mip_example for example.

    Args:
        logger (logging.Logger): logger.
        all_cars (List[Car]): every car in the hub.
        root_meter (Meter): the root meter
        priority_threshold (int): current priority
        min_total_current_by_priority (Dict[int, float]): for each priority already solved in
            a previous iteration, the minimum total current its cars must still receive here.

    Returns:
        Dict[Car,float]: charging current assignement to Car of at priority or less.

    Raises:
        RuntimeError: if the solver cannot be created or the MILP is not solved to optimality.
    """
    solver = pywraplp.Solver.CreateSolver("CBC_MIXED_INTEGER_PROGRAMMING")
    if solver is None:
        raise RuntimeError("Issue creating solver")

    included_cars = [car for car in all_cars if car.priority <= priority_threshold]

    logger.info("Creating variables")
    # Variables per car:
    # - binary in {0,1}: is_charging_carid: 0=not charging, 1=charging
    # - linear in [0, 15]: car_charging_current_carid
    car_charging_current_by_car_variables: Dict[Car, pywraplp.Variable] = {}
    car_is_charging_by_car_variables: Dict[Car, pywraplp.Variable] = {}
    car_variables_by_car_charging_current: Dict[pywraplp.Variable, Car] = {}
    for car in included_cars:
        is_charging = solver.BoolVar(f"is_charging_{car.name}")
        station_max_current = car.charging_station.max_charging_current_amps
        car_charging_current = solver.NumVar(
            0.0, station_max_current, f"car_charging_current_{car.name}"
        )
        car_charging_current_by_car_variables[car] = car_charging_current
        car_is_charging_by_car_variables[car] = is_charging
        car_variables_by_car_charging_current[car_charging_current] = car

    # Variable per meter:
    # - linear in [0, meter_capacity]: incoming_current_meterid
    # - linear in [0, meter_capacity]: total_outgoing_current_meterid
    incoming_current_by_meter_variables: Dict[Meter, pywraplp.Variable] = {}
    total_outgoing_current_by_meter_variables: Dict[Meter, pywraplp.Variable] = {}
    for meter in root_meter.iter_descendant_meters():
        if not meter.has_at_least_one_descendant_station_occupied(priority_threshold):
            # If there are no occupied charging station below, no need to create variables as no current will flow
            continue

        # Variables
        total_outgoing_current = solver.NumVar(
            0.0, meter.capacity_amps, f"total_outgoing_current_{meter.name}"
        )
        total_outgoing_current_by_meter_variables[meter] = total_outgoing_current

        if not meter.is_root():
            # Since there is no incoming current coming to the root, no need to create variable for it
            incoming_current = solver.NumVar(
                0.0, meter.capacity_amps, f"incoming_current_{meter.name}"
            )
            incoming_current_by_meter_variables[meter] = incoming_current

    # Variable per charging station:
    # - linear in [0, 15]: charging_station_charging_current_stationid
    charging_station_charging_current_by_charging_station_variables: Dict[
        ChargingStation, pywraplp.Variable
    ] = {}
    for charging_station in root_meter.iter_descendant_stations():
        if not charging_station.is_occupied(priority_threshold):
            # No need to create variables/constraint if there are no car connected.
            continue

        charging_station_charging_current = solver.NumVar(
            0.0,
            charging_station.max_charging_current_amps,
            f"charging_station_charging_current_{charging_station.name}",
        )
        charging_station_charging_current_by_charging_station_variables[
            charging_station
        ] = charging_station_charging_current

    logger.info("Variables created")
    logger.info("Creating constraints")

    # Constraint to force the car charging current to be 0 or between 6 and 15:
    # - car_charging_current_carid >= 6 * is_charging_carid
    # - car_charging_current_carid <= 15 * is_charging_carid
    for car in included_cars:
        station_min_current = car.charging_station.min_charging_current_amps
        station_max_current = car.charging_station.max_charging_current_amps
        is_charging = car_is_charging_by_car_variables[car]
        car_charging_current = car_charging_current_by_car_variables[car]
        solver.Add(car_charging_current >= station_min_current * is_charging)
        solver.Add(car_charging_current <= station_max_current * is_charging)

    # Meter's constraint
    for meter in root_meter.iter_descendant_meters():
        if not meter.has_at_least_one_descendant_station_occupied(priority_threshold):
            # If there are no occupied charging station below, no need to create constraint as no current will flow
            continue

        # Linking total outgoing with sum of outgoing
        if len(meter.child_meters) > 0:
            outgoing_meter_terms = [
                incoming_current_by_meter_variables[child]
                for child in meter.child_meters
                if child.has_at_least_one_descendant_station_occupied(
                    priority_threshold
                )
            ]
            solver.Add(
                total_outgoing_current_by_meter_variables[meter]
                == solver.Sum(outgoing_meter_terms)
            )

        # Linking outgoing with charging station
        if len(meter.charging_stations) > 0:
            outgoing_station_terms = [
                charging_station_charging_current_by_charging_station_variables[station]
                for station in meter.charging_stations
                if station.is_occupied(priority_threshold)
            ]
            solver.Add(
                total_outgoing_current_by_meter_variables[meter]
                == solver.Sum(outgoing_station_terms)
            )

        # Linking outgoing with incoming, excepted for root
        if not meter.is_root():
            solver.Add(
                total_outgoing_current_by_meter_variables[meter]
                == incoming_current_by_meter_variables[meter]
            )

    # Constraint to link station current and car charging current
    for charging_station in root_meter.iter_descendant_stations():
        if not charging_station.is_occupied(priority_threshold):
            # No need to create constraint if there are no car connected.
            continue

        charging_station_charging_current = (
            charging_station_charging_current_by_charging_station_variables[
                charging_station
            ]
        )
        car_charging_current = car_charging_current_by_car_variables[
            charging_station.car
        ]
        solver.Add(charging_station_charging_current == car_charging_current)

    logger.info("Constraints created")
    logger.info("Creating specific priority constraint")
    # Constraint to force previously solved priorities.
    # We force the total, not specific allocation as there could exist one that allow higher allocation for next priority.
    for priority, min_total in min_total_current_by_priority.items():
        cars_at_priority = [car for car in included_cars if car.priority <= priority]
        car_current_terms = [
            car_charging_current_by_car_variables[car] for car in cars_at_priority
        ]
        solver.Add(solver.Sum(car_current_terms) >= min_total)

    logger.info("Specific priority constraint done")

    logger.info("Setting objective function")

    # We maximize current for cars at priority and "lower" (meaning "higher priority" in English since 1 is higher
    # priority than 10 in the exercise).
    car_charging_current_at_least_at_priority = [
        car_charging_current_by_car_variables[car]
        for car in included_cars
        if car.priority <= priority_threshold
    ]

    solver.Maximize(solver.Sum(car_charging_current_at_least_at_priority))
    logger.info("Objective function set")

    logger.info(
        "Model info: %s variables, %s constraints",
        solver.NumConstraints(),
        solver.NumVariables(),
    )

    logger.info("About to solve model")
    status = solver.Solve()
    logger.info("Model solved")

    if status != pywraplp.Solver.OPTIMAL:
        raise RuntimeError(
            f"MILP for priority threshold {priority_threshold} did not solve to optimality "
            f"(solver status={status})"
        )

    _debug_solved_variables(
        logger,
        car_charging_current_by_car_variables,
        incoming_current_by_meter_variables,
        total_outgoing_current_by_meter_variables,
        charging_station_charging_current_by_charging_station_variables,
        car_is_charging_by_car_variables,
    )

    # We build the current solution
    car_current_assignement: Dict[Car, float] = {}
    for car_charging_current in car_charging_current_at_least_at_priority:
        car = car_variables_by_car_charging_current[car_charging_current]
        charging_current = car_charging_current.solution_value()
        logger.info("Current for car %s : %sA", car.name, charging_current)

        car_current_assignement[car] = charging_current

    return car_current_assignement


def optimize(logger: logging.Logger, charging_hub: ChargingHub) -> Dict[Car, float]:
    """Optimize charging of charging hub.

    Args:
        logger (logging.Logger): logger
        charging_hub (ChargingHub): Charging hub to optimize

    Returns:
        Dict[Car,float]: optimal current allocation.

    """
    all_cars = charging_hub.get_all_cars()
    root_meter = charging_hub.get_root_meter()

    min_total_current_by_priority: Dict[int, float] = {}
    car_charging_assignement: Dict[Car, float] = {}
    for priority in range(MIN_CAR_PRIORITY, MAX_CAR_PRIORITY + 1):
        car_charging_assignement = _solve_for_priority(
            logger, all_cars, root_meter, priority, min_total_current_by_priority
        )

        total_assignement_for_priority = sum(car_charging_assignement.values())
        min_total_current_by_priority[priority] = total_assignement_for_priority
        logger.info(
            "Temporary charging current assignment: %s", car_charging_assignement
        )
        logger.info(
            "Priority %s: total current allocated = %sA",
            priority,
            total_assignement_for_priority,
        )

    logger.info(
        "Lexicographic optimization done. Totals per priority: %s",
        min_total_current_by_priority,
    )
    logger.info("Final charging current assignment: %s", car_charging_assignement)

    return car_charging_assignement
