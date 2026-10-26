#!/usr/bin/env python3
"""보고서 그림 생성. jinju_semi_sim.py → ssl_abm.py 실행 후 사용.

    python3 make_figures.py [Noto Sans KR TTF 폴더]

fig1 진주시 OSM 도로망 + 지구대·파출소 + 원 파이프라인 사각지대(레이블)
fig2 준지도학습 위험장 R + 정책별 로봇 기지
fig3 정책(HEU·SSL) × 대수 N × 1회 순찰시간 T 결과
fig4 같은 조건(10대 × 120분)에서 정책별 로봇 연간 통과 분포
"""
import csv
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import numpy as np
from matplotlib import font_manager
from matplotlib.collections import LineCollection
from matplotlib.colors import LinearSegmentedColormap, LogNorm

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
RES = HERE.parent / "results"
FIG = HERE.parent / "figures"
FONT_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else None

if FONT_DIR:
    for f in FONT_DIR.glob("*.ttf"):
        font_manager.fontManager.addfont(str(f))
    plt.rcParams["font.family"] = "Noto Sans KR"
plt.rcParams.update({"axes.unicode_minus": False, "font.size": 9, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.edgecolor": "#8a8f94", "axes.labelcolor": "#222",
                     "xtick.color": "#555", "ytick.color": "#555", "savefig.dpi": 220})

INK, INK2, MUTED = "#222222", "#52514e", "#8a8f94"
C_JIGU, C_PACH = "#0069b4", "#eb6834"      # 지구대 · 파출소
C_HEU, C_SSL = "#8a8f94", "#2a78d6"        # 휴리스틱 정책 · 준지도학습 정책
SEQ = LinearSegmentedColormap.from_list("seq", ["#e8f1fb", "#9cc2ec", "#2a78d6", "#123f7a"])
RISK = LinearSegmentedColormap.from_list("risk", ["#e9e9e6", "#f3c6a8", "#eb6834", "#a8321a"])
HALO = [pe.withStroke(linewidth=2.6, foreground="white")]

E = np.load(RES / "jinju_fields.npz")
SSL = np.load(RES / "ssl_fields.npz")
lon, lat = E["lon"], E["lat"]
st = [s for s in json.load(open(REPO / "yeongnam/assets/stations.json", encoding="utf-8")) if s[5] == "진주시"]
rows = list(csv.DictReader(open(RES / "ssl_abm_scenarios.csv", encoding="utf-8")))

# 10m 구간 양 끝점 복원
E_raw = []
G, LON0, LAT0 = 0.02, 124.0, 33.0
for ix in range(int((127.86 - LON0) / G), int((128.38 - LON0) / G) + 1):
    for iy in range(int((35.03 - LAT0) / G), int((35.34 - LAT0) / G) + 1):
        f = REPO / "yeongnam/assets/tiles" / f"{ix}_{iy}.json"
        if f.exists():
            E_raw += json.load(open(f))
E_raw = np.array(E_raw, float)
key = {(round((a + c) / 2, 6), round((b + d) / 2, 6)): i for i, (a, b, c, d, *_ ) in enumerate(E_raw)}
idx = np.array([key.get((round(x, 6), round(y, 6)), -1) for x, y in zip(lon, lat)])
seg = np.stack([E_raw[idx][:, [0, 1]], E_raw[idx][:, [2, 3]]], axis=1)
major = E["major"].astype(bool)
ASPECT = 1 / np.cos(np.radians(35.18))
LAB = SSL["pos"]
LAB_LON, LAB_LAT = lon[LAB].mean(), lat[LAB].mean()


def base_axes(ax, extent=None):
    ax.set_aspect(ASPECT)
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(True); s.set_color("#c8ccd0"); s.set_linewidth(.6)
    if extent:
        ax.set_xlim(extent[0], extent[1]); ax.set_ylim(extent[2], extent[3])


def roads(ax, minor_c="#c9cdd1", major_c="#6b7177", lw=(.25, .7)):
    ax.add_collection(LineCollection(seg[~major], colors=minor_c, linewidths=lw[0], zorder=1))
    ax.add_collection(LineCollection(seg[major], colors=major_c, linewidths=lw[1], zorder=2))


def stations(ax, labels=True, fs=8.5, offsets=None, skip=()):
    for s in st:
        jigu = s[3] == "지구대"
        ax.scatter(s[0], s[1], marker="^" if jigu else "o", s=95 if jigu else 60,
                   c=C_JIGU if jigu else C_PACH, edgecolors="white", linewidths=1.4, zorder=6)
        if labels and s[2] not in skip:
            dx, dy = (offsets or {}).get(s[2], (0.004, 0.003))
            ax.text(s[0] + dx, s[1] + dy, s[2] + s[3], fontsize=fs, color=INK, zorder=7,
                    path_effects=HALO, fontweight="bold", clip_on=True)


