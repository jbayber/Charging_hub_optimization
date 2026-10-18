"""Domain model for a charging hub: a tree of meters feeding charging stations, each one potentially occupied by a car."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Generic, Iterator, List, Optional, TypeVar

MIN_CAR_PRIORITY: int = 1
MAX_CAR_PRIORITY: int = 10


class Meter(object):
    """A meter-node in the charging hub tree.

    It is defined by:
    -its capacity (in amps)
    -its parent meter
    -its child meters
    -its charging stations

    Important: a meter can have only one parent, and one of the two:
    -Child(ren) meter(s).
    -Charging station(s).

    """

    def __init__(self, name: str, capacity_amps: float, logger: logging.Logger):
        """Init.

        Args:
            name (str): human readable name for the meter.
            capacity_amps (float): Capacity (A) of the meter.
            logger (logging.Logger): logger used for this meter's activity.

        """
        if capacity_amps < 0:
            logger.error(
                "%s: capacity_amps must be positive, got %s", name, capacity_amps
            )

        self._name = name
        self._capacity_amps = capacity_amps
        self._logger = logger

        self._parent: Optional[Meter] = None
        self._child_meters: List[Meter] = []
        self._charging_stations: List[ChargingStation] = []

        self._logger.info(
            "Created meter %s (capacity=%sA)", self._name, self._capacity_amps
        )

    def add_child_meter(self, child_meter: Meter) -> None:
        """Add a child meter to this meter. The child meter is considered to be connected to this meter.

        Args:
            child_meter (Meter): Child meter considered to be added.

        """
        if child_meter is self:
            self._logger.error("%s: a meter cannot be its own child", self._name)

        if child_meter.parent is not None:
            self._logger.error(
                "%s already has a parent (%s)",
                child_meter.name,
                child_meter.parent.name,
            )
        if len(self._charging_stations) > 0:
            self._logger.error(
                "%s already has charging station(s) connected", self._name
            )

        # Checking for potential cycle in the tree.
        ancestor = self._parent
        while ancestor is not None:
            if ancestor is child_meter:
                self._logger.error(
                    "%s: attaching would create a cycle", child_meter.name
                )
            ancestor = ancestor.parent

        child_meter._parent = self
        self._child_meters.append(child_meter)
        self._logger.info(
            "Attached meter %s as child of %s", child_meter.name, self._name
        )

    def add_charging_station(self, station: ChargingStation) -> None:
        """Add charging station.

        Args:
            station (ChargingStation): A charging station.

        """
        if station.meter is not None:
            self._logger.error(
                "%s is already attached to meter %s",
                station.name,
                station.meter.name,
            )
        if len(self._child_meters) > 0:
            self._logger.error("%s already has child meter(s) connected", self._name)

        station._meter = self
        self._charging_stations.append(station)
        self._logger.info(
            "Attached charging station %s to meter %s", station.name, self._name
        )

    @property
    def name(self) -> str:
        """str: human readable name for the meter."""
        return self._name

    @property
    def capacity_amps(self) -> float:
        """float: capacity (A) of the meter."""
        return self._capacity_amps

    @property
    def parent(self) -> Optional[Meter]:
        """Optional[Meter]: this meter's parent, or None if it is the root."""
        return self._parent

    @property
    def child_meters(self) -> List[Meter]:
        """List[Meter]: meters directly attached below this meter."""
        return self._child_meters

    @property
    def charging_stations(self) -> List[ChargingStation]:
        """List[ChargingStation]: charging stations directly attached to this meter."""
        return self._charging_stations

    def is_root(self) -> bool:
        """Return whether meter is the root.

        Returns:
            bool: whether meter is the root
        """
        return self._parent is None

    def iter_descendant_meters(self) -> Iterator[Meter]:
        """Yield this meter and every meter reachable below it.

        Yields:
            Iterator[Meter]: Descending meters iterators.
        """
        yield self
        for child in self._child_meters:
            yield from child.iter_descendant_meters()

    def iter_descendant_stations(self) -> Iterator[ChargingStation]:
        """Yield every charging station reachable under this meter, at any depth.

        Yields:
            Iterator[Meter]: charging station iterator.
        """
        for station in self._charging_stations:
            yield station
        for child in self._child_meters:
            yield from child.iter_descendant_stations()

    def has_at_least_one_descendant_station_occupied(
        self, priority: int = MAX_CAR_PRIORITY
    ) -> bool:
        """Return whether at least one descendant charging station is occupied by a car.

        If priority is specified, it ignores car which are less priority.

        Args:
            priority (int): priority to consider.

        Returns:
            bool: whether at least one descendant charging station is occupied.
        """
        return any(
            station.is_occupied(priority) for station in self.iter_descendant_stations()
        )

    def __repr__(self) -> str:
        """String representation.

        Returns:
            str: string representation.
        """
        return f"Meter(name={self._name}, max={self._capacity_amps}A)"


