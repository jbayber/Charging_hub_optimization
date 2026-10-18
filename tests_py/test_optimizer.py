"""Unit tests for optimizer.optimize().

Each test builds a hub, runs optimize(), and asserts the resulting current
assignment against a hand-computed expected value per car.
"""

import itertools
import logging
import unittest
from typing import Dict, List, Set

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


def _quiet_logger(name: str) -> logging.Logger:
    """Build a logger that swallows output, so tests don't flood stdout.

    Args:
        name (str): logger name.

    Returns:
        logging.Logger: a logger with a NullHandler and CRITICAL level.
    """
    logger = logging.getLogger(name)
    # logger.handlers = [logging.NullHandler()]
    logger.setLevel(logging.DEBUG)
    # logger.propagate = False
    return logger


def _min_required(meter: Meter, active_stations: Set[ChargingStation]) -> float:
    """Minimum current needed to give every active station under meter at least
    MIN_CHARGING_CURRENT_AMPS, ignoring capacity (used for a feasibility check).

    Args:
        meter (Meter): meter to start from.
        active_stations (Set[ChargingStation]): stations assumed to be charging.

    Returns:
        float: minimum current (A) required under meter.
    """
    total = sum(
        station.min_charging_current_amps
        for station in meter.charging_stations
        if station in active_stations
    )
    total += sum(_min_required(child, active_stations) for child in meter.child_meters)
    return total


def _max_deliverable(meter: Meter, active_stations: Set[ChargingStation]) -> float:
    """Maximum current deliverable to active_stations under meter, bottlenecked by
    every meter's own capacity along the way. Assumes feasibility was already checked
    via _min_required.

    Args:
        meter (Meter): meter to start from.
        active_stations (Set[ChargingStation]): stations assumed to be charging.

    Returns:
        float: maximum current (A) deliverable under meter.
    """
    total = sum(
        station.max_charging_current_amps
        for station in meter.charging_stations
        if station in active_stations
    )
    total += sum(
        _max_deliverable(child, active_stations) for child in meter.child_meters
    )
    return min(total, meter.capacity_amps)


def _brute_force_best_total(
    root_meter: Meter, candidate_stations: List[ChargingStation]
) -> float:
    """Try every subset of candidate_stations ("charging" or not) and return the
    largest total current deliverable by any feasible subset - a car is either off
    (0.0) or on and drawing between MIN_CHARGING_CURRENT_AMPS=6.0 and
    MAX_CHARGING_CURRENT_AMPS=15.0, and every meter's own capacity must be respected.

    This is an exhaustive, independent re-derivation of the optimum: it doesn't call
    optimize() or reuse any of its logic, only the tree structure and capacities.

    Args:
        root_meter (Meter): the hub's root meter.
        candidate_stations (List[ChargingStation]): stations whose on/off state to
            brute-force over (their cars are assumed to share the same priority tier).

    Returns:
        float: the best achievable total current (A) across candidate_stations.
    """
    best = 0.0
    for subset_size in range(len(candidate_stations) + 1):
        for subset in itertools.combinations(candidate_stations, subset_size):
            active = set(subset)
            if _min_required(root_meter, active) <= root_meter.capacity_amps and all(
                _min_required(meter, active) <= meter.capacity_amps
                for meter in root_meter.iter_descendant_meters()
            ):
                best = max(best, _max_deliverable(root_meter, active))
    return best


class OptimizeTestCase(unittest.TestCase):
    """Base class providing a quiet logger and a current-assignment assertion helper."""

    def setUp(self) -> None:
        self.logger = _quiet_logger(self.id())

    def optimize(self, hub: ChargingHub) -> Dict[Car, float]:
        """Assert that hub is consistent, then run optimize() on it.

        Every test should build its hub and call this instead of optimize()
        directly, so a malformed test fixture fails fast on the consistency check
        rather than producing a confusing solver error or a silently wrong result.

        Args:
            hub (ChargingHub): the hub to check and optimize.

        Returns:
            Dict[Car, float]: result of optimize().
        """
        self.assertTrue(
            hub.check_consistency(), "hub must be consistent before optimizing"
        )
        return optimize(self.logger, hub)

    def assert_current_assignment(
        self, assignment: Dict[Car, float], expected_by_car_name: Dict[str, float]
    ) -> None:
        """Assert that assignment matches expected_by_car_name exactly, by car name.

        Args:
            assignment (Dict[Car, float]): result of optimize().
            expected_by_car_name (Dict[str, float]): expected current (A) per car name.
        """
        actual_by_car_name = {car.name: current for car, current in assignment.items()}
        self.assertEqual(set(actual_by_car_name), set(expected_by_car_name))
        for car_name, expected_current in expected_by_car_name.items():
            self.assertAlmostEqual(
                actual_by_car_name[car_name],
                expected_current,
                places=6,
                msg=f"unexpected current for {car_name}",
            )


