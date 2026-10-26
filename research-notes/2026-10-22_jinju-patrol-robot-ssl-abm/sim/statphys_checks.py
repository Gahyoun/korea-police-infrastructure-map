#!/usr/bin/env python3
"""통계물리 관점 점검(ssl_abm.py 실행 후).

1) 위험장 R의 포화(이분화) 정도
2) 그래프 분해: 도로망만 / 특징 kNN만으로 전파한 R과 전체 R의 순위 상관
3) 단일 로봇 고유 방문 구간 수 S(t)의 스케일링 S(t) ~ t^θ
4) 무작위 기지 null model 대비 SSL 정책의 z-score (N=10, T=120)
"""
import json
import sys
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix, diags
from scipy.spatial import cKDTree
from scipy.stats import spearmanr

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import jinju_semi_sim as base  # noqa: E402
import ssl_abm as sa  # noqa: E402

OUT = HERE.parent / "results"


def main():
    E, Pts, st, sxy, nn, jst = base.load()
    nodes, u, v, L = base.build_graph(E)
    n, m = len(nodes), len(E)
    mid = (nodes[u] + nodes[v]) / 2
    Fz = np.load(OUT / "jinju_fields.npz")
    S, P, A, F, D = (Fz[k] for k in "SPAFD")
    major = Fz["major"].astype(bool)
    Z = np.load(OUT / "ssl_fields.npz")
    R, pos = Z["R"], Z["pos"]
    res = {}

    # 1) 포화
    res["R_frac_gt_0.99"] = float((R > .99).mean())
    res["R_frac_gt_0.5"] = float((R > .5).mean())
    res["R_frac_lt_0.01"] = float((R < .01).mean())

    # 2) 그래프 분해
    X = np.c_[S / 100, P, A, F, D]
    X = (X - X.mean(0)) / X.std(0)
    inc = csr_matrix((np.ones(2 * m), (np.r_[u, v], np.r_[np.arange(m), np.arange(m)])), shape=(n, m))
    adj = (inc.T @ inc).tocoo()
    k = adj.row != adj.col
    road = (adj.row[k], adj.col[k])
    _, kn = cKDTree(X).query(X, k=sa.K_FEAT + 1)
    feat = (np.repeat(np.arange(m), sa.K_FEAT), kn[:, 1:].ravel())
    rng = np.random.default_rng(42)
    neg = rng.choice(np.where((S >= 65) & (F > 0))[0], sa.NEG_PER_POS * len(pos), replace=False)

    def prop(pairs):
        ri, ci = np.r_[tuple(p[0] for p in pairs)], np.r_[tuple(p[1] for p in pairs)]
        w = np.exp(-((X[ri] - X[ci]) ** 2).sum(1) / sa.SIGMA2)
        W = csr_matrix((w, (ri, ci)), shape=(m, m))
        W = W.maximum(W.T)
        d = np.asarray(W.sum(1)).ravel()
        Dm = diags(1 / np.sqrt(d + 1e-12))
        Sg = Dm @ W @ Dm
        Y = np.zeros((m, 2)); Y[neg, 0] = 1; Y[pos, 1] = 1
        Fm = Y.copy()
        for _ in range(sa.PROP_ITER):
            Fm = sa.ALPHA * (Sg @ Fm) + (1 - sa.ALPHA) * Y
        q = Fm / (Fm.sum(0, keepdims=True) + 1e-12)
        r = q[:, 1] / (q.sum(1) + 1e-12)
        return r, (Fm.sum(1) > 1e-12)

    r_road, reach_road = prop([road])
    r_feat, _ = prop([feat])
    dist = np.hypot(*(mid - mid[pos].mean(0)).T)
    res["road_only_reach_frac"] = float(reach_road.mean())
    res["road_only_reach_p95_dist_m"] = float(np.percentile(dist[r_road > 1e-6], 95)) if (r_road > 1e-6).any() else 0.0
    res["spearman_R_vs_road_only"] = float(spearmanr(R[::5], r_road[::5]).correlation)
    res["spearman_R_vs_feat_only"] = float(spearmanr(R[::5], r_feat[::5]).correlation)
    res["top5_overlap_R_feat_only"] = float(((R >= np.percentile(R, 95)) & (r_feat >= np.percentile(r_feat, 95))).mean() / .05)
    # 랜덤워크-재시작 해석: 재시작 전 평균 걸음 α/(1-α)
    res["rwr_mean_steps"] = sa.ALPHA / (1 - sa.ALPHA)

    # 공통: 인접 리스트
    ou, ov, oe = np.r_[u, v], np.r_[v, u], np.r_[np.arange(m), np.arange(m)]
    srt = np.argsort(ou, kind="stable")
    nbr, eid = ov[srt], oe[srt]
    ptr = np.r_[0, np.cumsum(np.bincount(ou, minlength=n))]
    att_ssl = (0.2 + 2.0 * R) * np.where(major, 0.5, 1.0)

    # 3) S(t) 스케일링: SSL 기지 1–5, 시드 5, 1600걸음
    curves = []
    for s0 in Z["sites_ssl"][:5]:
        for seed in range(5):
            rg = np.random.default_rng(seed)
            cur, prev_e, seen, p0, St = u[s0], -1, {}, nodes[u[s0]], []
            for t in range(1600):
                a, b = ptr[cur], ptr[cur + 1]
                cand, ce = nbr[a:b], eid[a:b]
                d = np.hypot(*(nodes[cand] - p0).T)
                w = att_ssl[ce] * np.exp(-np.maximum(d - base.TETHER, 0) / 60.0)
                w = w / (1.0 + np.array([seen.get(x, 0) for x in ce]))
                if prev_e >= 0 and len(cand) > 1:
                    w = np.where(ce == prev_e, w * 0.05, w)
                j = rg.choice(len(cand), p=w / w.sum())
                e = ce[j]; seen[e] = seen.get(e, 0) + 1; prev_e, cur = e, cand[j]
                St.append(len(seen))
            curves.append(St)
    Sm = np.mean(curves, 0)
    t = np.arange(1, 1601)
    for lo, hi in ((10, 100), (100, 400), (400, 1600)):
        sel = (t >= lo) & (t <= hi)
        res[f"theta_{lo}_{hi}"] = float(np.polyfit(np.log(t[sel]), np.log(Sm[sel]), 1)[0])
    res["S_t_at"] = {str(x): float(Sm[x - 1]) for x in (100, 400, 800, 1600)}
    seg_in_tether = [int((np.hypot(*(mid - nodes[u[s]]).T) <= base.TETHER).sum()) for s in Z["sites_ssl"][:5]]
    res["segments_within_tether_mean"] = float(np.mean(seg_in_tether))

    # 4) 무작위 기지 null (N=10, T=120): 기지 = 무작위 구간(900m 간격), 이동 규칙은 SSL과 동일
    topR = R >= np.percentile(R, 95)
    T, N, reps = 120, 10, 8
    null_cov = []
    for rep in range(reps):
        rr = np.random.default_rng(100 + rep)
        sites = sa.pick_sites(rr.random(m), mid, N)
        r = sum(sa.walk_visits(u[s], nodes, nbr, eid, ptr, att_ssl, T, m, 5000 + 31 * rep + k)
                for k, s in enumerate(sites))
        null_cov.append(float((r[topR] >= 52).mean()))
    obs = 0.461  # ssl_abm_scenarios.csv: SSL N=10 T=120
    res["null_random_sites_cov_mean"] = float(np.mean(null_cov))
    res["null_random_sites_cov_sd"] = float(np.std(null_cov, ddof=1))
    res["z_ssl_vs_random_sites"] = float((obs - np.mean(null_cov)) / np.std(null_cov, ddof=1))
    json.dump(res, open(OUT / "statphys_checks.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
