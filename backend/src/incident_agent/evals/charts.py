"""Charts of the results report (matplotlib, PNG)."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from incident_agent.evals.aggregate import Aggregate, Rate

PALETTE = ["#1b6ca8", "#d95f02", "#4d9a4d", "#7570b3", "#8a8a8a"]
GRID = "#e5e5e5"


def _style(ax: Axes) -> None:
    ax.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


def _err(rate: Rate) -> tuple[float, float]:
    if rate.value is None or rate.lo is None or rate.hi is None:
        return 0.0, 0.0
    return rate.value - rate.lo, rate.hi - rate.value


def _save(fig: Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, facecolor="white", dpi=140)
    plt.close(fig)


def accuracy_by_kind(by_run: dict[str, dict[str, Aggregate]], path: Path) -> None:
    """Share of cases with a lenient root-cause match per scenario kind, with 95% intervals."""
    kinds = sorted({k for groups in by_run.values() for k in groups})
    runs = list(by_run)
    height = 0.8 / max(len(runs), 1)
    fig, ax = plt.subplots(figsize=(8, 0.55 * len(kinds) * max(len(runs), 1) ** 0.5 + 1.9), dpi=140)
    labelled: set[str] = set()
    for i, run in enumerate(runs):
        for j, kind in enumerate(kinds):
            agg = by_run[run].get(kind)
            if agg is None or agg.rca_lenient.value is None:
                continue
            y = j + (i - (len(runs) - 1) / 2) * height
            lo, hi = _err(agg.rca_lenient)
            ax.barh(
                y,
                agg.rca_lenient.value,
                height=height * 0.9,
                color=PALETTE[i % len(PALETTE)],
                xerr=[[lo], [hi]],
                error_kw={"ecolor": "#333333", "lw": 1.1, "capsize": 3},
                label=run if run not in labelled else None,
            )
            labelled.add(run)
            ax.text(1.02, y, f"{agg.rca_lenient.k}/{agg.rca_lenient.n}", va="center", fontsize=8)
    ax.set_yticks(range(len(kinds)))
    ax.set_yticklabels(kinds)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.12)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_xlabel("share of cases with the root cause found (verdict, category and node)")
    ax.set_title("Root-cause accuracy by scenario kind (bars: 95% Wilson interval)", loc="left")
    _style(ax)
    ax.legend(frameon=False, loc="lower left", fontsize=8)
    _save(fig, path)


def calibration(by_run: dict[str, Aggregate], path: Path) -> None:
    """Accuracy at each stated confidence level."""
    levels = ["low", "medium", "high"]
    runs = list(by_run)
    width = 0.8 / max(len(runs), 1)
    fig, ax = plt.subplots(figsize=(7, 4.2), dpi=140)
    labelled: set[str] = set()
    for i, run in enumerate(runs):
        rows = {r.confidence: r.accuracy for r in by_run[run].calibration}
        for j, level in enumerate(levels):
            acc = rows.get(level)
            x = j + (i - (len(runs) - 1) / 2) * width
            if acc is None or acc.value is None:
                ax.text(x, 0.02, "no cases", ha="center", fontsize=7, color="#777777")
                continue
            lo, hi = _err(acc)
            ax.bar(
                x,
                acc.value,
                width=width * 0.9,
                color=PALETTE[i % len(PALETTE)],
                yerr=[[lo], [hi]],
                error_kw={"ecolor": "#333333", "lw": 1.1, "capsize": 3},
                label=run if run not in labelled else None,
            )
            labelled.add(run)
            ax.text(x, min(acc.hi or 1.0, 1.0) + 0.03, f"n={acc.n}", ha="center", fontsize=8)
    ax.set_xticks(range(len(levels)))
    ax.set_xticklabels([f"{lv} confidence" for lv in levels])
    ax.set_ylim(0, 1.15)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_ylabel("share of reports with the root cause found")
    ax.set_title("Calibration: accuracy at each stated confidence", loc="left")
    _style(ax)
    ax.legend(frameon=False, loc="lower right", fontsize=8)
    _save(fig, path)


def token_distribution(tokens: dict[str, list[float]], path: Path) -> None:
    """Input plus output tokens of each investigation."""
    runs = [r for r, v in tokens.items() if v]
    fig, ax = plt.subplots(figsize=(8, 0.9 * len(runs) + 1.8), dpi=140)
    data = [tokens[r] for r in runs]
    ax.boxplot(
        data,
        orientation="horizontal",
        tick_labels=runs,
        widths=0.5,
        showfliers=False,
        medianprops={"color": "#d95f02", "lw": 2},
    )
    for i, values in enumerate(data, start=1):
        spread = [i + ((k * 37) % 21 - 10) / 60 for k in range(len(values))]
        ax.scatter(
            values, spread, s=14, color=PALETTE[(i - 1) % len(PALETTE)], alpha=0.75, zorder=3
        )
    ax.invert_yaxis()
    ax.set_xlabel("tokens per investigation (input + output)")
    ax.set_title("Tokens per investigation (box: quartiles, line: median, dots: cases)", loc="left")
    _style(ax)
    _save(fig, path)