class TestExampleHub(OptimizeTestCase):
    """Tests against the example_charging_hub_2 topology (25 stations, 5 meters, 7 cars)."""

    def test_no_meter_capacity_binds_every_car_gets_max_current(self) -> None:
        """No meter capacity is anywhere near binding, so every connected car should
        reach its own maximum of 15A, regardless of priority."""
        hub = build_example_hub(self.logger)

        assignment = self.optimize(hub)

        self.assert_current_assignment(
            assignment,
            {
                "car_0": 15.0,
                "car_1": 15.0,
                "car_2": 15.0,
                "car_3": 15.0,
                "car_4": 15.0,
                "car_5": 15.0,
                "car_6": 15.0,
            },
        )

    def test_low_meter_capacity_binds_every_car_gets_max_current(self) -> None:
        """No meter capacity is anywhere near binding, so every connected car should
        reach its own maximum of 15A, regardless of priority."""
        hub = ChargingHub(self.logger)

        # Creating meters
        meter_1: Meter = hub.create_meter("Meter 1", capacity_amps=20)
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
            charging_station = hub.create_charging_station(
                f"Station_2_{idx}", 6.0, 15.0
            )
            meter_2.add_charging_station(charging_station)
            meter_2_stations.append(charging_station)

        meter_4_stations: List[ChargingStation] = []
        for idx in range(5):
            charging_station = hub.create_charging_station(
                f"Station_4_{idx}", 6.0, 15.0
            )
            meter_4.add_charging_station(charging_station)
            meter_4_stations.append(charging_station)

        meter_5_stations: List[ChargingStation] = []
        for idx in range(10):
            charging_station = hub.create_charging_station(
                f"Station_5_{idx}", 6.0, 15.0
            )
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

        assignment = self.optimize(hub)

        self.assert_current_assignment(
            assignment,
            {
                "car_0": 0.0,
                "car_1": 15.0,
                "car_2": 0.0,
                "car_3": 0.0,
                "car_4": 0.0,
                "car_5": 0.0,
                "car_6": 0.0,
            },
        )


