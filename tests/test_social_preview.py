"""The social preview card carries no result value, and it is the size GitHub expects."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.text import Text
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("make_social_preview", ROOT / "scripts" / "make_social_preview.py")
assert _spec is not None and _spec.loader is not None
msp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(msp)


def _results() -> dict[str, Any]:
    t = np.arange(0.0, 30.5, 0.5)
    series = {
        "t": t.tolist(),
        "position_error_m": (0.4 * t).tolist(),
        "claimed_sigma_p_m": [0.3] * len(t),
    }
    case = {
        "name": "outage_visual",
        "error_time_series": series,
        "outages": [{"start_s": 5.0, "end_s": 20.0}],
        "headline": {"ate_rmse_m": 2.541, "claimed_sigma_p_m": 0.161, "coverage": {"2sigma": 0.2}},
    }
    return {"cases": [case]}


def test_no_text_other_than_tick_labels_contains_a_digit() -> None:
    fig = msp.build_figure(_results())
    try:
        fig.canvas.draw()
        ticks = {
            id(label)
            for ax in fig.axes
            for axis in (ax.xaxis, ax.yaxis)
            for tick in (*axis.majorTicks, *axis.minorTicks)
            for label in (tick.label1, tick.label2)
        }
        texts = [x for x in fig.findobj(Text) if id(x) not in ticks and x.get_text()]
        assert any("contested-nav" in x.get_text() for x in texts)
        offenders = [x.get_text() for x in texts if re.search(r"\d", x.get_text())]
        assert offenders == []
    finally:
        plt.close(fig)


def test_saved_card_is_1280_by_640(tmp_path: Path) -> None:
    out = msp.render(_results(), tmp_path / "card.png")
    with Image.open(out) as im:
        assert im.size == (1280, 640)