def label_site(ax, text=True, dx=.003, dy=-.009):
    ax.scatter(LAB_LON, LAB_LAT, marker="*", s=230, c=INK, edgecolors="white", linewidths=1.2, zorder=8)
    if text:
        ax.text(LAB_LON + dx, LAB_LAT + dy, "원 파이프라인 사각지대\n(개양 · 가좌동 대학가)", fontsize=7.6,
                color=INK, path_effects=HALO, zorder=8, clip_on=True, linespacing=1.3)


def scalebar(ax, x0, y0, km=2):
    dlon = km * 1000 / (111_320 * np.cos(np.radians(35.18)))
    ax.plot([x0, x0 + dlon], [y0, y0], color=INK, lw=2, solid_capstyle="butt", zorder=8)
    ax.text(x0 + dlon / 2, y0 + dlon * .12, f"{km} km", ha="center", fontsize=8, color=INK, path_effects=HALO, zorder=8)
    L = dlon * .45
    ax.annotate("N", xy=(x0 + dlon + L * .5, y0 + L * 1.1), xytext=(x0 + dlon + L * .5, y0), ha="center", fontsize=9,
                fontweight="bold", arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.2), color=INK)


FULL = (lon.min() - .01, lon.max() + .01, lat.min() - .008, lat.max() + .008)
CORE = (128.035, 128.185, 35.140, 35.225)
CORE_ST = {"남강", "비봉", "하대", "상대", "진양호", "개양", "충무공", "문산", "금산"}
CORE_OFF = {"남강": (-.004, .006), "비봉": (.002, .006), "하대": (.003, .004), "진양호": (.003, -.007),
            "상대": (.003, -.007), "개양": (-.026, .003), "충무공": (-.004, .006), "문산": (-.006, -.008),
            "금산": (.003, -.007)}

# ── fig1 OSM 도로망 + 관서 + 레이블 지점 ───────────────
fig, axs = plt.subplots(1, 2, figsize=(10.4, 4.6), gridspec_kw=dict(width_ratios=[1.32, 1]))
roads(axs[0]); base_axes(axs[0], FULL)
stations(axs[0], fs=8, skip=CORE_ST, offsets={"수곡": (.006, .004), "지수": (.006, .003), "일반성": (-.012, .007),
                                              "대곡": (.006, .003)})
axs[0].add_patch(plt.Rectangle((CORE[0], CORE[2]), CORE[1] - CORE[0], CORE[3] - CORE[2], fill=False,
                               ec=INK, lw=.9, ls="--", zorder=5))
axs[0].text(CORE[0] + .003, CORE[3] + .004, "(b) 도심부 · 관서 9개소", fontsize=7.5, color=INK, path_effects=HALO, zorder=7)
scalebar(axs[0], FULL[0] + .03, FULL[2] + .012, 5)
axs[0].set_title("(a) 진주시 관할 도로망과 지구대·파출소 13개소", fontsize=9.5, loc="left", color=INK)
roads(axs[1], lw=(.35, 1.0)); base_axes(axs[1], CORE)
stations(axs[1], fs=8.5, offsets=CORE_OFF)
label_site(axs[1], dx=.004, dy=-.012)
scalebar(axs[1], CORE[0] + .012, CORE[2] + .007, 1)
axs[1].set_title("(b) 도심부 확대", fontsize=9.5, loc="left", color=INK)
h = [plt.Line2D([], [], marker="^", ls="", ms=9, mfc=C_JIGU, mec="white", label="지구대 (5개소)"),
     plt.Line2D([], [], marker="o", ls="", ms=7.5, mfc=C_PACH, mec="white", label="파출소 (8개소)"),
     plt.Line2D([], [], marker="*", ls="", ms=12, mfc=INK, mec="white", label="원 파이프라인 사각지대 (레이블)"),
     plt.Line2D([], [], color="#6b7177", lw=1.4, label="주요도로 (4차선 이상)"),
     plt.Line2D([], [], color="#c9cdd1", lw=1.2, label="세부길")]
fig.legend(handles=h, loc="lower center", ncol=5, fontsize=8.2, frameon=False, bbox_to_anchor=(.5, .045))
fig.text(.01, .008, "자료: OpenStreetMap 기여자(ODbL) 도로망을 레포 파이프라인이 10m 구간으로 이산화한 영남권 타일 · 관서 좌표 stations.json · "
         "관할은 최근접 관서(보로노이) 기준. 진주경찰서 본서 좌표는 원자료에 없어 표시하지 않음.", fontsize=6.8, color=MUTED)
fig.tight_layout(rect=(0, .1, 1, 1)); fig.savefig(FIG / "fig1_jinju_osm_police.png"); plt.close(fig)

# ── fig2 준지도학습 위험장 ─────────────────────────────
R = SSL["R"]
fig, ax = plt.subplots(figsize=(7.6, 5.4))
order = np.argsort(R)
lc = LineCollection(seg[order], array=R[order], cmap=RISK, norm=plt.Normalize(0, 1),
                    linewidths=np.where(major[order], .9, .5), zorder=2)