class TestCapacityBinding(OptimizeTestCase):
    """Tests with a deliberately tight meter capacity, to check priority precedence
    and the "0 or [6, 15]" charging rule under contention."""

    def _build_two_car_hub(self, capacity_amps: float) -> ChargingHub:
        hub = ChargingHub(self.logger)
        root = hub.create_meter("Root", capacity_amps=capacity_amps)
        station_1 = hub.create_charging_station("S1", 6.0, 15.0)
        station_2 = hub.create_charging_station("S2", 6.0, 15.0)
        root.add_charging_station(station_1)
        root.add_charging_station(station_2)

        car_1 = hub.create_car("C1", priority=1)
        car_5 = hub.create_car("C5", priority=5)
        station_1.connect_car(car_1)
        station_2.connect_car(car_5)
        return hub

    def test_higher_priority_car_gets_served_first(self) -> None:
        """With only 20A available, C1 (priority 1) should take its full 15A first;
        the 5A left over is below the 6A minimum, so C5 (priority 5) must stay off."""
        hub = self._build_two_car_hub(capacity_amps=20)

        assignment = self.optimize(hub)

        self.assert_current_assignment(assignment, {"C1": 15.0, "C5": 0.0})

    def test_leftover_current_below_minimum_is_not_assigned_to_same_priority_car(
        self,
    ) -> None:
        """C_high (priority 1) takes its full 15A. That leaves 3A of the 18A root
        capacity for C_a and C_b (both priority 2, sharing a station under the same
        meter): 3A is below the 6A minimum for either to turn on, so both must be 0 -
        the 3A must go unused rather than being split off between them.
        """
        hub = ChargingHub(self.logger)
        root = hub.create_meter("Root", capacity_amps=18)
        station_high = hub.create_charging_station("S_high", 6.0, 15.0)
        station_a = hub.create_charging_station("S_a", 6.0, 15.0)
        station_b = hub.create_charging_station("S_b", 6.0, 15.0)
        root.add_charging_station(station_high)
        root.add_charging_station(station_a)
        root.add_charging_station(station_b)

        car_high = hub.create_car("C_high", priority=1)
        car_a = hub.create_car("C_a", priority=2)
        car_b = hub.create_car("C_b", priority=2)
        station_high.connect_car(car_high)
        station_a.connect_car(car_a)
        station_b.connect_car(car_b)

        assignment = self.optimize(hub)

        self.assert_current_assignment(
            assignment, {"C_high": 15.0, "C_a": 0.0, "C_b": 0.0}
        )

    def test_low_priority(
        self,
    ) -> None:
        """Simple example where one root with limited capacity, one other with big capacity, and one charging station"""
        hub = ChargingHub(self.logger)
        root = hub.create_meter("Root", capacity_amps=5)
        meter1 = hub.create_meter("meter1", 100)
        root.add_child_meter(meter1)

        charging_station = hub.create_charging_station("S1", 6.0, 15.0)
        meter1.add_charging_station(charging_station)

        car = hub.create_car("car", priority=1)
        charging_station.connect_car(car)

        assignment = self.optimize(hub)

        self.assert_current_assignment(
            assignment,
            {
                "car": 0.0,
            },
        )

    def test_low_priority_several_cars(
        self,
    ) -> None:
        """Simple example where one root with limited capacity, one other with big capacity, and one charging station"""
        hub = ChargingHub(self.logger)
        root = hub.create_meter("Root", capacity_amps=18)
        meter1 = hub.create_meter("meter1", 100)
        root.add_child_meter(meter1)

        meter2 = hub.create_meter("meter2", 100)
        root.add_child_meter(meter2)

        charging_station1 = hub.create_charging_station("S1", 6.0, 15.0)
        meter1.add_charging_station(charging_station1)

        charging_station2 = hub.create_charging_station("S2", 6.0, 15.0)
        meter2.add_charging_station(charging_station2)

        car1 = hub.create_car("car1", priority=1)
        car2 = hub.create_car("car2", priority=10)

        charging_station1.connect_car(car1)
        charging_station2.connect_car(car2)

        assignment = self.optimize(hub)

        self.assert_current_assignment(
            assignment,
            {
                "car1": 15.0,
                "car2": 0.0,
            },
        )


