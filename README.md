# 전국 경찰 순찰경로 최적화 및 가상순찰(Semi-Agent-Based) 시뮬레이션
## 기술 구현 및 이론적 근거 보고서 (개정판)

---

## 0. 요약 (Executive Summary)

본 시스템은 전국 시·도 경찰 행정지점(지구대·파출소·출장소 약 2,000여 개)을 기점으로,

1. **수요·도로 기반 닫힌 순찰경로 최적화** — 100m 격자 거주·유동인구 수요와 4차선 이상
   주요도로를 반영하여, 범죄학의 **Koper Curve**(핫스팟 ~15분 체류·잔여억제)와 **핫스팟
   폴리싱**(hot spots policing) 원리에 따라 차량별 닫힌 경로를 생성한다. 차량 간 **중복
   회피(anti-convoy)** 와 **광역 분산(wide-exploration)** 을 강제한다.
2. **준-행위자기반(semi-ABM) 가상순찰** — 각 순찰차를 **자율 에이전트**로 보고, 골목 조우
   시 **0.01 확률로 진입하여 약 10분 무작위 탐색 후 복귀**하는 행동을 **시드 0–99 앙상블**로
   365일×8시간대 시뮬레이션하여 연간 순찰 방문빈도장(field)을 산출한다.
3. **복합 안전지수와 사각지대 진단** — 방문빈도·응답접근성·방범시설 커버리지를 결합한
   0–100 안전지수를 산출하고, 수요 대비 안전이 낮은 사각지대를 추출한다.
4. **뷰포트 지연로딩 웹지도** — 전국 데이터를 좌표 타일로 분할하고, 화면이 일정 시간(3초)
   정지했을 때만 보이는 영역을 로드하여 단일 전국 지도에서도 과부하 없이 탐색한다.

본 문서는 ① 지리정보과학(GIScience), ② 경찰행정·환경범죄학, ③ 복잡계 물리학의
행위자기반모형(ABM)에 근거하여 설계 결정을 설명하고, 각 에이전트의 행동을 **인공지능
(자율 에이전트) 관점**(정책·탐험/활용·창발)으로 정리한다.

---

## 1. 시스템 아키텍처

| 단계 | 산출물 | 핵심 이론/기법 | 대표 문헌 |
|---|---|---|---|
| A. 지오코딩 | 관서 좌표 | 주소→좌표, 권위 sido(경찰청명) | — |
| 1. 셀 | 파출소별 보로노이 관할(soft) | Voronoi tessellation | Okabe et al. 2000 |
| 2. 도로망 | 셀별 10m 노드링크 그래프 | OSM 네트워크 모형화 | Boeing 2017 |
| 3. 차량배분 | 시도→경찰서→파출소 계층 배분 | 자원-수요 배분(Hamilton) | Larson 1972 |
| 4. 경로 | 슬롯별 닫힌 순찰경로 | Koper·팀 오리엔티어링·CPP·anti-convoy | Koper 1995; Vansteenwegen 2011 |
| 5. ABM | 365×8 가상순찰 방문빈도 | semi-random walk + 앙상블 | Bonabeau 2002 |
| 6. 안전지수 | 구간별 복합 안전지수 0–100 | 방문·접근성·CPTED | Newman 1972 |
| 7. 웹지도 | 지연로딩 전국 안전지도 | 벡터 타일·LOD | (벡터 타일 패러다임) |

좌표계는 한국 통계·센서스 표준 **EPSG:5179(UTM-K)** 를 거리·시간 계산에, WGS84를
OSM 추출·지도 렌더링에 사용한다. 각 단계는 독립 실행·재개(resume), 시군구 단위 `--region`
디버깅, `ProcessPoolExecutor` 병렬을 지원한다.

---

## 2. 지리정보과학(GIScience) 기반

### 2.1 도로망: 10m 노드링크 그래프

