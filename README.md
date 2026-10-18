# Charging hub optimization

Allocate charging current to electric cars in a charging hub, so that the hub's electrical limits are never exceeded and higher-priority cars are served first.

The hub is modeled as a tree of meters feeding charging stations. The allocation is solved as a sequence of mixed-integer linear programs (MILP) with [Google OR-Tools](https://developers.google.com/optimization).

## Requirements

- Python 3.13.
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (recommended) or pip.
- Optional: [Graphviz](https://graphviz.org/download/) to render the hub diagrams.

## Installation

Create and activate a virtual environment, then install the package in editable mode with the development tools:

```bash
uv venv -p 3.13
source .venv/bin/activate
make install            # same as: uv pip install -e ".[dev]"
```

Available extras:

| Extra | Contents | Command |
|---|---|---|
| *(none)* | The package and OR-Tools | `uv pip install -e .` |
| `test` | + pytest | `uv pip install -e ".[test]"` |
| `dev` | + pytest and ruff | `uv pip install -e ".[dev]"` |

Without uv, use `python -m venv .venv` and `pip install -e ".[dev]"` instead.

## Running

Two example scripts build the example hub from the assignment (5 meters, 25 stations, 7 cars). Run them from the repository root:

```bash
python examples/example_charging_hub_2.py   # runs the optimizer
python examples/example_charging_hub.py     # dummy allocation (every car at 6 A), to check the data model
```

Each script:

1. Builds the hub and writes its diagram to `tmp/input_hub*.dot`.
2. Checks the hub's consistency, and stops if it's invalid.
3. Allocates current to each car and logs the result.
4. Checks consistency again and writes the result to `tmp/optimized_hub*.dot`.

To use the optimizer from your own code:

```python
import logging

from charging_hub_optimization import ChargingHub
from charging_hub_optimization.optimizer import optimize

logger = logging.getLogger(__name__)
hub = ChargingHub(logger)
# ... create meters, stations and cars, and connect them (see examples/)

assignment = optimize(logger, hub)  # Dict[Car, float]: current in amps per car
hub.apply_current(assignment)
```

## Visualizing

The examples export the hub as [Graphviz DOT](https://graphviz.org/doc/info/lang.html) files in `tmp/`:

- Meters (blue) show current drawn / capacity.
- Stations (orange) show current / (min, max).
- Cars (pink) show priority and current.

To render one, either:

- Paste the file contents into an online viewer such as [devtoolsdaily.com/graphviz](https://www.devtoolsdaily.com/graphviz/), or
- Install Graphviz (`brew install graphviz` on macOS) and render to an image:

  ```bash
  dot -Tsvg tmp/optimized_hub_2.dot -o tmp/optimized_hub_2.svg
  ```

`tmp/` is git-ignored.

## Testing

```bash
make test               # or: pytest
```

The tests in `tests_py/` build hubs, run `optimize()`, and compare each car's current with hand-computed values. Some tests also compare against an independent brute-force search over every on/off combination of the cars.

## Development

| Command | What it does |
|---|---|
| `make format` | Sort imports and format the code with ruff (rewrites files). |
| `make lint` | Report lint issues. |
| `make check` | Check formatting and lint without changing files. |
| `make test` | Run the test suite. |

Ruff is configured in `pyproject.toml`: 88-character lines, with pyflakes, pycodestyle and import-sorting rules.

GitHub Actions ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs `make check` and `make test` on every pull request and on every push to `main`. A failing check fails the run. CI never reformats code, so run `make format` before pushing.

## The problem

A charging hub distributes power from the grid to cars through a tree:

```
                Meter 1 (250 A)
               /               \
      Meter 2 (150 A)       Meter 3 (200 A)
      10 stations           /             \
                     Meter 4 (100 A)   Meter 5 (150 A)
                     5 stations        10 stations
```

- **Meters** have a capacity in amps. The current flowing through a meter, which is the sum over all stations below it, must not exceed that capacity. A meter feeds either child meters or charging stations, never both.
- **Charging stations** deliver either **0 A** (off) or a current between a **minimum and maximum** (6 A to 15 A in the examples). A station can't charge below its minimum.
- **Cars** are connected to at most one station each and have a **priority** from 1 (highest) to 10 (lowest).

**Goal:** choose a current for every car that respects every meter's capacity and every station's limits, while serving priorities in strict order. Priority 1 cars get as much current as possible. Then, without reducing that, priority 2 cars get as much as possible, and so on down to priority 10.

The 0-or-at-least-6 A rule makes this more than a simple flow problem. When capacity is tight, a lower-priority car may be switched off completely, because giving it less than the minimum isn't allowed.

## The approach

This is a lexicographic (strict priority) optimization: maximize each priority level in turn, never at the expense of a higher one. It's solved with one MILP per priority level, using the CBC solver through OR-Tools ([charging_hub_optimization/optimizer.py](charging_hub_optimization/optimizer.py)).

### Model for one priority level $p$

Only cars with priority $\le p$ are included. Meters and stations with no included car below them are left out of the model.

**Variables**

- $x_c \in \{0, 1\}$: whether car $c$ is charging.
- $i_c \in [0, I^{max}_c]$: current delivered to car $c$.
- One current variable per station and per meter (incoming and outgoing), to model the flow through the tree.

**Constraints**

- **Station limits (on/off):** $I^{min}_c \cdot x_c \le i_c \le I^{max}_c \cdot x_c$. A car is either off ($i_c = 0$) or charging within its station's range.
- **Flow conservation:** a meter's outgoing current equals the sum of its children's incoming currents (or of its stations' currents). For non-root meters, outgoing current equals incoming current.
- **Meter capacity:** every meter current variable is bounded by that meter's capacity.
- **Keep earlier results:** for every level $q < p$ already solved with optimal total $T_q$:

  $$\sum_{c \,:\, \text{priority}(c) \le q} i_c \;\ge\; T_q$$

**Objective:** maximize $\sum_{c \,:\, \text{priority}(c) \le p} i_c$.

### Iteration

```
for p in 1..10:
    solve the MILP for level p, constrained by T_1 .. T_{p-1}
    T_p = optimal total current for cars with priority <= p
return the allocation from the last solve (p = 10)
```

The earlier results are kept as constraints on **totals**, not on each car's individual value. This leaves the solver free to rearrange current between higher-priority cars, if that frees capacity for lower-priority ones without reducing any higher level's total.

### Example

On the example hub, capacity isn't a bottleneck, so all 7 cars get 15 A. If Meter 4's capacity is reduced to 20 A, its two cars compete:

- `car_3` (priority 7) is solved first and gets 15 A.
- `car_4` (priority 9) has only 5 A left, which is below the 6 A minimum, so it's switched off (0 A).

All other cars still get 15 A.

## Project structure

```
charging_hub_optimization/
    datamodel.py      Meter, ChargingStation, Car, ChargingHub, plus consistency checks and DOT export
    optimizer.py      optimize(): lexicographic MILP with OR-Tools
examples/             Scripts that build the example hub and write diagrams to tmp/
tests_py/             Unit tests (pytest / unittest)
.github/workflows/    CI: format check, lint and tests
Makefile              install / format / lint / check / test
pyproject.toml        Package metadata, dependencies, and pytest/ruff configuration
```

## License

[MIT](LICENSE)