class TestManyCars(OptimizeTestCase):
    """Corner case: a large number of cars/stations under one generously-sized meter."""

    def test_maximum_number_of_cars_all_max_out(self) -> None:
        """25 cars (one per station, spread across all priorities) under a single meter
        with ample capacity: nothing should bind, so every car reaches 15A."""
        hub = ChargingHub(self.logger)
        root = hub.create_meter("Root", capacity_amps=1000)

        expected: Dict[str, float] = {}
        for i in range(25):
            station = hub.create_charging_station(f"S{i}", 6.0, 15.0)
            root.add_charging_station(station)
            car = hub.create_car(f"C{i}", priority=(i % 10) + 1)
            station.connect_car(car)
            expected[f"C{i}"] = 15.0

        assignment = self.optimize(hub)

        self.assert_current_assignment(assignment, expected)

    def test_depth_five_tree_with_ten_meters_and_25_cars(self) -> None:
        """A deeper, wider topology than the other tests: 10 meters arranged 5 edges
        deep from root to the station-holding meters, each meter given a distinct
        capacity, carrying 25 cars split across two depth-5 branches (13 + 12).

        Root -> M1 -> {M2a, M2b} -> {M3a, M3b} -> {M4a, M4b} -> {M5a, M5b}

        Every meter's capacity is comfortably above what its subtree could ever draw
        (worst case: 13 or 12 cars * 15A), so nothing binds - every car should still
        reach its own 15A ceiling regardless of priority or which branch it's on.
        This is a purely structural stress test of deep multi-level flow
        conservation, as opposed to the other tests' capacity-binding scenarios.
        """
        hub = ChargingHub(self.logger)

        root = hub.create_meter("Root", capacity_amps=400)
        m1 = hub.create_meter("M1", capacity_amps=380)
        root.add_child_meter(m1)

        m2a = hub.create_meter("M2a", capacity_amps=250)
        m2b = hub.create_meter("M2b", capacity_amps=220)
        m1.add_child_meter(m2a)
        m1.add_child_meter(m2b)

        m3a = hub.create_meter("M3a", capacity_amps=230)
        m3b = hub.create_meter("M3b", capacity_amps=200)
        m2a.add_child_meter(m3a)
        m2b.add_child_meter(m3b)

        m4a = hub.create_meter("M4a", capacity_amps=210)
        m4b = hub.create_meter("M4b", capacity_amps=190)
        m3a.add_child_meter(m4a)
        m3b.add_child_meter(m4b)

        m5a = hub.create_meter("M5a", capacity_amps=200)
        m5b = hub.create_meter("M5b", capacity_amps=185)
        m4a.add_child_meter(m5a)
        m4b.add_child_meter(m5b)

        self.assertEqual(len(hub.get_all_meters()), 10)

        expected: Dict[str, float] = {}
        for i in range(13):
            station = hub.create_charging_station(f"SA{i}", 6.0, 15.0)
            m5a.add_charging_station(station)
            car = hub.create_car(f"CA{i}", priority=(i % 10) + 1)
            station.connect_car(car)
            expected[f"CA{i}"] = 15.0

        for i in range(12):
            station = hub.create_charging_station(f"SB{i}", 6.0, 15.0)
            m5b.add_charging_station(station)
            car = hub.create_car(f"CB{i}", priority=(i % 10) + 1)
            station.connect_car(car)
            expected[f"CB{i}"] = 15.0

        self.assertEqual(len(expected), 25)

        assignment = self.optimize(hub)

        self.assert_current_assignment(assignment, expected)


class TestExtremeCapacity(OptimizeTestCase):
    """Corner case: a meter capacity many orders of magnitude larger than anything
    that could actually be drawn."""

    def test_very_large_capacity_does_not_limit_any_car(self) -> None:
        """A capacity of 1,000,000A should behave exactly like an unbounded one: the
        car is still capped by its own 15A ceiling, not the meter."""
        hub = ChargingHub(self.logger)
        root = hub.create_meter("Root", capacity_amps=1_000_000.0)
        station = hub.create_charging_station("S", 6.0, 15.0)
        root.add_charging_station(station)
        car = hub.create_car("C", priority=1)
        station.connect_car(car)

        assignment = self.optimize(hub)

        self.assert_current_assignment(assignment, {"C": 15.0})


class TestZeroCapacity(OptimizeTestCase):
    """Corner case: a meter capacity of exactly 0.0A."""

    def test_zero_capacity_root_forces_all_cars_off(self) -> None:
        """If the root itself has 0A capacity, nothing can flow anywhere in the hub,
        regardless of priority."""
        hub = ChargingHub(self.logger)
        root = hub.create_meter("Root", capacity_amps=0.0)
        station = hub.create_charging_station("S", 6.0, 15.0)
        root.add_charging_station(station)
        car = hub.create_car("C", priority=1)
        station.connect_car(car)

        assignment = self.optimize(hub)

        self.assert_current_assignment(assignment, {"C": 0.0})

    def test_zero_capacity_branch_forces_only_that_branch_off(self) -> None:
        """A 0A branch meter should only zero out cars under that specific branch;
        a sibling branch with real capacity should be unaffected."""
        hub = ChargingHub(self.logger)
        root = hub.create_meter("Root", capacity_amps=100)
        dead_branch = hub.create_meter("Dead", capacity_amps=0.0)
        live_branch = hub.create_meter("Live", capacity_amps=50)
        root.add_child_meter(dead_branch)
        root.add_child_meter(live_branch)

        station_dead = hub.create_charging_station("S_dead", 6.0, 15.0)
        dead_branch.add_charging_station(station_dead)
        car_dead = hub.create_car("C_dead", priority=1)
        station_dead.connect_car(car_dead)

        station_live = hub.create_charging_station("S_live", 6.0, 15.0)
        live_branch.add_charging_station(station_live)
        car_live = hub.create_car("C_live", priority=1)
        station_live.connect_car(car_live)

        assignment = self.optimize(hub)

        self.assert_current_assignment(assignment, {"C_dead": 0.0, "C_live": 15.0})