도로망은 OpenStreetMap(OSM)에서 추출하여 `networkx` 그래프로 모형화한다. OSM 도로망의
취득·구성·분석 방법론은 Boeing(2017)의 **OSMnx**에 정립되어 있으며 [Boeing 2017], 본
시스템은 동일 원리를 한국 전역에 적용하되 대규모 처리를 위해 오프라인 `.pbf`(GDAL/pyrosm)
기반으로 변형하였다.

- **고속도로 제외**: `highway ∈ {motorway, trunk, …}` 배제 → 시내 순찰 도로만.
- **주요도로(4차선 이상)**: OSM `lanes ≥ 4` 를 주요도로로 정의, 태그 결측 시 도로위계
  (primary/secondary)로 보강.
- **10m densify**: 링크를 10m 간격 노드로 분할 → 미세 순찰 커버리지·방문빈도 측정 가능
  (해상도↔계산량 trade-off).
- 엣지 속성: `length_m`, `travel_time_s`(정속 30–50km/h), `highway`, `lanes`, `is_major`,
  `in_cell`(보로노이 내부 여부).

도로를 그래프로 모형화함으로써 최단경로(Dijkstra), 커버리지, 연결성(최대 연결요소) 등
**네트워크 과학**의 도구를 직접 활용한다. 특히 파출소는 **최대 연결요소**의 최근접 노드에
스냅하여, 고립된 도로 조각에 갇혀 비현실적 단경로가 생기는 문제를 방지한다.

### 2.2 관할구역: 보로노이 테셀레이션과 soft 경계

