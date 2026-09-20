"""Versioned tabletop task definitions; no simulation work at import time."""
import importlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TASKS = ('hang_on_rod', 'retrieve_from_rod', 'place_in_basket', 'retrieve_from_basket', 'cover_box')


def catalog():
    return json.loads((ROOT / 'catalog.json').read_text())


def execute(task, robot, recorder, planner):
    if task not in TASKS:
        raise ValueError('Unknown tabletop task: ' + task)
    return importlib.import_module('fixtures_v4.' + task).execute(robot, recorder, planner)
