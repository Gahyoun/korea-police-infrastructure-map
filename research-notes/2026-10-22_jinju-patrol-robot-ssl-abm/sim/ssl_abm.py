#!/usr/bin/env python3
"""준지도학습(semi-supervised) 위험장 기반 무인순찰로봇 ABM — 진주시.

jinju_semi_sim.py 실행 후 사용한다(results/jinju_fields.npz 필요).

1) 레이블: 원 파이프라인(SGIS 100m 실제 인구)이 진주에서 지정한 사각지대 구간(blindspots.json)을
   양성(1), 보호가 두터운 구간(S ≥ 65, 반경 100m 시설 ≥ 1)에서 뽑은 표본을 음성(0)으로 둔다.
   나머지 11만여 구간은 레이블 없음(−1).
2) 모델: 도로망 인접 + 특징공간 kNN 그래프 위 레이블 전파(Zhou 외, 2004).
   음성 표본을 20회 다시 뽑아 평균·표준편차를 낸다(레이블 불확실성).
3) ABM: 로봇 에이전트의 기지 선정·이동 선호를 SSL 위험장 R로 바꾼 정책(SSL)과
   기존 휴리스틱 정책(HEU: 대리수요 우선도 B)을 같은 N·T에서 비교한다.
"""
import csv
import json
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree
from scipy.sparse import csr_matrix, diags

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import jinju_semi_sim as base  # noqa: E402

OUT = HERE.parent / "results"
N_SET, T_SET, SEEDS = (5, 10, 20), (60, 120, 240), 10
NEG_PER_POS, BOOT = 10, 20
ALPHA, PROP_ITER, K_FEAT, SIGMA2 = 0.95, 300, 8, 1.0   # 전파 강도, 반복 수, 특징공간 이웃 수, 커널 폭


def walk_visits(site_node, nodes, nbr, eid, ptr, attract, T, m, seed0):
    """기지에서 출발하는 반경 제약 비역행 무작위보행(jinju_semi_sim.py와 같은 규칙)."""
    nsteps = int(T * base.V_ROBOT * 60 / 10.0)
    acc = np.zeros(m)
    p0 = nodes[site_node]
    for seed in range(SEEDS):
        rg = np.random.default_rng(seed0 + seed)
        cur, prev_e, seen = site_node, -1, {}
        for _ in range(nsteps):
            a, b = ptr[cur], ptr[cur + 1]
            cand, ce = nbr[a:b], eid[a:b]
            if len(cand) == 0:
                break
            d = np.hypot(*(nodes[cand] - p0).T)
            w = attract[ce] * np.exp(-np.maximum(d - base.TETHER, 0) / 60.0)
            w = w / (1.0 + np.array([seen.get(x, 0) for x in ce]))
            if prev_e >= 0 and len(cand) > 1:
                w = np.where(ce == prev_e, w * 0.05, w)
            j = rg.choice(len(cand), p=w / w.sum())
            e = ce[j]
            acc[e] += 1
            seen[e] = seen.get(e, 0) + 1
            prev_e, cur = e, cand[j]
    return acc / SEEDS * base.SESS_PER_DAY * 365


def pick_sites(score, mid, k):
    sites = []
    for e in np.argsort(-score):
        if all(np.hypot(*(mid[e] - mid[s])) >= base.SITE_SEP for s in sites):
            sites.append(e)
        if len(sites) == k:
            break
    return sites