class ChargingStation(object):
    """A charging point.

    It is defined by:
    -potential car connected
    -its parent meter

    Important: a meter can have only one parent, and one of the two:
    -Child(ren) meter(s).
    -Charging station(s).

    """

    def __init__(
        self,
        name: str,
        logger: logging.Logger,
        min_charging_current_amps: float,
        max_charging_current_amps: float,
    ):
        """Init.

        Args:
            name (str): human readable name for the charging station.
            logger (logging.Logger): logger used for this charging station's activity.
            min_charging_current_amps (float): minimum current at which station can operate.
            max_charging_current_amps (float): maximum current that can be delivered.

        """
        if max_charging_current_amps < min_charging_current_amps:
            logger.error(
                "%s: max_charging_current_amps (%s) must be >= min_charging_current_amps (%s)",
                name,
                max_charging_current_amps,
                min_charging_current_amps,
            )

        self._name = name
        self._logger = logger

        self._meter: Optional[Meter] = None
        self._car: Optional[Car] = None
        self._min_charging_current_amps = min_charging_current_amps
        self._max_charging_current_amps = max_charging_current_amps

        self._logger.info("Created charging station %s", self._name)

    @property
    def name(self) -> str:
        """str: human readable name for the charging station."""
        return self._name

    @property
    def meter(self) -> Optional[Meter]:
        """Optional[Meter]: the meter this charging station is attached to."""
        return self._meter

    @property
    def car(self) -> Optional[Car]:
        """Optional[Car]: the car currently connected to this charging station."""
        return self._car

    @property
    def min_charging_current_amps(self) -> float:
        """float: minimum current (A) this station can supply to a car, when charging."""
        return self._min_charging_current_amps

    @property
    def max_charging_current_amps(self) -> float:
        """float: maximum current (A) this station can supply to a car."""
        return self._max_charging_current_amps

    def is_occupied(self, priority: int = MAX_CAR_PRIORITY) -> bool:
        """Return whether the charging station is occupied by a car.

        If priority is specified, it ignores car which are less priority.

        Args:
            priority (int): priority to consider.

        Returns:
            bool: whether the charging station is occupied by a car.
        """
        if self._car is None:
            return False
        else:
            return self._car.priority <= priority

    def connect_car(self, car: Car) -> None:
        """Connect car to the charging station.

        Args:
            car (Car): A car.

        """
        if self._car is not None:
            self._logger.error(
                "%s is already occupied by %s", self._name, self._car.name
            )
        if car.charging_station is not None:
            self._logger.error(
                "%s is already connected to %s", car.name, car.charging_station.name
            )

        self._car = car
        car._charging_station = self
        self._logger.info(
            "Connected car %s to charging station %s", car.name, self._name
        )

    def __repr__(self) -> str:
        """String representation.

        Returns:
            str: string representation.
        """
        car_name = self._car.name if self._car else None
        return f"ChargingStation(name={self._name}, car={car_name})"


class Car(object):
    """A car that can be connected to a charging station.

    It is defined by:
    -its priority

    Priority is an integer between 1 and 10, 1 being the highest priority.
    """

    def __init__(self, name: str, priority: int, logger: logging.Logger):
        """Init.

        Args:
            name (str): human readable name for the car.
            priority: priority of the car, between 1 and 10.
            logger (logging.Logger): logger used for this car's activity.

        """

        if not (MIN_CAR_PRIORITY <= priority <= MAX_CAR_PRIORITY):
            logger.error(
                "%s: priority must be between %s and %s, got %s",
                name,
                MIN_CAR_PRIORITY,
                MAX_CAR_PRIORITY,
                priority,
            )

        self._name = name
        self._priority = priority
        self._logger = logger

        self._charging_station: ChargingStation = None
        self._charging_current_amps: float = 0.0

        self._logger.info("Created car %s (priority=%s)", self._name, self._priority)

    @property
    def name(self) -> str:
        """str: human readable name for the car."""
        return self._name

    @property
    def charging_current_amps(self) -> float:
        """float: current (A) currently supplied to the car."""
        return self._charging_current_amps

    @property
    def priority(self) -> int:
        """int: priority of the car."""
        return self._priority

    @property
    def charging_station(self) -> Optional[ChargingStation]:
        """Optional[ChargingStation]: the charging station this car is connected to."""
        return self._charging_station

    def set_current(self, current_amps: float) -> None:
        """Set the current supplied to the car.

        Args:
            current_amps (float): current in amps.

        """
        if current_amps != 0.0 and not (
            self.charging_station.min_charging_current_amps
            <= current_amps
            <= self.charging_station.max_charging_current_amps
        ):
            self._logger.error("%s: invalid current %sA", self._name, current_amps)

        self._charging_current_amps = current_amps
        self._logger.info("Set current of car %s to %sA", self._name, current_amps)

    def __repr__(self) -> str:
        """String representation.

        Returns:
            str: string representation.
        """
        station_id = self._charging_station.name if self._charging_station else None
        return (
            f"Car(name={self._name}, priority={self._priority}, "
            f"current={self._charging_current_amps}A, station={station_id})"
        )