class TestDeepMeterChain(OptimizeTestCase):
    """Corner case: a long single-child chain of meters, to check that a capacity
    constraint on an interior meter (neither root nor leaf) still propagates
    correctly through several hops."""

    def test_deep_chain_bottleneck_propagates_through_interior_meter(self) -> None:
        """5 meters chained one after another; the tightest capacity (8A) sits in the
        middle (M3), well below its ancestors' and descendants' capacities. The car
        should be bottlenecked to exactly 8A - not 0 (8 >= MIN_CHARGING_CURRENT_AMPS)
        and not 15 (M3's capacity is the binding constraint)."""
        hub = ChargingHub(self.logger)
        m1 = hub.create_meter("M1", capacity_amps=50)
        m2 = hub.create_meter("M2", capacity_amps=40)
        m3 = hub.create_meter("M3", capacity_amps=8)
        m4 = hub.create_meter("M4", capacity_amps=30)
        m5 = hub.create_meter("M5", capacity_amps=25)
        m1.add_child_meter(m2)
        m2.add_child_meter(m3)
        m3.add_child_meter(m4)
        m4.add_child_meter(m5)

        station = hub.create_charging_station("S", 6.0, 15.0)
        m5.add_charging_station(station)
        car = hub.create_car("C", priority=1)
        station.connect_car(car)

        assignment = self.optimize(hub)

        self.assert_current_assignment(assignment, {"C": 8.0})


class TestBruteForceComparison(OptimizeTestCase):
    """Builds a scenario rich enough (multiple meter levels, a same-priority group
    forced to choose how many of its cars to turn on, and an independent tied-priority
    pair) that its optimum isn't obvious by inspection, then independently
    re-derives the expected optimum by brute force and compares against optimize().
    """

    def test_complex_scenario_matches_brute_force_optimum(self) -> None:
        """Topology:

        Root (capacity=100, not binding)
          MeterA (capacity=17): 3 same-priority(2) cars sharing one station each.
              6A/car minimum means at most 2 of the 3 can be on at once
              (3 * 6 = 18 > 17), so the optimizer has to actually decide *how many*
              to turn on, not just which - a genuine combinatorial choice.
          MeterB (capacity=20)
              MeterB1 (capacity=9) -> one priority-1 car
              MeterB2 (capacity=9) -> one priority-1 car
              Each priority-1 car is alone under its own 9A sub-meter, so each is
              independently bottlenecked to exactly 9A (unambiguous), and MeterB's
              own 20A capacity is never actually binding (9 + 9 = 18 <= 20).

        The priority-1 pair's expected values are unambiguous and asserted exactly.
        The priority-2 trio's individual split is symmetric (any 2 of the 3 could
        win), so only the aggregate total and the count of cars actually charging
        are asserted - both independently re-derived by _brute_force_best_total,
        not hardcoded.
        """
        hub = ChargingHub(self.logger)
        root = hub.create_meter("Root", capacity_amps=100)

        meter_a = hub.create_meter("MeterA", capacity_amps=17)
        root.add_child_meter(meter_a)
        stations_a = [
            hub.create_charging_station(f"SA{i}", 6.0, 15.0) for i in range(3)
        ]
        for station in stations_a:
            meter_a.add_charging_station(station)
        cars_a = [hub.create_car(f"CA{i}", priority=2) for i in range(3)]
        for station, car in zip(stations_a, cars_a):
            station.connect_car(car)

        meter_b = hub.create_meter("MeterB", capacity_amps=20)
        root.add_child_meter(meter_b)
        meter_b1 = hub.create_meter("MeterB1", capacity_amps=9)
        meter_b2 = hub.create_meter("MeterB2", capacity_amps=9)
        meter_b.add_child_meter(meter_b1)
        meter_b.add_child_meter(meter_b2)
        station_b1 = hub.create_charging_station("SB1", 6.0, 15.0)
        station_b2 = hub.create_charging_station("SB2", 6.0, 15.0)
        meter_b1.add_charging_station(station_b1)
        meter_b2.add_charging_station(station_b2)
        car_b1 = hub.create_car("CB1", priority=1)
        car_b2 = hub.create_car("CB2", priority=1)
        station_b1.connect_car(car_b1)
        station_b2.connect_car(car_b2)

        # Independently re-derive the expected optimum by brute force, without
        # calling optimize() or reusing any of its logic.
        expected_b_total = _brute_force_best_total(root, [station_b1, station_b2])
        expected_a_total = _brute_force_best_total(root, stations_a)

        assignment = self.optimize(hub)
        actual_by_name = {car.name: current for car, current in assignment.items()}

        # Priority-1 pair: unambiguous, assert exact values.
        self.assertAlmostEqual(actual_by_name["CB1"], 9.0, places=6)
        self.assertAlmostEqual(actual_by_name["CB2"], 9.0, places=6)
        self.assertAlmostEqual(
            actual_by_name["CB1"] + actual_by_name["CB2"], expected_b_total, places=6
        )

        # Priority-2 trio: assert against the brute-forced aggregate and on-count,
        # since which 2 of the 3 symmetric cars win is not uniquely determined.
        a_values = [actual_by_name[f"CA{i}"] for i in range(3)]
        self.assertAlmostEqual(sum(a_values), expected_a_total, places=6)
        self.assertEqual(sum(1 for v in a_values if v > 0.0), 2)
        for value in a_values:
            self.assertTrue(
                value == 0.0 or 6.0 <= value <= 15.0,
                f"current {value} is neither 0 nor within the allowed charging range",
            )