ax.add_collection(lc); base_axes(ax, CORE)
stations(ax, labels=True, fs=8, offsets=CORE_OFF)
for s in SSL["sites_ssl"][:10]:
    ax.scatter(lon[s], lat[s], marker="D", s=34, facecolors="none", edgecolors=C_SSL, linewidths=1.5, zorder=5)
for s in SSL["sites_heu"][:10]:
    ax.scatter(lon[s], lat[s], marker="s", s=30, facecolors="none", edgecolors=INK2, linewidths=1.1, zorder=5)
label_site(ax, dx=.004, dy=-.012)
cb = fig.colorbar(lc, ax=ax, fraction=.035, pad=.01); cb.set_label("준지도학습 위험장 R (0–1)", fontsize=8.5)
cb.outline.set_visible(False)
ax.scatter([], [], marker="D", s=34, facecolors="none", edgecolors=C_SSL, linewidths=1.5, label="SSL 정책 기지 (상위 10)")
ax.scatter([], [], marker="s", s=30, facecolors="none", edgecolors=INK2, linewidths=1.1, label="휴리스틱 정책 기지 (상위 10)")
ax.legend(loc="lower right", fontsize=8, frameon=True, edgecolor="#d7d7d7")
scalebar(ax, CORE[0] + .008, CORE[2] + .007, 1)
ax.set_title("진주 도심부 준지도학습 위험장과 정책별 로봇 기지", fontsize=10, loc="left", color=INK)
fig.tight_layout(); fig.savefig(FIG / "fig2_ssl_risk.png"); plt.close(fig)

# ── fig3 정책 × N × T ─────────────────────────────────
Ns, Ts = [5, 10, 20], [60, 120, 240]
get = lambda pol, n, t, k: float(next(r[k] for r in rows if r["policy"] == pol and int(r["N"]) == n and int(r["T"]) == t))
fig, axs = plt.subplots(2, 3, figsize=(10, 5.4), sharey="row")
for j, t in enumerate(Ts):
    for i, (metric, ylab, scale) in enumerate((("weekly_cov_topR", "위험 상위 5% 구간 중\n주 1회 이상 통과 (%)", 100),
                                               ("label_visits_year", "사각지대 레이블 구간\n연간 로봇 통과 (회)", 1))):
        ax = axs[i, j]
        for pol, c, mk, ls in (("HEU", C_HEU, "s", "--"), ("SSL", C_SSL, "D", "-")):
            ys = [scale * get(pol, n, t, metric) for n in Ns]
            ax.plot(range(len(Ns)), ys, color=c, ls=ls, lw=2, marker=mk, ms=5.5, mec="white", mew=.8,
                    label="휴리스틱(HEU)" if pol == "HEU" else "준지도학습(SSL)")
            ax.text(len(Ns) - 1 + .08, ys[-1], f"{ys[-1]:.0f}", fontsize=7.5, color=INK2, va="center")
        ax.set_xticks(range(len(Ns)), [f"{n}대" for n in Ns]); ax.set_xlim(-.3, len(Ns) - .45)
        ax.grid(axis="y", color="#ececea", lw=.6); ax.set_axisbelow(True)
        if j == 0:
            ax.set_ylabel(ylab, fontsize=8.3)
        if i == 0:
            ax.set_title(f"1회 순찰시간 {t}분", fontsize=9.3, loc="left")
axs[0, 0].legend(fontsize=7.8, frameon=False, loc="upper left")
fig.tight_layout(); fig.savefig(FIG / "fig3_policy_scenarios.png"); plt.close(fig)

# ── fig4 정책별 방문장 ─────────────────────────────────
fig, axs = plt.subplots(1, 2, figsize=(10, 4.4))
SUB = (128.06, 128.135, 35.145, 35.205)
for ax, keyname, title in ((axs[0], "r_heu", "(a) 휴리스틱 정책 · 10대 × 120분"),
                           (axs[1], "r_ssl", "(b) 준지도학습 정책 · 10대 × 120분")):
    r = SSL[keyname]
    roads(ax, minor_c="#e3e5e7", major_c="#c9cdd1", lw=(.3, .6))
    on = r > 0
    lc = LineCollection(seg[on], array=r[on], cmap=SEQ, norm=LogNorm(5, 2000), linewidths=1.0, zorder=3)
    ax.add_collection(lc); base_axes(ax, SUB)
    stations(ax, labels=False)
    label_site(ax, text=False)
    ax.set_title(title, fontsize=9, loc="left")
cb = fig.colorbar(lc, ax=axs, fraction=.025, pad=.01); cb.set_label("로봇 연간 통과 횟수 (로그)", fontsize=8.5)
cb.outline.set_visible(False)
fig.savefig(FIG / "fig4_policy_visits.png", bbox_inches="tight"); plt.close(fig)
print("figures ->", FIG)