PoolItem = TypeVar("PoolItem")


class Pool(Generic[PoolItem]):
    """Base pool: stores every object created via a subclass's create(...) method.

    Subclasses only need to implement create() and call self._register(...) on the result.
    """

    def __init__(self, logger: logging.Logger):
        """Init.

        Args:
            logger (logging.Logger): logger
        """
        self._logger = logger
        self._items: List[PoolItem] = []

    def _register(self, item: PoolItem) -> PoolItem:
        """Add a newly created item to the pool.

        Args:
            item (PoolItem): item to register

        Returns:
            PoolItem: same item
        """
        self._items.append(item)
        return item

    def get_all(self) -> List[PoolItem]:
        """Return all objects created by this pool.

        Returns:
            List[PoolItem]: all created objects.
        """
        return self._items


class MeterPool(Pool[Meter]):
    def create(self, name: str, capacity_amps: float) -> Meter:
        """Create meter object.

        Args:
            name (str): human readable name.
            capacity_amps (float): capacity of meter.

        Returns:
            Meter: created meter.
        """
        return self._register(
            Meter(name.replace(" ", "_"), capacity_amps, self._logger)
        )


class ChargingStationPool(Pool[ChargingStation]):
    def create(
        self,
        name: str,
        min_charging_current_amps: float,
        max_charging_current_amps: float,
    ) -> ChargingStation:
        """Create charging station object.

        Args:
            name (str): human readable name.
            min_charging_current_amps (float): minimum current at which station can operate.
            max_charging_current_amps (float): maximum current that can be delivered.

        Returns:
            ChargingStation: created charging station.
        """
        return self._register(
            ChargingStation(
                name.replace(" ", "_"),
                self._logger,
                min_charging_current_amps,
                max_charging_current_amps,
            )
        )


class CarPool(Pool[Car]):
    def create(self, name: str, priority: int) -> Car:
        """Create a car.

        Args:
            name (str): human readable name.
            priority (int): car's priority.

        Returns:
            Car: created car.
        """
        return self._register(Car(name.replace(" ", "_"), priority, self._logger))