class TestPartialCapacityLimiting(OptimizeTestCase):
    """Tests where capacity limits some cars to a value strictly between 0 and 15A -
    not just on/off - while a sibling branch elsewhere in the same hub is completely
    unaffected."""

    def test_leftover_after_higher_priority_partially_limits_lower_priority_car(
        self,
    ) -> None:
        """Tight branch (23A): C1 (priority 1) takes its full 15A, leaving 8A for C5
        (priority 5) - enough to turn on (>= 6A) but not enough to reach 15A, so C5
        should land at exactly 8A. Loose branch (500A): the same priority pattern,
        but with ample capacity, so both cars there reach 15A untouched."""
        hub = ChargingHub(self.logger)
        root = hub.create_meter("Root", capacity_amps=1000)
        branch_tight = hub.create_meter("Tight", capacity_amps=23)
        branch_loose = hub.create_meter("Loose", capacity_amps=500)
        root.add_child_meter(branch_tight)
        root.add_child_meter(branch_loose)

        station_1 = hub.create_charging_station("S1", 6.0, 15.0)
        station_5 = hub.create_charging_station("S5", 6.0, 15.0)
        branch_tight.add_charging_station(station_1)
        branch_tight.add_charging_station(station_5)
        car_1 = hub.create_car("C1", priority=1)
        car_5 = hub.create_car("C5", priority=5)
        station_1.connect_car(car_1)
        station_5.connect_car(car_5)

        station_loose_1 = hub.create_charging_station("SL1", 6.0, 15.0)
        station_loose_5 = hub.create_charging_station("SL5", 6.0, 15.0)
        branch_loose.add_charging_station(station_loose_1)
        branch_loose.add_charging_station(station_loose_5)
        car_loose_1 = hub.create_car("CL1", priority=1)
        car_loose_5 = hub.create_car("CL5", priority=5)
        station_loose_1.connect_car(car_loose_1)
        station_loose_5.connect_car(car_loose_5)

        assignment = self.optimize(hub)

        self.assert_current_assignment(
            assignment, {"C1": 15.0, "C5": 8.0, "CL1": 15.0, "CL5": 15.0}
        )

    def test_branch_ceiling_limits_top_priority_car_below_its_own_maximum(
        self,
    ) -> None:
        """A branch capped at 10A limits even its lone, top-priority car to 10A - not
        because it's competing with anyone (it's alone under its meter), but because
        the branch's own capacity is below the car's 15A ceiling. A sibling branch
        with ample capacity holds an identically-configured car that reaches 15A."""
        hub = ChargingHub(self.logger)
        root = hub.create_meter("Root", capacity_amps=1000)
        branch_capped = hub.create_meter("Capped", capacity_amps=10)
        branch_free = hub.create_meter("Free", capacity_amps=500)
        root.add_child_meter(branch_capped)
        root.add_child_meter(branch_free)

        station_capped = hub.create_charging_station("S_capped", 6.0, 15.0)
        branch_capped.add_charging_station(station_capped)
        car_capped = hub.create_car("C_capped", priority=1)
        station_capped.connect_car(car_capped)

        station_free = hub.create_charging_station("S_free", 6.0, 15.0)
        branch_free.add_charging_station(station_free)
        car_free = hub.create_car("C_free", priority=1)
        station_free.connect_car(car_free)

        assignment = self.optimize(hub)

        self.assert_current_assignment(assignment, {"C_capped": 10.0, "C_free": 15.0})

    def test_25_with_15_plus_10(
        self,
    ) -> None:
        """Scenario to check we use the full 25 available with 15+10"""
        hub = ChargingHub(self.logger)
        root = hub.create_meter("Root", capacity_amps=1000)
        branch_capped = hub.create_meter("Capped", capacity_amps=25)
        root.add_child_meter(branch_capped)

        station_1 = hub.create_charging_station("S1", 6.0, 15.0)
        station_2 = hub.create_charging_station("S2", 6.0, 15.0)
        station_3 = hub.create_charging_station("S3", 6.0, 15.0)

        branch_capped.add_charging_station(station_1)
        branch_capped.add_charging_station(station_2)
        branch_capped.add_charging_station(station_3)

        car1 = hub.create_car("car1", priority=1)
        car2 = hub.create_car("car2", priority=5)
        car3 = hub.create_car("car3", priority=5)

        station_1.connect_car(car1)
        station_2.connect_car(car2)
        station_3.connect_car(car3)

        assignment = self.optimize(hub)

        self.assert_current_assignment(
            assignment, {"car1": 15.0, "car2": 0.0, "car3": 10.0}
        )

    def test_31_with_15_plus_6_plus_10(
        self,
    ) -> None:
        """Scenario to check we use the full 27 available with 15+6+6"""
        hub = ChargingHub(self.logger)
        root = hub.create_meter("Root", capacity_amps=1000)
        branch_capped = hub.create_meter("Capped", capacity_amps=31)
        root.add_child_meter(branch_capped)

        station_1 = hub.create_charging_station("S1", 6.0, 15.0)
        station_2 = hub.create_charging_station("S2", 6.0, 15.0)
        station_3 = hub.create_charging_station("S3", 6.0, 15.0)

        branch_capped.add_charging_station(station_1)
        branch_capped.add_charging_station(station_2)
        branch_capped.add_charging_station(station_3)

        car1 = hub.create_car("car1", priority=1)
        car2 = hub.create_car("car2", priority=5)
        car3 = hub.create_car("car3", priority=5)

        station_1.connect_car(car1)
        station_2.connect_car(car2)
        station_3.connect_car(car3)

        assignment = self.optimize(hub)

        self.assert_current_assignment(
            assignment, {"car1": 15.0, "car2": 6.0, "car3": 10.0}
        )

    def test_33_with_15_plus_6_plus_6_plus_6(
        self,
    ) -> None:
        """Scenario to check we use the full 33 available with 15+6+6+6 or variant"""
        hub = ChargingHub(self.logger)
        root = hub.create_meter("Root", capacity_amps=1000)
        branch_capped = hub.create_meter("Capped", capacity_amps=33)
        root.add_child_meter(branch_capped)

        station_1 = hub.create_charging_station("S1", 6.0, 15.0)
        station_2 = hub.create_charging_station("S2", 6.0, 15.0)
        station_3 = hub.create_charging_station("S3", 6.0, 15.0)
        station_4 = hub.create_charging_station("S4", 6.0, 15.0)

        branch_capped.add_charging_station(station_1)
        branch_capped.add_charging_station(station_2)
        branch_capped.add_charging_station(station_3)
        branch_capped.add_charging_station(station_4)

        car1 = hub.create_car("car1", priority=1)
        car2 = hub.create_car("car2", priority=5)
        car3 = hub.create_car("car3", priority=5)
        car4 = hub.create_car("car4", priority=5)

        station_1.connect_car(car1)
        station_2.connect_car(car2)
        station_3.connect_car(car3)
        station_4.connect_car(car4)

        assignment = self.optimize(hub)

        self.assert_current_assignment(
            assignment, {"car1": 15.0, "car2": 6.0, "car3": 0.0, "car4": 12.0}
        )


