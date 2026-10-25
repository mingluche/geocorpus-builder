"""Regenerate Figure 1 and Figure S1 from the archived controlled table."""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle

def figures(controlled_path=None, output_dir=None):
    plt.rcParams.update({"font.family": "Times New Roman", "font.size": 10,
                         "svg.fonttype": "none", "pdf.fonttype": 42,
                         "axes.unicode_minus": False})
    out = Path(output_dir) if output_dir else HERE / "figures"
    out.mkdir(parents=True, exist_ok=True)
    frame = pd.read_csv(controlled_path or AUDIT / "controlled_six_stats_recheck.csv")
    variants = ["positive_no_nodata", "all_zero_no_nodata", "signed_zero_no_nodata",
                "nan_no_nodata", "float32_precision", "nan_declared_nodata",
                "sentinel_declared_nodata", "sentinel_explicit_override", "signed_nan_sentinel"]
    names = ["Positive values; NoData unset", "All zeros; NoData unset",
             "Signed values and zero; NoData unset", "NaN values; NoData unset",
             "Float32 precision control", "NaN declared as NoData",
             "Sentinel declared as NoData", "Explicit NoData override", "Signed values with NoData"]
    stats = ["mean", "median", "std", "min", "max", "count"]
    agg = frame.groupby(["variant", "statistic"])["paper_tolerance_pass"].sum()
    a = np.array([[int(agg.loc[v, s]) for s in stats] for v in variants])
    fig, ax = plt.subplots(figsize=(8.4, 4.6))
    ax.imshow(a, cmap=matplotlib.colors.LinearSegmentedColormap.from_list(
        "pass", ["#e5b4a3", "#f4f4f4", "#b8d2cc"]), vmin=0, vmax=8, aspect="auto")
    ax.set_xticks(range(6), ["Mean", "Median", "SD", "Minimum", "Maximum", "Count"])
    ax.set_yticks(range(9), names)
    ax.tick_params(length=0, pad=7)
    for i in range(9):
        for j in range(6):
            ax.text(j, i, f"{a[i,j]}/8", ha="center", va="center", fontsize=10)
    ax.set_xticks(np.arange(-.5, 6, 1), minor=True)
    ax.set_yticks(np.arange(-.5, 9, 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=2)
    ax.tick_params(which="minor", bottom=False, left=False)
    for sp in ax.spines.values():
        sp.set_visible(False)
    fig.subplots_adjust(left=.42, right=.985, bottom=.11, top=.985)
    for ext in ["png", "pdf", "svg"]:
        fig.savefig(out / f"FigS1_controlled_statistics.{ext}", dpi=400)
    plt.close(fig)
    # Abstract processing stages, not a claim that all routes call one function.
    fig, ax = plt.subplots(figsize=(10.4, 4.4))
    ax.set(xlim=(0, 104), ylim=(0, 44))
    ax.axis("off")
    def box(x, y, w, h, text, color="#f3f5f5", size=10):
        ax.add_patch(Rectangle((x,y),w,h,facecolor=color,edgecolor="#596368",lw=.8))
        ax.text(x+w/2,y+h/2,text,ha="center",va="center",fontsize=size)
    def arrow(a,b):
        ax.add_patch(FancyArrowPatch(a,b,arrowstyle="-|>",mutation_scale=9,
                                     linewidth=.85,color="#596368"))
    for y, label, process in [(29,"Vector attributes","Attribute extraction"),
                               (17,"Numeric rasters and zones","Zonal statistics"),
                               (5,"CSV or Parquet statistics","Table parsing")]:
        box(1,y,22,8,label)
        box(28,y,21,8,process)
        arrow((23,y+4),(28,y+4))
        arrow((49,y+4),(56,21))
    box(56,12,19,18,"Record organization\n\nObject and variable\nStatistic and value\nContext and source", "#e7efed",9.5)
    arrow((75,21),(80,21))
    box(80,15,23,12,"Rules and templates\n\nQuantitative statements", "#edf0f4",10)
    box(56,34,47,7,"Project configuration and expression rules", "#f3f3f3")
    arrow((65.5,34),(65.5,30))
    arrow((91.5,34),(91.5,27))
    box(79,1,24,8,"Corpus records + evidence records", "#ffffff",9)
    arrow((91.5,15),(91.5,9))
    fig.subplots_adjust(left=.01,right=.99,bottom=.01,top=.99)
    for ext in ["png", "pdf", "svg"]:
        fig.savefig(out / f"Fig01_reproducible_workflow.{ext}", dpi=400)
    plt.close(fig)
    if output_dir is None:
        for path in out.iterdir():
            copy(path, REPO / "reproducibility/figures" / path.name)

if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--controlled",type=Path,default=Path(__file__).parent/"controlled_six_stats_recheck.csv")
    parser.add_argument("--output",type=Path,default=Path("regenerated_figures"))
    args=parser.parse_args()
    figures(args.controlled,args.output)
