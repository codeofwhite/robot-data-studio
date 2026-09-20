"""Versioned tabletop task definitions; no simulation work at import time."""
import importlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TASKS = ('edge_retrieve_spread', 'directed_flatten', 'translate_rotate_align', 'unfold_corner')


def catalog():
    return json.loads((ROOT / 'catalog.json').read_text())


def execute(task, robot, recorder, planner):
    if task not in TASKS:
        raise ValueError('Unknown tabletop task: ' + task)
    return importlib.import_module('tabletop_v2.' + task).execute(robot, recorder, planner)