class TestMixedLimitingComplexScenario(OptimizeTestCase):
    """A single hub combining three branches, each with a different capacity-limiting
    behavior, at three different priority tiers, plus a fourth, fully unconstrained
    branch - checking that none of these interfere with each other."""

    def test_three_branches_with_different_limiting_behaviors_stay_independent(
        self,
    ) -> None:
        """Branch 'Full' (500A, priority 1, 5 cars): capacity is a non-issue, every
        car reaches 15A.

        Branch 'Partial' (50A, priority 2, 4 cars): 3 cars alone can reach at most
        45A (3*15), strictly less than the 50A available, so the true optimum
        requires all 4 cars charging simultaneously - every one of them ends up
        below its own 15A ceiling. This is the "all limited, none off" flavor,
        distinct from the "some off, some maxed" flavor tested elsewhere.

        Branch 'Mixed' (17A, priority 3, 3 cars): the already-verified "exactly 2 of
        3 symmetric cars turn on" case, reused here at a different priority tier and
        alongside other branches, to confirm it still holds under a more complex,
        multi-branch, multi-priority hub.
        """
        hub = ChargingHub(self.logger)
        root = hub.create_meter("Root", capacity_amps=1000)

        branch_full = hub.create_meter("Full", capacity_amps=500)
        root.add_child_meter(branch_full)
        full_stations = [
            hub.create_charging_station(f"SF{i}", 6.0, 15.0) for i in range(5)
        ]
        for station in full_stations:
            branch_full.add_charging_station(station)
        full_cars = [hub.create_car(f"CF{i}", priority=1) for i in range(5)]
        for station, car in zip(full_stations, full_cars):
            station.connect_car(car)

        branch_partial = hub.create_meter("Partial", capacity_amps=50)
        root.add_child_meter(branch_partial)
        partial_stations = [
            hub.create_charging_station(f"SP{i}", 6.0, 15.0) for i in range(4)
        ]
        for station in partial_stations:
            branch_partial.add_charging_station(station)
        partial_cars = [hub.create_car(f"CP{i}", priority=2) for i in range(4)]
        for station, car in zip(partial_stations, partial_cars):
            station.connect_car(car)

        branch_mixed = hub.create_meter("Mixed", capacity_amps=17)
        root.add_child_meter(branch_mixed)
        mixed_stations = [
            hub.create_charging_station(f"SM{i}", 6.0, 15.0) for i in range(3)
        ]
        for station in mixed_stations:
            branch_mixed.add_charging_station(station)
        mixed_cars = [hub.create_car(f"CM{i}", priority=3) for i in range(3)]
        for station, car in zip(mixed_stations, mixed_cars):
            station.connect_car(car)

        # Independently re-derive each branch's expected optimum by brute force.
        expected_full_total = _brute_force_best_total(root, full_stations)
        expected_partial_total = _brute_force_best_total(root, partial_stations)
        expected_mixed_total = _brute_force_best_total(root, mixed_stations)

        assignment = self.optimize(hub)
        actual_by_name = {car.name: current for car, current in assignment.items()}

        # Full branch: unaffected, every car at its own 15A ceiling.
        full_values = [actual_by_name[f"CF{i}"] for i in range(5)]
        self.assertTrue(all(v == 15.0 for v in full_values))
        self.assertAlmostEqual(sum(full_values), expected_full_total, places=6)

        # Partial branch: all 4 cars charging, none at their individual ceiling.
        partial_values = [actual_by_name[f"CP{i}"] for i in range(4)]
        self.assertAlmostEqual(sum(partial_values), expected_partial_total, places=6)
        self.assertTrue(
            all(v > 0.0 for v in partial_values),
            "every car in this branch should be on",
        )
        self.assertTrue(
            all(v <= 15.0 for v in partial_values),
            "no single car should reach its own ceiling here",
        )

        # Mixed branch: exactly 2 of the 3 symmetric cars win.
        mixed_values = [actual_by_name[f"CM{i}"] for i in range(3)]
        self.assertAlmostEqual(sum(mixed_values), expected_mixed_total, places=6)
        self.assertEqual(sum(1 for v in mixed_values if v > 0.0), 2)


if __name__ == "__main__":
    unittest.main()