def main():
    E, Pts, st, sxy, nn, jst = base.load()
    nodes, u, v, L = base.build_graph(E)
    n, m = len(nodes), len(E)
    mid = (nodes[u] + nodes[v]) / 2
    F_ = np.load(OUT / "jinju_fields.npz")
    S, P, A, F, D, B = (F_[k] for k in ("S", "P", "A", "F", "D", "B"))
    major = F_["major"].astype(bool)

    # ── 1) 레이블 ───────────────────────────────────────
    bl = json.load(open(base.ASSETS / "blindspots.json", encoding="utf-8"))   # [lon, lat, S, B, demand]
    bl = np.array([x for x in bl if base.BBOX[0] < x[0] < base.BBOX[1] and base.BBOX[2] < x[1] < base.BBOX[3]])
    d_lab, pos = cKDTree(mid).query(base.to_xy(bl[:, 0], bl[:, 1]))
    pos = np.unique(pos[d_lab < 15])
    neg_pool = np.where((S >= 65) & (F > 0))[0]
    print(f"양성 레이블 {len(pos)}구간(원 파이프라인 사각지대), 음성 후보 {len(neg_pool)}구간")

    # 레이블 위치가 대리수요 우선도 B에서 몇 백분위인지(대리변수 기준타당도 점검)
    b_pct = float((B < B[pos].mean()).mean() * 100)

    # ── 2) 그래프 기반 레이블 전파(Zhou 외, 2004) ─────────
    # 그래프 = 도로망 인접(같은 노드를 공유하는 구간) ∪ 특징공간 kNN. 가중치는 특징 거리의 가우스 커널.
    X = np.c_[S / 100, P, A, F, D]
    X = (X - X.mean(0)) / X.std(0)
    inc = csr_matrix((np.ones(2 * m), (np.r_[u, v], np.r_[np.arange(m), np.arange(m)])), shape=(n, m))
    adj = (inc.T @ inc).tocoo()                              # 구간-구간 인접(line graph)
    keep = adj.row != adj.col
    ri, ci = adj.row[keep], adj.col[keep]
    _, kn = cKDTree(X).query(X, k=K_FEAT + 1)
    ri = np.r_[ri, np.repeat(np.arange(m), K_FEAT)]
    ci = np.r_[ci, kn[:, 1:].ravel()]
    d2 = ((X[ri] - X[ci]) ** 2).sum(1)
    w = np.exp(-d2 / SIGMA2)                                # 표준화 특징 1 SD 차이 → e^-1
    Wg = csr_matrix((w, (ri, ci)), shape=(m, m))
    Wg = Wg.maximum(Wg.T)
    dg = np.asarray(Wg.sum(1)).ravel()
    Dm = diags(1 / np.sqrt(dg + 1e-12))
    Sg = Dm @ Wg @ Dm

    def propagate(pos_idx, neg_idx):
        Y = np.zeros((m, 2))
        Y[neg_idx, 0] = 1
        Y[pos_idx, 1] = 1
        Fm = Y.copy()
        for _ in range(PROP_ITER):
            Fm = ALPHA * (Sg @ Fm) + (1 - ALPHA) * Y
        q = Fm / (Fm.sum(0, keepdims=True) + 1e-12)          # 클래스 질량 정규화(Zhu 외, 2003)
        return q[:, 1] / (q.sum(1) + 1e-12)

    rng = np.random.default_rng(42)
    probs = np.array([propagate(pos, rng.choice(neg_pool, NEG_PER_POS * len(pos), replace=False))
                      for _ in range(BOOT)])
    R, R_sd = probs.mean(0), probs.std(0)
    span = R.max() - R.min() + 1e-12
    R, R_sd = (R - R.min()) / span, R_sd / span
    far = np.hypot(*(mid - mid[pos].mean(0)).T) > 300
    top_R = R >= np.percentile(R, 95)
    office = {}
    for i, s in jst:
        sel = nn == i
        office[s[2]] = round(float(top_R[sel].sum() / top_R.sum()), 3)
    ssl = dict(n_pos=int(len(pos)), n_neg=int(NEG_PER_POS * len(pos)), boot=BOOT,
               label_B_percentile=b_pct, R_sd_mean=float(R_sd.mean()),
               R_label_pct=float((R < R[pos].min()).mean() * 100),
               top5_far_share=float((far & (R >= np.percentile(R, 95))).sum() / (R >= np.percentile(R, 95)).sum()),
               R_sd_top5=float(R_sd[top_R].mean()),
               spearman_R_vs_B=float(__import__("scipy.stats", fromlist=["spearmanr"]).spearmanr(R[::5], B[::5]).correlation),
               top5_overlap_R_B=float((top_R & (B >= np.percentile(B, 95))).sum() / top_R.sum()),
               top5_R_by_office=office)
    print(json.dumps(ssl, ensure_ascii=False, indent=1))

    # ── 3) ABM: HEU vs SSL 정책 ─────────────────────────
    ou, ov, oe = np.r_[u, v], np.r_[v, u], np.r_[np.arange(m), np.arange(m)]
    srt = np.argsort(ou, kind="stable")
    nbr, eid = ov[srt], oe[srt]
    ptr = np.r_[0, np.cumsum(np.bincount(ou, minlength=n))]
    policies = {
        "HEU": (B, (0.2 + D + (1 - S / 100)) * np.where(major, 0.5, 1.0)),
        "SSL": (R * (100 - S) / 100, (0.2 + 2.0 * R) * np.where(major, 0.5, 1.0)),
    }
    vref = base.V_REF
    vc = (1 + vref) ** P - 1
    rows, fields = [], {}
    for name, (score, attract) in policies.items():
        sites = pick_sites(score, mid, max(N_SET))
        cache = {(k, T): walk_visits(u[s], nodes, nbr, eid, ptr, attract, T, m, 1000 * k + 7 * T)
                 for k, s in enumerate(sites) for T in T_SET}
        fields[name] = dict(sites=sites)
        for N in N_SET:
            for T in T_SET:
                r = sum(cache[(k, T)] for k in range(N))
                P2 = np.clip(np.log1p(vc + r) / np.log1p(vref), 0, 1)
                S2 = np.clip(S + 50 * (P2 - P), 0, 100)
                rows.append(dict(policy=name, N=N, T=T, robot_hours_day=N * T * base.SESS_PER_DAY / 60,
                                 dS_city=S2.mean() - S.mean(),
                                 dS_topR=(S2 - S)[top_R].mean(),
                                 weekly_cov_topR=(r[top_R] >= 52).mean(),
                                 label_visits_year=r[pos].mean(),
                                 dS_label=(S2 - S)[pos].mean()))
                if N == 10 and T == 120:
                    fields[name]["r"] = r
        print(name, "완료")
    with open(OUT / "ssl_abm_scenarios.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(x, 5) if isinstance(x, float) else x) for k, x in r.items()})
    json.dump(ssl, open(OUT / "ssl_model.json", "w"), ensure_ascii=False, indent=1)
    np.savez_compressed(OUT / "ssl_fields.npz", R=R, R_sd=R_sd, pos=pos,
                        sites_heu=np.array(fields["HEU"]["sites"]), sites_ssl=np.array(fields["SSL"]["sites"]),
                        r_heu=fields["HEU"]["r"], r_ssl=fields["SSL"]["r"])
    print("완료")


if __name__ == "__main__":
    main()