class ChargingHub(object):
    """Master object to represent the ChargingHub problem."""

    def __init__(self, logger: logging.Logger):
        """Init

        Args:
            logger (logging.Logger): logger
        """
        self._logger = logger
        self._meter_pool = MeterPool(logger)
        self._charging_station_pool = ChargingStationPool(logger)
        self._car_pool = CarPool(logger)

    def create_meter(self, name: str, capacity_amps: float) -> Meter:
        """Create a meter via the meter pool.

        Args:
            name (str): human readable name.
            capacity_amps (float): capacity of meter.

        Returns:
            Meter: created meter.
        """
        return self._meter_pool.create(name, capacity_amps)

    def create_charging_station(
        self,
        name: str,
        min_charging_current_amps: float,
        max_charging_current_amps: float,
    ) -> ChargingStation:
        """Create a charging station via the charging station pool.

        Args:
            name (str): human readable name.
            min_charging_current_amps (float): minimum current at which station can operate.
            max_charging_current_amps (float): maximum current that can be delivered.

        Returns:
            ChargingStation: created charging station.
        """
        return self._charging_station_pool.create(
            name, min_charging_current_amps, max_charging_current_amps
        )

    def create_car(self, name: str, priority: int) -> Car:
        """Create a car via the car pool.

        Args:
            name (str): human readable name.
            priority (int): car's priority.

        Returns:
            Car: created car.
        """
        return self._car_pool.create(name, priority)

    def get_all_meters(self) -> List[Meter]:
        """Return every meter created in this hub.

        Returns:
            List[Meter]: all created meters.
        """
        return self._meter_pool.get_all()

    def get_root_meter(self) -> Meter:
        """Return the single meter with no parent.

        Returns:
            Meter: the root meter.

        """
        root_meters = [
            meter for meter in self._meter_pool.get_all() if meter.parent is None
        ]
        if len(root_meters) != 1:
            self._logger.error(
                "Unexpected number of root meter. Should be exactly one."
            )

        return root_meters[0]

    def get_all_charging_stations(self) -> List[ChargingStation]:
        """Return every charging station created in this hub.

        Returns:
            List[ChargingStation]: all created charging stations.
        """
        return self._charging_station_pool.get_all()

    def get_all_cars(self) -> List[Car]:
        """Return every car created in this hub.

        Returns:
            List[Car]: all created cars.
        """
        return self._car_pool.get_all()

    def apply_current(self, car_charging_assignement: Dict[Car, float]) -> None:
        """Apply current to existing cars.

        For every car in this hub, current is set to the value found in
        car_charging_assignement if present.

        Args:
            car_charging_assignement (Dict[Car, float]): current (A) to apply, keyed by car.
        """
        for car in self._car_pool.get_all():
            if car in car_charging_assignement:
                car.set_current(car_charging_assignement[car])

    def create_graph(self, export_path: str) -> None:
        """Write a Graph dot representation of the Hub.

        It disregards the tree structures and draws every meter, charging station and car ever created.
        The idea is to get a full representation of the data and find inconsistencies such as standalone nodes.

        To visualize online: https://www.devtoolsdaily.com/graphviz/
        Dot languages: https://graphviz.org/doc/info/lang.html

        Args:
            export_path (str): destination path for generated .dot file.
        """
        self._logger.info(
            "Starting to create graph file. Will export to: %s", export_path
        )

        directory = os.path.dirname(export_path)
        if not os.path.exists(directory):
            os.makedirs(directory)

        meters = self._meter_pool.get_all()
        stations = self._charging_station_pool.get_all()
        cars = self._car_pool.get_all()

        lines = ["graph charging_hub {", ""]

        lines.append("  // Meters")
        for meter in meters:
            current = sum(
                station.car.charging_current_amps if station.car is not None else 0.0
                for station in meter.iter_descendant_stations()
            )
            label = f"{meter.name}\\n{current}A / {meter.capacity_amps}A"
            lines.append(
                f"  {meter.name} "
                f'[shape=ellipse, style=filled, color=lightblue, label="{label}"];'
            )

        lines.append("")
        lines.append("  // Charging stations")
        for station in stations:
            current = (
                station.car.charging_current_amps if station.car is not None else 0.0
            )
            label = f"{station.name}\\n{current}A / ({station.min_charging_current_amps},{station.max_charging_current_amps})A"
            lines.append(
                f"  {station.name} "
                f'[shape=box, style=filled, color=orange, label="{label}"];'
            )

        lines.append("")
        lines.append("  // Cars")
        for car in cars:
            label = (
                f"{car.name}\\npriority {car.priority}\n {car.charging_current_amps}A"
            )
            lines.append(
                f"  {car.name} "
                f'[shape=ellipse, style=filled, color=pink, label="{label}"];'
            )

        lines.append("")
        lines.append("  // Meter -> meter")
        for meter in meters:
            if meter.parent is not None:
                lines.append(f"  {meter.parent.name} -- {meter.name};")

        lines.append("")
        lines.append("  // Meter -> charging station")
        for station in stations:
            if station.meter is not None:
                lines.append(f"  {station.meter.name} -- {station.name};")

        lines.append("")
        lines.append("  // Charging station -> car")
        for car in cars:
            if car.charging_station is not None:
                lines.append(f"  {car.charging_station.name} -- {car.name};")

        lines.append("}")

        with open(export_path, "w") as dot_file:
            dot_file.write("\n".join(lines) + "\n")

        self._logger.info("Graph written to %s", export_path)

    def check_consistency(self) -> bool:
        """Check consistency of all data.

        Look at every object created by the pools directly, not the tree structure, so all objects are looked at.

        Checks performed:
        - Every car is connected to a charging station.
        - Car names are unique.
        - At most one car is connected per charging station.
        - Every charging station is connected to a meter.
        - Charging station names are unique.
        - Every charging station is attached to at most one meter.
        - Every meter has a parent, except one (the root).
        - Meter names are unique.
        - Every car's current is 0.0 or within [min_current, max_current] defined by the station.
        - Every car's priority is within [MIN_CAR_PRIORITY, MAX_CAR_PRIORITY].
        - Every meter's capacity is respected by the sum of the currents of its descendant charging stations.

        Returns:
            bool: whether the charging hub is consistent.
        """
        self._logger.info("Starting charging hub consistency checks")

        def _duplicate_name_errors(label: str, objects: List) -> List[str]:
            """Return one error string per name used more than once among the objects.

            Args:
                label (str): human readable name of the object type.
                objects (List): objects to check, each expected to have a name property.

            Returns:
                List[str]: one error message per name shared by more than one object.
            """
            objects_by_name: Dict[str, Any] = {}
            for entity in objects:
                objects_by_name.setdefault(entity.name, []).append(entity)

            duplicates: List[str] = []
            for entity_name, corresponding_objects in objects_by_name.items():
                if len(corresponding_objects) > 1:
                    duplicates.append(
                        f"Duplicate {label} name {entity_name} used by "
                        f"{len(corresponding_objects)} entities"
                    )

            return duplicates

        meters = self._meter_pool.get_all()
        stations = self._charging_station_pool.get_all()
        cars = self._car_pool.get_all()

        errors: List[str] = []

        # Check that all cars are connected to charging station
        for car in cars:
            if car.charging_station is None:
                errors.append(f"{car.name}: car not connected to any charging station")

        # Check only one car connected to each charging station
        cars_per_station: Dict[ChargingStation, List[Car]] = {}
        for car in cars:
            if car.charging_station is not None:
                cars_per_station.setdefault(car.charging_station, []).append(car)

        for station, connected_cars in cars_per_station.items():
            if len(connected_cars) > 1:
                car_names = ", ".join(car.name for car in connected_cars)
                errors.append(
                    f"{station.name}: more than one car connected ({car_names})"
                )

        # Check that all stations are connected to a meter
        for station in stations:
            if station.meter is None:
                errors.append(
                    f"{station.name}: charging station is not connected to any meter"
                )

        # Check that each station is attached to at most one meter
        owning_meters_per_station: Dict[ChargingStation, List[Meter]] = {}
        for meter in meters:
            for station in meter.charging_stations:
                owning_meters_per_station.setdefault(station, []).append(meter)

        for station, owning_meters in owning_meters_per_station.items():
            if len(owning_meters) > 1:
                meter_names = ", ".join(meter.name for meter in owning_meters)
                errors.append(
                    f"{station.name}: attached to more than one meter ({meter_names})"
                )

        # Check that each car's current is 0.0 or within the allowed charging range
        for car in cars:
            current = car.charging_current_amps
            if current != 0.0 and not (
                car.charging_station.min_charging_current_amps
                <= current
                <= car.charging_station.max_charging_current_amps
            ):
                errors.append(f"{car.name}: invalid current {current} ")

        # Check that each car's priority is within the allowed range
        for car in cars:
            if not (MIN_CAR_PRIORITY <= car.priority <= MAX_CAR_PRIORITY):
                errors.append(f"{car.name}: invalid priority: {car.priority}")

        # Check that each meter's capacity is respected by its descendant charging stations
        for meter in meters:
            total_current = sum(
                station.car.charging_current_amps if station.car is not None else 0.0
                for station in meter.iter_descendant_stations()
            )
            if total_current > meter.capacity_amps:
                errors.append(
                    f"{meter.name}: invalid current drawn {total_current}A vs max {meter.capacity_amps}A"
                )

        # Check that one and only one meter has no parent (the root)
        root_meters = [meter for meter in meters if meter.parent is None]
        if len(root_meters) == 0:
            errors.append("No root meter found: every meter has a parent")
        elif len(root_meters) > 1:
            root_names = ", ".join(meter.name for meter in root_meters)
            errors.append(
                f"Expected exactly one root meter, found {len(root_meters)}: {root_names}"
            )

        # Check for name duplication
        errors.extend(_duplicate_name_errors("meter", meters))
        errors.extend(_duplicate_name_errors("car", cars))
        errors.extend(_duplicate_name_errors("charging station", stations))

        if errors:
            self._logger.error("Consistency errors found:")

            for error in errors:
                self._logger.error("\t-%s", error)

        self._logger.info("Charging hub consistency checks done")

        return len(errors) == 0
