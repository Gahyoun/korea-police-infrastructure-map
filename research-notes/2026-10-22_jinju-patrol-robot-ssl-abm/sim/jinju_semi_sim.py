#!/usr/bin/env python3
"""경남 진주시 한정: 도심 안전지수(USG) 타당성 점검 + 무인순찰로봇 세미 시뮬레이션.

입력은 레포에 공개된 영남권 산출물(yeongnam/assets)뿐이다.
  tiles/*.json  : [lon1, lat1, lon2, lat2, safety, is_major]  (10m 도로 구간)
  points/*.json : [lon, lat, type(0=CCTV,1=비상벨), count]
  stations.json : [lon, lat, 관서명, 유형, 시도, 시군구]

원 파이프라인의 구성요소(visits_year, access_s, facility_count, 100m 인구)는 공개본에
없으므로 아래 가정으로 재구성한다(보고서 2.3절).
  A  = clip(1 - t/T_REF, 0, 1)            t: 최근접 관서 네트워크 도달시간
  F  = log1p(c)/log1p(C_REF)              c: 반경 R_FAC 안 CCTV·비상벨 수
  P  = clip((S/100 - 0.3A - 0.2F)/0.5)    역산한 순찰존재(presence)
  v  = (1+V_REF)^P - 1                    P = log1p(v)/log1p(V_REF) 의 역함수
  D  = 세부길 밀도 커널(인구 수요 대리변수)

실행: python3 jinju_semi_sim.py  (레포 루트 기준 상대경로 자동 탐색)
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree
from scipy.stats import spearmanr

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OUT = HERE.parent / "results"
ASSETS = REPO / "yeongnam" / "assets"

# ── 파라미터 ──────────────────────────────────────────────
G, LON0, LAT0 = 0.02, 124.0, 33.0          # 영남권 타일 격자(manifest)
BBOX = (127.86, 128.38, 35.03, 35.34)      # 진주시 외접 사각형
T_REF = 15 * 60                            # 접근성 정규화 기준 15분
R_FAC = 100.0                              # 시설 집계 반경(m)
V_REF_SET = (2920, 8760, 29200)            # presence 로그정규화 기준(연간 방문)
V_REF = 8760                               # 기본: 365일 × 8슬롯 × 3회
V_CAR, V_CAR_MAJOR = 30 / 3.6, 45 / 3.6    # 순찰차 속도(m/s)
V_ROBOT = 4 / 3.6                          # 로봇 보행속도 4km/h
SESS_PER_DAY = 2                           # 하루 2회(야간 집중) 순찰
TETHER = 600.0                             # 로봇 활동반경(기지 기준, m)
SITE_SEP = 900.0                           # 로봇 기지 간 최소 간격(m)
N_SET = (0, 5, 10, 20, 40)
T_SET = (30, 60, 120, 180, 240)            # 1회 순찰시간(분)
SEEDS = 10
KLAT = 110_950.0
KLON = 111_320.0 * np.cos(np.radians(35.18))


def to_xy(lon, lat):
    return np.c_[(lon - LON0) * KLON, (lat - LAT0) * KLAT]


def load():
    st = json.load(open(ASSETS / "stations.json", encoding="utf-8"))
    sxy = to_xy(np.array([s[0] for s in st]), np.array([s[1] for s in st]))
    is_j = np.array([s[5] == "진주시" for s in st])
    E, P = [], []
    for ix in range(int((BBOX[0] - LON0) / G), int((BBOX[1] - LON0) / G) + 1):
        for iy in range(int((BBOX[2] - LAT0) / G), int((BBOX[3] - LAT0) / G) + 1):
            for sub, acc in (("tiles", E), ("points", P)):
                f = ASSETS / sub / f"{ix}_{iy}.json"
                if f.exists():
                    acc += json.load(open(f))
    E, P = np.array(E, float), np.array(P, float)
    mid = to_xy((E[:, 0] + E[:, 2]) / 2, (E[:, 1] + E[:, 3]) / 2)
    _, nn = cKDTree(sxy).query(mid)
    keep = is_j[nn]   # 보로노이(최근접 관서) 기준 진주시 관할
    E, nn = E[keep], nn[keep]
    jst = [(i, st[i]) for i in np.where(is_j)[0]]
    return E, P, st, sxy, nn, jst


def build_graph(E):
    a, b = to_xy(E[:, 0], E[:, 1]), to_xy(E[:, 2], E[:, 3])
    key = np.round(np.r_[a, b], 0)          # 1m 격자로 노드 병합
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    u, v = inv[: len(E)], inv[len(E):]
    L = np.maximum(np.hypot(*(a - b).T), 1.0)
    return uniq, u, v, L


def main():
    OUT.mkdir(exist_ok=True)
    E, Pts, st, sxy, nn, jst = load()
    S, major = E[:, 4], E[:, 5].astype(bool)
    nodes, u, v, L = build_graph(E)
    n, m = len(nodes), len(E)
    mid = (nodes[u] + nodes[v]) / 2
    print(f"진주 도로구간 {m:,} · 노드 {n:,} · 관서 {len(jst)}")

    # ── 1) 구성요소 재구성 ──────────────────────────────
    tt = L / np.where(major, V_CAR_MAJOR, V_CAR)
    W = csr_matrix((np.r_[tt, tt], (np.r_[u, v], np.r_[v, u])), shape=(n, n))
    ntree = cKDTree(nodes)
    src = ntree.query(sxy[[i for i, _ in jst]])[1]
    t_node = dijkstra(W, indices=src, min_only=True)
    t_edge = np.minimum(t_node[u], t_node[v])
    t_edge[~np.isfinite(t_edge)] = 3 * T_REF
    A = np.clip(1 - t_edge / T_REF, 0, 1)

    pxy = to_xy(Pts[:, 0], Pts[:, 1])
    ptree = cKDTree(pxy)
    cnt = np.array([Pts[ix, 3].sum() for ix in ptree.query_ball_point(mid, R_FAC)])
    C_REF = max(np.percentile(cnt, 99), 1)
    F = np.clip(np.log1p(cnt) / np.log1p(C_REF), 0, 1)

    raw = (S / 100 - 0.3 * A - 0.2 * F) / 0.5
    Pn = np.clip(raw, 0, 1)
    clip_lo, clip_hi = (raw < 0).mean(), (raw > 1).mean()

    # 수요 대리변수: 세부길(비주요) 밀도 커널, 반경 250m
    minor_mid = mid[~major]
    dens = np.array([len(x) for x in cKDTree(minor_mid).query_ball_point(mid, 250.0)], float)
    D = dens / np.percentile(dens, 99)
    D = np.clip(D, 0, 1)
    B = D * (100 - S) / 100   # BlindspotPriority 식 그대로

    # ── 2) 지표 타당성 진단 ─────────────────────────────
    comp = np.c_[Pn, A, F, D, S]
    corr = spearmanr(comp).correlation
    rng = np.random.default_rng(0)
    top_base = B >= np.percentile(B, 95)
    rho, jac = [], []
    for _ in range(500):
        w = rng.dirichlet([5, 3, 2])
        Sw = 100 * (w[0] * Pn + w[1] * A + w[2] * F)
        rho.append(spearmanr(Sw[::7], S[::7]).correlation)
        Bw = D * (100 - Sw) / 100
        tw = Bw >= np.percentile(Bw, 95)
        jac.append((tw & top_base).sum() / (tw | top_base).sum())
    rho, jac = np.array(rho), np.array(jac)
    # 등가중(1/3) 및 순찰 단독 비교
    alt = {
        "equal_1/3": 100 * (Pn + A + F) / 3,
        "presence_only": 100 * Pn,
        "no_facility_0.6/0.4": 100 * (0.6 * Pn + 0.4 * A),
    }
    alt_res = {}
    for k, Sw in alt.items():
        Bw = D * (100 - Sw) / 100
        tw = Bw >= np.percentile(Bw, 95)
        alt_res[k] = dict(spearman=float(spearmanr(Sw[::7], S[::7]).correlation),
                          top5_jaccard=float((tw & top_base).sum() / (tw | top_base).sum()))
    office = {}
    for i, s in jst:
        sel = nn == i
        office[s[2]] = dict(edges=int(sel.sum()), mean_S=float(S[sel].mean()),
                            share_S_lt30=float((S[sel] < 30).mean()),
                            mean_B=float(B[sel].mean()))
    validity = dict(
        n_edges=int(m), mean_S=float(S.mean()), median_S=float(np.median(S)),
        share_S_lt30=float((S < 30).mean()), major_share=float(major.mean()),
        recon_clip_low=float(clip_lo), recon_clip_high=float(clip_hi),
        C_REF=float(C_REF), facility_zero_share=float((cnt == 0).mean()),
        access_median_min=float(np.median(t_edge) / 60),
        spearman_matrix_labels=["P", "A", "F", "D", "S"],
        spearman_matrix=np.round(corr, 3).tolist(),
        weight_mc=dict(n=500, rho_p05=float(np.percentile(rho, 5)), rho_median=float(np.median(rho)),
                       jaccard_p05=float(np.percentile(jac, 5)), jaccard_median=float(np.median(jac))),
        alternatives=alt_res, offices=office,
    )
    json.dump(validity, open(OUT / "validity.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps({k: validity[k] for k in ("mean_S", "share_S_lt30", "recon_clip_low", "recon_clip_high",
                                               "weight_mc", "alternatives")}, ensure_ascii=False, indent=1))

    # ── 3) 로봇 기지 선정: 우선도 상위 구간, 최소 간격 SITE_SEP ──
    order = np.argsort(-B)
    sites = []
    for e in order:
        p = mid[e]
        if all(np.hypot(*(p - mid[s])) >= SITE_SEP for s in sites):
            sites.append(e)
        if len(sites) == max(N_SET):
            break
    site_node = np.array([u[s] for s in sites])

    # ── 4) 로봇 순찰 앙상블(사이트별·T별 독립 계산 후 합성) ──
    # 인접 리스트(CSR)
    order_u = np.r_[u, v]; order_v = np.r_[v, u]; order_e = np.r_[np.arange(m), np.arange(m)]
    srt = np.argsort(order_u, kind="stable")
    nbr, eid = order_v[srt], order_e[srt]
    ptr = np.r_[0, np.cumsum(np.bincount(order_u, minlength=n))]
    attract = 0.2 + D + (1 - S / 100)        # 수요 높고 안전 낮은 구간 선호
    attract = attract * np.where(major, 0.5, 1.0)  # 큰길보다 세부길·보도 선호
    steps_per_min = V_ROBOT * 60 / 10.0     # 10m 구간 기준 분당 이동 구간수

    visit = {}   # (site_idx, T) -> 연간 방문 벡터
    for T in T_SET:
        nsteps = int(T * steps_per_min)
        for k, s0 in enumerate(site_node):
            acc = np.zeros(m)
            p0 = nodes[s0]
            for seed in range(SEEDS):
                rg = np.random.default_rng(1000 * k + seed + 7 * T)
                cur, prev_e = s0, -1
                seen = {}
                for _ in range(nsteps):
                    a, b = ptr[cur], ptr[cur + 1]
                    cand, ce = nbr[a:b], eid[a:b]
                    if len(cand) == 0:
                        break
                    d = np.hypot(*(nodes[cand] - p0).T)
                    w = attract[ce] * np.exp(-np.maximum(d - TETHER, 0) / 60.0)
                    w = w / (1.0 + np.array([seen.get(x, 0) for x in ce]))  # 재방문 회피
                    if prev_e >= 0 and len(cand) > 1:
                        w = np.where(ce == prev_e, w * 0.05, w)          # 되돌아가기 억제
                    j = rg.choice(len(cand), p=w / w.sum())
                    e = ce[j]
                    acc[e] += 1
                    seen[e] = seen.get(e, 0) + 1
                    prev_e, cur = e, cand[j]
            visit[(k, T)] = acc / SEEDS * SESS_PER_DAY * 365
        print(f"T={T}분 완료 (단계 {nsteps})")

    # ── 5) 시나리오 평가 ────────────────────────────────
    v_car = (1 + V_REF) ** Pn - 1
    dsite = cKDTree(mid[sites]).query(mid)[1]
    dnear = cKDTree(mid[sites]).query(mid)[0] <= TETHER + 200
    near_n = {N: dnear & (dsite < N) for N in N_SET}             # 배치된 N대의 영향권
    near = near_n[max(N_SET)]
    hiB = B >= np.percentile(B, 95)
    rows = []
    for vref in V_REF_SET:
        vc = (1 + vref) ** Pn - 1
        for N in N_SET:
            for T in T_SET:
                if N == 0 and T != T_SET[0]:
                    continue
                r = np.zeros(m)
                for k in range(N):
                    r += visit[(k, T)]
                P2 = np.clip(np.log1p(vc + r) / np.log1p(vref), 0, 1)
                S2 = np.clip(S + 50 * (P2 - Pn), 0, 100)
                B2 = D * (100 - S2) / 100
                rows.append(dict(
                    v_ref=vref, N=N, T=T if N else 0, robot_hours_day=N * T * SESS_PER_DAY / 60,
                    mean_S=S2.mean(), dS_city=S2.mean() - S.mean(),
                    zone_edges=int(near_n[N].sum()),
                    dS_zone=(S2[near_n[N]] - S[near_n[N]]).mean() if N else 0.0,
                    dS_demand_w=np.average(S2 - S, weights=D + 1e-9),
                    share_S_lt30=(S2 < 30).mean(),
                    blind_top5_remaining=(B2 >= np.percentile(B, 95)).sum() / hiB.sum(),
                    weekly_cov_zone=((r[near_n[N]] >= 52).mean() if N else 0.0),
                ))
    import csv
    with open(OUT / "scenarios.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(x, 5) if isinstance(x, float) else x) for k, x in r.items()})
    np.savez_compressed(OUT / "jinju_fields.npz", lon=(E[:, 0] + E[:, 2]) / 2, lat=(E[:, 1] + E[:, 3]) / 2,
                        S=S, P=Pn, A=A, F=F, D=D, B=B, major=major, near=near,
                        sites=np.array(sites), r_20_120=sum(visit[(k, 120)] for k in range(20)),
                        r_40_60=sum(visit[(k, 60)] for k in range(40)),
                        r_10_240=sum(visit[(k, 240)] for k in range(10)),
                        r_5_120=sum(visit[(k, 120)] for k in range(5)))
    json.dump([dict(rank=i + 1, lon=float((E[s, 0] + E[s, 2]) / 2), lat=float((E[s, 1] + E[s, 3]) / 2),
                    office=st[nn[s]][2], S=float(S[s]), D=float(D[s]), B=float(B[s])) for i, s in enumerate(sites)],
              open(OUT / "robot_sites.json", "w"), ensure_ascii=False, indent=1)
    print("완료:", OUT)


if __name__ == "__main__":
    sys.exit(main())