각 파출소의 1차 관할은 **보로노이 다이어그램**으로 정의한다("임의 지점은 가장 가까운
파출소 관할"). 보로노이는 공간 분할·서비스 권역의 표준 도구이며 [Okabe et al. 2000],
경찰 beat/district 설계의 **입지-배분(location-allocation)** 발상과 일치한다 [Larson 1972].

현실 순찰은 행정경계를 칼같이 지키지 않으므로, 도로망을 셀 경계 밖 **1.2km까지 버퍼(soft
boundary)** 하여 포함하고 인접 셀의 약한 침범을 허용한다. 이는 이전 연구의 *Voronoi
soft-constraint*(일부 이탈 허용, 과도 이탈 페널티)를 단순화·계승한 것이다.

### 2.3 수요 표면: 100m 격자 인구·유동인구

수요는 통계청 100m 센서스 격자 인구를 1차 신호로, 가용 지역의 **시간대별 유동인구**를
보조 배율로 사용한다. 인구 밀집 격자는 경로 최적화에서 **강한 끌개(minima)** 로 작동하도록
가중치에 거듭제곱(`γ=2.0`)을 적용한다(§4.2). 이는 도시 범죄가 소수 미시지점에 집중된다는
**범죄집중의 법칙** [Weisburd 2015]과 정합한다.

---

## 3. 경찰행정·환경범죄학 이론

### 3.1 핫스팟 폴리싱과 범죄집중

범죄는 도시 전역에 균등하지 않고 소수 미시지점(hot spots)에 집중되며, 그 지점에 순찰을
집중하면 범죄가 단순 전이(displacement)되기보다 전체적으로 감소한다. 이는 다수의 무작위
통제실험과 메타분석으로 입증되었다 [Sherman & Weisburd 1995; Braga et al. 2019]. Braga
등의 Campbell 체계적 문헌고찰·메타분석은 핫스팟 폴리싱이 처치지점에서 **통계적으로 유의한
범죄 감소(약 16%)** 를 가져옴을 보고했다 [Braga et al. 2019]. Weisburd(2015)는 도시
범죄의 약 절반이 가로구간의 약 5%에 집중된다는 **범죄집중의 법칙**을 제시했다. 본 시스템이
고수요 격자를 정차 대상으로 삼는 것은 이 경험적 토대에 근거한다.

### 3.2 Koper Curve — 최적 체류시간과 잔여 억제

Koper(1995)는 핫스팟 체류시간과 떠난 뒤의 **잔여 억제효과(residual deterrence)** 관계를
분석하여, 체류가 **약 11–15분**일 때 잔여 억제가 최대화되고 그 이상은 수확 체감함을 보였고,
핫스팟 간 이동을 **예측 불가능한 순서**로 수행할 때 억제가 강화됨을 제시했다 [Koper 1995].

본 시스템의 직접 구현:
- 각 순찰차는 슬롯(2.5–3시간)당 **고수요 핫스팟 2–3개**에 **약 15분씩 체류(dwell)**.
- 핫스팟 사이는 주요도로 위주로 **빠르게 이동**(정속 30–50km/h).
- 핫스팟은 **가까운 순서(nearest-first)** 로 방문하되, ABM에서 방문 순서·골목 이탈을
  시드별로 **확률화**하여 예측불가성을 부여한다.

### 3.3 일상활동이론·범죄패턴이론·CPTED

범죄는 동기화된 범죄자·적절한 표적·보호자 부재가 시공간적으로 수렴할 때 발생한다는
**일상활동이론** [Cohen & Felson 1979], 사람·범죄자가 도시 구조를 따라 이동하며 활동공간
주변에서 범죄가 발생한다는 **범죄패턴이론** [Brantingham & Brantingham 1993]은, (a) 시간대
유동인구로 표적·보호자 밀도를 근사하고 (b) 도로망 위에서 순찰차를 이동시키는 설계를
정당화한다. 순찰차는 "유능한 보호자(capable guardian)"의 공간적 가용성을 높이는 장치이다.
또한 안전지수의 CCTV·비상벨 항목은 **환경설계를 통한 범죄예방(CPTED)** 의 자연·기계 감시
개념에 근거한다 [Jeffery 1971; Newman 1972].

### 3.4 계층적 자원배분과 대기(standby) 원칙

상위 조직(지방청→경찰서)의 보유 순찰차 총량을 하위 관서에 **수요(인구) 비례**로 정수
배분(해밀턴 최대잔여법)한다. 이는 도시 순찰자원의 수요기반 배분을 다룬 운용연구 전통에
근거한다 [Larson 1972]. 관서별 **1대는 대기(standby)** 시키고 나머지를 동시 순찰에 투입하되,
동시 순찰차는 인구비례로 **1–3대**로 제한하고 차량당 정차 타깃을 **2–3개**로 둔다.

---

## 4. 경로 최적화 모델

### 4.1 문제의 형식화

각 (관서 × 시간대 슬롯)에 대해 파출소 노드 \(d\)를 출발·복귀점으로 하는 **닫힌 walk**
\(W\)를 \(k\)대 차량에 대해 생성한다. 도로 그래프 \(G=(V,E)\), 엣지 \(e\)의 주행시간
\(\tau_e\), 길이 \(\ell_e\), 주요도로 표시 \(m_e\in\{0,1\}\), 핫스팟 \(h\)의 수요가중 \(w_h\),
체류시간 \(\delta\)(≈15분), 슬롯 예산 \(T\)(2.5–3시간)라 할 때, 차량 \(v\)의 목적은

\[
\max_{W_v}\; \underbrace{\sum_{h\in S_v} w_h}_{\text{Koper 억제}} \;+\; \alpha\!\!\sum_{e\in W_v} m_e\,\ell_e \;-\; \beta\!\!\sum_{e\in W_v\cap W_{\neq v}} \ell_e
\]
subject to \(\sum_{e\in W_v}\tau_e + |S_v|\,\delta \le T\), \(W_v\) closed at \(d\), \(|S_v|\le 3\).

세 항은 각각 (i) 정차 핫스팟의 억제효과, (ii) 주요도로 커버리지, (iii) **차량 간 중복
패널티(anti-convoy)** 이다. 이는 운용연구의 **팀 오리엔티어링(Team Orienteering Problem)**
[Vansteenwegen et al. 2011; Gunawan et al. 2016]과 **아크 라우팅(Chinese Postman/arc routing)**
[Edmonds & Johnson 1973]의 혼합 성격을 가지며, 영역 전반을 훑는 부분은 **커버리지 경로
계획(coverage path planning)** [Galceran & Carreras 2013]과 맞닿는다.

### 4.2 수요 가중과 강한 끌개(minima)

슬롯별 핫스팟 가중치는
\[
w_h^{(s)} = (\text{pop}_h)^{\gamma}\cdot \text{regime}_h^{(s)}\cdot \text{float}^{(s)}
\]
- \(\gamma=2.0\): 고수요 격자에 경로가 강하게 끌리도록(에너지 지형의 깊은 우물).
- \(\text{regime}^{(s)}\): 핫스팟 도로환경(상업·간선 vs 주거)별 **시간대 일주기** — 낮엔
  상업·간선, 저녁·심야엔 주거 가중↑.
- \(\text{float}^{(s)}\): 시간대 유동인구 배율. **데이터가 있는 지역은 8슬롯을 각각 최적화**,
  없는 지역은 대표 1타임을 복제.

### 4.3 휴리스틱 알고리즘 (의사코드)

```
for each (office, slot):
  depot ← nearest node in largest connected component
  hotspots ← top-N 100m 격자(가까운순·고수요 우선), 차량별 sector(k-means)
  for v in 1..k:
    # (1) Koper 정차: 가까운 고수요 핫스팟 ≤3개, 각 15분 체류
    # (2) 광역 커버: 미방문 '주요도로' 우선 sweep, 막히면 가장 먼/가까운 미커버 대로 점프
    # (3) anti-convoy: 다른 차량이 지난 도로(global_covered)는 회피
    # (4) 시간 밴드: 목표 ~150분(±15) 도달까지, 최소 120분 hard-floor(부족시 재방문 허용)
    # (5) 닫힘: 항상 depot 복귀 여유 확인 → 닫힌 walk 보장 (distance>0)
    global_covered ← global_covered ∪ edges(W_v)
```

**anti-convoy / wide-exploration** 은 차량들이 전역 커버 집합을 공유하여 서로의 도로를
피하고(차량1이 지난 길을 차량2가 회피), 섹터 분할로 공간 분산하며, 부족한 차량은 더 먼
미커버 대로로 진출(셀 약간 침범)하여 광역을 훑게 한다. 이는 이전 파이프라인의 **시뮬레이티드
어닐링(SA)** [Kirkpatrick et al. 1983] 기반 anti-convoy·wide-exploration 목적함수의 핵심
동작을 경량 휴리스틱으로 이식한 것이다. 거리·시간은 EPSG:5179 거리 기반 정속 근사이다(§11).

---

## 5. 복잡계 물리학: 행위자기반모형(ABM)

### 5.1 ABM과 창발(emergence)

행위자기반모형은 단순 국지 규칙을 따르는 다수 자율 에이전트로부터 거시 패턴이 **창발**하는
것을 모사하는, 복잡계 연구의 표준 방법이다 [Bonabeau 2002; Epstein & Axtell 1996]. 치안·범죄
영역에서도 ABM은 순찰·범죄의 시공간 동학을 모사하는 데 사용되어 왔다 [Groff 2007;
Malleson, Heppenstall & See 2010; Andresen & Malleson 2015].

### 5.2 준-무작위보행(semi-random walk) 에이전트

각 순찰차는 **결정론적 주 경로(4단계)** 를 따르되, 물리학의 **네트워크 무작위보행(random
walk on networks)** [Noh & Rieger 2004] 요소를 결합한다.

- **주 경로 주행**: 매일(365일) 배정 경로 주행 → 본 경로 엣지에 연간 방문빈도 누적
  (성능상 1회에 ×days 누적).
- **골목 조우 시 확률적 진입**: 경로상에서 골목(분기·비-경로 엣지)을 만날 때마다 **확률
  P_ENTER = 0.01** 로 진입.
- **약 10분 탐색 후 복귀**: 진입 시 **약 10분(±30%)** 동안 골목을 무작위 보행(미-경로·이질
  방향 선호)하다 주 경로로 복귀.
- **앙상블(Monte-Carlo)**: 시드 **0,1,…,N−1**(기본 N=100)로 반복 시행 후 평균 → 단일
  실현의 분산을 줄이고 골목까지 **약하게·고르게** 침투하는 기대 방문장을 얻는다. 이는
  통계물리의 **앙상블 평균/몬테카를로** 와 동일 발상이다 [Metropolis & Ulam 1949].

이 확률적 간헐 이탈은 인간·동물 이동의 **간헐적 탐색(intermittent search)** 및 **Lévy/무작위
비행** 패턴과 개념적으로 연결되고 [Viswanathan et al. 1999; Brockmann, Hufnagel & Geisel 2006;
González, Hidalgo & Barabási 2008], 다수 자기추진 입자의 집합동학을 다루는 **자기추진입자
모형** [Vicsek et al. 1995]과 같은 계열의 사고를 공유한다(본 모형은 차량 간 비상호작용 근사).

### 5.3 거시 산출: 연간 방문빈도장

본 경로(결정론)는 \(\times\text{days}\)로 1회 누적하고, 골목 이탈만 앙상블로 누적·스케일
(\(\times \text{days}/N\))하여 도로 구간별 **연간 방문빈도(visits\_year)** 를 산출한다. 결과는
"어느 도로가 1년간 얼마나 자주 순찰되는가"의 기대 장(field)이다.

---

## 6. 인공지능(자율 에이전트) 관점에서의 행동 정리

각 순찰차를 **부분관측 환경에서 행동하는 자율 에이전트**로 기술한다(본 모형은 학습된 신경
정책이 아니라 **규칙기반 확률 정책**이며, 'AI'는 자율 의사결정 에이전트를 뜻한다).

### 6.1 행동양식 (Behavioral Policy)

| 요소 | AI 용어 | 본 모형 구현 |
|---|---|---|
| 정책 π | 경로추종 정책 | 결정론적 주 경로 추종 |
| 활용(exploitation) | 보상 높은 행동 | 고수요 핫스팟 ~15분 체류(Koper) |
| 탐험(exploration) | ε-탐험 (ε=0.01) | 골목 0.01 확률 진입 |
| 탐색 옵션 | temporal option | 약 10분 후 주 경로 복귀 |
| 확률 정책 | stochastic policy | 시드별 무작위 순서·이탈 |
| 다중 에이전트 협응 | multi-agent coordination | anti-convoy(전역 커버 공유) |

이는 강화학습의 **탐험-활용 절충** [Sutton & Barto 2018]을 순찰 맥락에 옮긴 것으로,
낮은 탐험률(0.01)로 활용(핫스팟 체류)과 탐험(골목 점검)을 균형 잡는다.

### 6.2 이론적 위치 — 부분관측·국지규칙·창발

에이전트는 전역 최적해를 모른 채 국지 정보(인접 도로, 방문여부)로 행동(분권적 의사결정)
하며, 단순 규칙(따라가다 가끔 이탈)의 다수 시행 평균에서 **도시 전역의 부드러운 순찰
커버리지장**이 창발한다. 시드별 무작위 순서·이탈은 잠재적 범죄자에 대한 **억제(예측불가
순회)** 를 제공한다.

### 6.3 효과 (Expected Effects)

1. **억제(deterrence)**: 핫스팟 체류 + 무작위 순회로 잔여 억제 극대화.
2. **광역 커버리지**: 골목 탐색 앙상블로 주 경로 밖까지 약하게 순찰 → 사각 최소화.
3. **강건성(robustness)**: 단일 경로 의존이 아닌 분포적 순찰로 결손에 덜 취약.
4. **형평성(equity) 진단**: 방문빈도장을 수요·시설과 비교하여 자원배분 형평성·사각지대 진단.

---

## 7. 복합 안전지수와 사각지대

도로 구간별 **복합 안전지수(0–100)**:
\[
\text{safety} = 100\,(\,0.5\cdot \text{presence} + 0.3\cdot \text{access} + 0.2\cdot \text{facility}\,)
\]
- **presence**: ABM 연간 방문빈도(로그 정규화) — 높을수록 안전.
- **access**: 파출소(depot)에서 구간까지 도달시간(Dijkstra **isochrone**) — 가까울수록 안전.
  응급·치안의 **응답시간(response time)** 접근성 이론에 근거.
- **facility**: 반경 내 CCTV·비상벨 수(KDTree 집계) — CPTED 자연·기계 감시 대리지표
  [Newman 1972].

수요(인구)가 높은데 안전이 낮은 구간을 **사각지대 우선순위**로 자동 추출한다.

---

## 8. 웹 시각화 아키텍처 (지연로딩)

전국 약 150만+ 도로구간을 단일 지도에 한 번에 그리면 브라우저가 과부하된다. 이를 **벡터
타일 + 세부수준(LOD)** 패러다임으로 해결한다(웹 GIS의 표준 접근).

- **타일 분할**: safety 엣지를 약 5.5km(0.05°) 좌표 타일 JSON으로 분할(`tiles/{ix}_{iy}.json`).
- **세부수준(LOD)**: 줌아웃이면 가벼운 **격자 개요**만, 줌인(레벨≤6)이면 상세 로드.
- **정지 트리거(debounce)**: 화면이 **3초 이상 정지**했을 때만 현재 화면에 걸친 타일을 fetch·
  렌더(패닝/줌 중엔 로드 안 함). 사용자가 보려는 영역만 로드하여 과부하를 원천 차단.
- **경량 export**: 서버는 ABM·안전지수만 수행하고 웹이 쓰는 6컬럼을 gzip으로 저장,
  로컬에서 타일 생성·웹 제작(연산 분리).

이는 슬리피 맵(slippy map)·벡터 타일의 **요청-시-렌더(load-on-demand)** 와 동일 원리이다.

---

## 9. 기술 구현 상세 및 파라미터

| 구성요소 | 구현 |
|---|---|
| 언어/라이브러리 | Python, networkx, geopandas/pyogrio, shapely, scipy(KDTree·Voronoi), pyproj, numpy/pandas, openpyxl |
| 좌표계 | EPSG:5179(거리·시간), EPSG:4326(OSM·지도) |
| 병렬화 | ProcessPoolExecutor(관서 단위), tqdm, tmux 장기실행 |
| 재현성 | ABM 시드 0..N−1, resume(`--force`), `--region` 단위 검증 |
| 시각화 | 카카오맵, 빨강(위험)–보라–파랑(안전) 팔레트, 안전선 투명도 0.2, CCTV/비상벨 줌인 이모지, 관서 핀, 6권역/지연로딩 |

**주요 파라미터(기본값)**: 슬롯 8개(3h) · 순찰예산 150–180분 · 최소 120분(hard floor) ·
목표 ~150분(±15) · Koper 체류 15분 · 정속 30–50km/h · 주요도로 `lanes≥4` · 보로노이 버퍼
1.2km · 수요거듭제곱 γ=2.0 · 동시순찰 1–3대 · 정차 ≤3 · P_ENTER 0.01 · 골목탐색 ~10분 ·
앙상블 100(seed 0–99) · 안전지수 가중 0.5/0.3/0.2 · 타일 0.05° · 정지 트리거 3초.

산출물: 슬롯별 경로 JSON, 경로요약 CSV, ABM 방문빈도 CSV, 복합 안전지수·사각지대 CSV,
**계층 결과 XLSX(시도→경찰서→파출소)**, 권역/지연로딩 안전지도.

---

## 10. 검증

- **순찰 타당성**: 경로 시각화에서 닫힘 여부·정차수·순찰시간을 코드로 검증(흔적없음·안닫힘 0,
  정차 2–3, 순찰 135–165분).
- **계층 결과**: 시도→경찰서→파출소 차량배분·동시순찰·커버리지·순찰시간 표로 합리성 검수.
- **공간 타당성**: anti-convoy로 차량 간 겹침이 감소하고 셀 전반이 분산 커버되는지 확인.

---

## 11. 한계와 향후 과제

1. **이동시간**: EPSG:5179 거리 기반 정속 근사 → 카카오모빌리티 실주행/실시간 교통으로 대체
   가능(쿼터·비용 고려).
2. **시간대 유동인구 해상도**: 현재 가용 데이터가 시·도/시군구 단위로 희소 → 100m/행정동
   시간대 유동인구 확보 시 시간대 차별화가 크게 강화됨(구조는 이미 반영).
3. **정식 메타휴리스틱**: 현재는 anti-convoy·wide-exploration의 *동작*을 휴리스틱으로 이식 →
   시뮬레이티드 어닐링·OR-Tools VRP로 전역 목적함수 최적화 가능 [Kirkpatrick 1983].
4. **에이전트 상호작용**: 비상호작용 근사 → 신고출동 이벤트·차량 간 동적 재배치(자기추진입자
   상호작용)로 확장 가능.
5. **타당성 검증**: 산출 안전지수를 실제 범죄 발생 분포와 상관분석하여 통계적으로 검증 권장.

---

## 12. 구현 ↔ 이론 매핑 (요약)

| 구현 요소 | 이론/근거 | 문헌 |
|---|---|---|
| 핫스팟 정차 | 핫스팟 폴리싱·범죄집중 | Sherman&Weisburd 1995; Braga 2019; Weisburd 2015 |
| 15분 체류·예측불가 순회 | Koper Curve | Koper 1995 |
| 시간대 유동·도로 이동 | 일상활동·범죄패턴 | Cohen&Felson 1979; Brantingham 1993 |
| 차량 수요비례 배분 | 순찰자원 배분 | Larson 1972 |
| 보로노이 soft 관할 | 공간 테셀레이션·입지배분 | Okabe 2000; Larson 1972 |
| 10m 도로 그래프 | OSM 네트워크 모형화 | Boeing 2017 |
| 닫힌 커버 경로 | 오리엔티어링·아크라우팅·CPP | Vansteenwegen 2011; Edmonds&Johnson 1973; Galceran 2013 |
| anti-convoy·wide-explo | 메타휴리스틱(SA) | Kirkpatrick 1983 |
| 0.01·10분 골목 탐색 | 네트워크 무작위보행·간헐탐색 | Noh&Rieger 2004; Viswanathan 1999 |
| 시드 앙상블 평균 | 몬테카를로·앙상블 | Metropolis&Ulam 1949 |
| 자율 에이전트·탐험/활용 | ABM·강화학습 | Bonabeau 2002; Sutton&Barto 2018 |
| CCTV·비상벨 안전항 | CPTED | Jeffery 1971; Newman 1972 |

---

## 13. 참고문헌 (References)

**경찰행정·환경범죄학**
- Koper, C. S. (1995). *Just Enough Police Presence: Reducing Crime and Disorderly Behavior by Optimizing Patrol Time in Crime Hot Spots.* Justice Quarterly, 12(4), 649–672.
- Sherman, L. W., & Weisburd, D. (1995). *General Deterrent Effects of Police Patrol in Crime "Hot Spots": A Randomized, Controlled Trial.* Justice Quarterly, 12(4), 625–648.
- Braga, A. A., Turchan, B., Papachristos, A. V., & Hureau, D. M. (2019). *Hot Spots Policing of Small Geographic Areas Effects on Crime.* Campbell Systematic Reviews, 15(3), e1046.
- Weisburd, D. (2015). *The Law of Crime Concentration and the Criminology of Place.* Criminology, 53(2), 133–157.
- Cohen, L. E., & Felson, M. (1979). *Social Change and Crime Rate Trends: A Routine Activity Approach.* American Sociological Review, 44(4), 588–608.
- Brantingham, P. L., & Brantingham, P. J. (1993). *Environment, Routine, and Situation: Toward a Pattern Theory of Crime.* Advances in Criminological Theory, 5.
- Larson, R. C. (1972). *Urban Police Patrol Analysis.* MIT Press.
- Jeffery, C. R. (1971). *Crime Prevention Through Environmental Design.* Sage.
- Newman, O. (1972). *Defensible Space: Crime Prevention Through Urban Design.* Macmillan.

**지리정보과학·최적화**
- Boeing, G. (2017). *OSMnx: New Methods for Acquiring, Constructing, Analyzing, and Visualizing Complex Street Networks.* Computers, Environment and Urban Systems, 65, 126–139.
- Okabe, A., Boots, B., Sugihara, K., & Chiu, S. N. (2000). *Spatial Tessellations: Concepts and Applications of Voronoi Diagrams* (2nd ed.). Wiley.
- Edmonds, J., & Johnson, E. L. (1973). *Matching, Euler Tours and the Chinese Postman.* Mathematical Programming, 5, 88–124.
- Vansteenwegen, P., Souffriau, W., & Van Oudheusden, D. (2011). *The Orienteering Problem: A Survey.* European Journal of Operational Research, 209(1), 1–10.
- Gunawan, A., Lau, H. C., & Vansteenwegen, P. (2016). *Orienteering Problem: A Survey of Recent Variants, Solution Approaches and Applications.* EJOR, 255(2), 315–332.
- Galceran, E., & Carreras, M. (2013). *A Survey on Coverage Path Planning for Robotics.* Robotics and Autonomous Systems, 61(12), 1258–1276.
- Kirkpatrick, S., Gelatt, C. D., & Vecchi, M. P. (1983). *Optimization by Simulated Annealing.* Science, 220(4598), 671–680.

**복잡계 물리학·ABM·이동성**
- Bonabeau, E. (2002). *Agent-Based Modeling: Methods and Techniques for Simulating Human Systems.* PNAS, 99(suppl. 3), 7280–7287.
- Epstein, J. M., & Axtell, R. (1996). *Growing Artificial Societies: Social Science from the Bottom Up.* MIT Press.
- Vicsek, T., et al. (1995). *Novel Type of Phase Transition in a System of Self-Driven Particles.* Physical Review Letters, 75(6), 1226–1229.
- Noh, J. D., & Rieger, H. (2004). *Random Walks on Complex Networks.* Physical Review Letters, 92(11), 118701.
- Viswanathan, G. M., et al. (1999). *Optimizing the Success of Random Searches.* Nature, 401, 911–914.
- Brockmann, D., Hufnagel, L., & Geisel, T. (2006). *The Scaling Laws of Human Travel.* Nature, 439, 462–465.
- González, M. C., Hidalgo, C. A., & Barabási, A.-L. (2008). *Understanding Individual Human Mobility Patterns.* Nature, 453, 779–782.
- Metropolis, N., & Ulam, S. (1949). *The Monte Carlo Method.* Journal of the American Statistical Association, 44(247), 335–341.
- Groff, E. R. (2007). *Simulation for Theory Testing and Experimentation: An Example Using Routine Activity Theory and Street Robbery.* Journal of Quantitative Criminology, 23(2), 75–103.
- Malleson, N., Heppenstall, A., & See, L. (2010). *Crime Reduction Through Simulation: An Agent-Based Model of Burglary.* Computers, Environment and Urban Systems, 34(3), 236–250.
- Andresen, M. A., & Malleson, N. (2015). *Crime, ABM, and CPTED.* Environment and Planning B.

**인공지능·강화학습**
- Sutton, R. S., & Barto, A. G. (2018). *Reinforcement Learning: An Introduction* (2nd ed.). MIT Press.

---

*문서 생성: 전국 순찰 최적화·가상순찰 파이프라인 (2026, 개정판)*
