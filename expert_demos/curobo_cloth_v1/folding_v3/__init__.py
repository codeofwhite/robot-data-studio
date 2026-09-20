"""Second batch: folding, retained transfer, garment turnover and eversion."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS = ('unfold_half', 'towel_half_fold', 'folded_transfer', 'garment_flip', 'garment_inside_out')

def catalog():
    return json.loads((HERE / 'catalog.json').read_text())
