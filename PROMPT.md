# PROMPT — `hair_anakin_01_mesh.fbx` 헤어스타일을 레퍼런스 이미지 기준으로 변경하기

이 문서는 Blender(bpy)를 다룰 수 있는 에이전트(또는 사람)에게 그대로 넘겨 실행할 수 있도록 쓴 작업 프롬프트입니다.
`tools/hair_pipeline.py` 가 이 프롬프트를 코드로 옮긴 결과물이고, `styles/anakin_ahsoka.json` 이 1차 실행에 쓴 파라미터입니다.

---

## 역할

너는 게임용 헤어 카드(hair card) 에셋을 다루는 테크니컬 아티스트다. 아래 자산과 레퍼런스를 보고
**원본 FBX의 토폴로지·UV·스킨 웨이트를 깨지 않은 채** 헤어스타일만 레퍼런스에 맞게 바꾼다.

## 입력 자산 (`source/`, `reference/`)

| 파일 | 내용 |
|---|---|
| `source/hair_anakin_01_mesh.fbx` | Kaydara FBX 7.2, Y-up. 아마추어 `Reference`(MetaHuman 계열 본: `Neck`, `Neck1`, `Head`, `HeadRoll`, `FACIAL_LOD1_*`) + 메시 2개 |
| └ `HairPlanes_M` | 헤어 카드 9,519 verts / 10,432 tris, 연결된 섬(island) **463개 = 카드 463장**. UV `UVChannel0`(0~1), 카드 길이 평균 6.3 cm, 최대 12.8 cm. 443장은 UV v=0 쪽이 뿌리(root). |
| └ `hair_cap` | 두피 캡 704 verts / 1,230 tris. `Head`, `Neck`, `Neck1`, `HeadRoll` 에 스킨됨 |
| `reference/textures/hair_strips_albedo_alpha_1024x512.webp` | 카드용 스트립 아틀라스(알베도+알파). 8개 스트립, 위쪽이 뿌리(굵음) 아래쪽이 끝(가늘고 흩어짐) |
| `reference/textures/hair_strips_normal_1024x512.webp` | 위 아틀라스와 같은 레이아웃의 노멀/플로우 맵 (RGB 평균 ≈ (186,187,145) — 표준 (128,128,255) 인코딩이 아니므로 확인 전에는 셰이딩에 쓰지 말 것) |
| `reference/textures/hair_scalp_albedo_1500.webp` | 두피 캡 알베도(+알파). 큰 원형 셸 + 좌측 얇은 스트립 |
| `reference/textures/hair_scalp_flow_or_id_2000.webp` | 두피 캡과 같은 UV 레이아웃의 플로우/노멀 맵 (인코딩 동일하게 비표준) |
| `reference/photos/anakin_ahsoka_ref_01.webp` | 목표 스타일 사진 |

추가로 대화에서 받은 레퍼런스 3장(파일로 저장되지 않음) — 〈아소카〉 아나킨 포스터 1장, Hot Toys 〈Ahsoka〉 Anakin Skywalker (Clone Wars) 1/6 피규어 헤드 2장. 아래 "목표 스타일"은 이 네 장을 종합한 것이다.

## 좌표계 (Blender로 임포트한 뒤)

- Z-up. 얼굴은 **-Y** 를 본다(`Head` 본 tail y=-0.149, 이마 본 y≈-0.10). 뒤통수·목덜미는 +Y.
- 캐릭터의 **왼쪽 = +X** (`FACIAL_LOD1_L_Ear` x=+0.07). 정면 카메라(-Y에서 +Y를 봄)에서는 화면 오른쪽이 캐릭터 왼쪽.
- 머리 중심 ≈ (0, -0.04, 1.70), 두피 캡 z 범위 1.568~1.828, 귀 z 1.655~1.74.
- 충돌/프리뷰용 두상은 타원체 반지름 (0.080, 0.098, 0.112) 로 근사.

## 목표 스타일 — "Anakin Skywalker, Ahsoka/Clone Wars 시대 (Hayden Christensen)"

1. **가르마**: 캐릭터 오른쪽(-X), 중심에서 약 2.5 cm. 가르마 선 위 카드는 양옆으로 벌어져 두피가 살짝 보인다.
2. **윗머리(top)**: 길이 유지(원본의 0.9~1.0배, 8~12 cm). 가르마에서 **캐릭터 왼쪽(+X)·뒤(+Y)** 로 빗어 넘기고, 이마 위에서 한 번 크게 들렸다가 옆으로 떨어지는 **굵은 S-웨이브**(진폭 ≈ 0.5~1 cm, 카드 한 장에 1 파장 이하). 이웃 카드끼리 **같은 위상**으로 물결쳐야 하나의 덩어리 웨이브로 읽힌다. 랜덤 위상은 바람 맞은 머리처럼 보이므로 금지.
3. **앞머리(front)**: 이마를 덮고 늘어지지 않는다. 뿌리에서 위·뒤로 2~3 cm 들렸다가 가르마 반대쪽(+X)으로 흐른다. 가르마 쪽(-X) 앞머리는 반대 방향(-X·뒤)으로 빗는다.
4. **옆머리(side_L/side_R)**: 원본의 약 0.45배로 짧게. 귀 위쪽 1/3만 덮고 귀 대부분이 보인다. 구레나룻은 귀 중간 높이까지.
5. **뒷머리(back)**: 약 0.6배. 목덜미로 갈수록 점점 짧아지는 테이퍼. **목덜미(nape)** 끝은 바깥·위로 살짝 말린다(1 cm 정도).
6. **볼륨**: 윗머리는 두피에서 1 cm 정도 떠서 풍성하게, 옆·뒤는 두피에 붙는다. 어떤 정점도 두상 타원체 안으로 들어가거나 두피에서 3.5 cm 이상 떨어지지 않는다. 정수리 위로 솟는 카드 금지.
7. **색**: 따뜻한 중간 갈색. 제공된 스트립 알베도를 그대로 쓰면 맞는다(틴트 0). 스페큘러는 낮게(IOR level ≈ 0.08) — 얇은 카드가 겹치면 프레넬 때문에 하얗게 떠 보인다.

## 반드시 지킬 제약

- 카드의 **뿌리 정점은 움직이지 않는다**(두피에 심어진 위치 유지). 변형량은 뿌리 0 → 끝 1로 커진다.
- 정점 수·면 수·UV·스킨 웨이트·본 계층은 그대로. 카드를 추가/삭제하지 않는다(길이는 카드 스케일로만 조정 → 텍스처가 조금 늘어나는 것은 허용).
- 카드를 회전시킬 때는 **카드 프레임 전체를 회전**한다. 방향 벡터만 바꾸면 카드가 옆면(edge-on)으로 서서 선처럼 보인다.
- 텍스처는 Blender 임포트 기준 V를 뒤집어야 뿌리(굵은 쪽)가 두피에 온다(`texture_flip_v: true`).
- 노멀/플로우 맵은 인코딩을 확인하기 전까지 프리뷰 셰이딩에 연결하지 않는다.

## 실행 절차

1. `source/hair_anakin_01_mesh.fbx` 임포트 → `HairPlanes_M`, `hair_cap`, `Reference` 확인.
2. 머티리얼 생성: 카드 = 스트립 알베도(알파 → Alpha, DITHERED) / 캡 = 두피 알베도. V 뒤집기.
3. 카드마다 연결 섬을 구해 뿌리/끝(두피 캡까지 거리로 판정), 길이, 방향, 두피 바깥 방향(타원체 법선), UV v 기반 0~1 진행도 `s` 를 만든다.
4. 뿌리 위치로 영역 가중치(top/front/side_L/side_R/back/nape)를 부드럽게(smoothstep) 계산한다 — 경계가 딱 끊기면 줄이 생긴다.
5. 각 정점에 순서대로: 길이 스케일 → 영역별 목표 방향으로 카드 프레임 회전(quaternion, `s`에 비례) → 가르마 밀어내기 → 위치 기반 위상의 S-웨이브 → 볼륨 리프트(`s²`) → 중력 처짐 → 목덜미 컬(`s³`) → 정수리/상승량 클램프 → 타원체 충돌(안쪽·바깥 3.5 cm 모두).
6. FBX(아마추어 포함, 스킨 유지)와 .blend 로 내보내고 front / 3/4 / side / back 네 방향을 렌더해 원본과 나란히 비교한다.
7. 비교 시트를 보고 파라미터(JSON)를 고쳐 다시 돌린다. 코드가 아니라 **JSON만 바꿔서** 반복할 수 있어야 한다.

## 합격 기준

- 정면: 가르마 -X, 윗머리가 +X로 넘어가며 S-웨이브가 한 덩어리로 읽힘. 이마가 보임.
- 측면: 귀가 2/3 이상 보임. 뒷머리는 목덜미로 갈수록 짧아짐.
- 어느 방향에서도 두상을 뚫는 카드·공중에 뜬 막대 모양 카드·정수리 위로 솟은 카드가 없음.
- 내보낸 FBX를 다시 임포트하면 정점/면 수(9,519 / 10,432)와 버텍스 그룹이 원본과 같음.

## 실행 명령

```bash
pip install bpy numpy pillow          # Blender 4.x/5.x 파이썬 모듈
python3 tools/hair_pipeline.py --style styles/anakin_ahsoka.json --render     # 변형 + FBX/blend 내보내기 + 렌더
python3 tools/hair_pipeline.py --style none --render --no-export --flip-v 1 --name hair_anakin_01_original   # 원본 비교 렌더
```

## 파라미터 설명 (`styles/*.json`)

| 키 | 의미 |
|---|---|
| `texture_flip_v`, `use_normal_maps`, `roughness`, `specular`, `hair_tint_rgb`, `hair_tint_mix` | 프리뷰 머티리얼 |
| `part_x`, `part_width` | 가르마 x 위치(m)와 영향 폭 |
| `sweep_dir` | 영역별 `sweep_dir` 이 없을 때 쓰는 기본 빗질 방향 |
| `wave_freq`, `wave_coherence`, `wave_jitter` | 카드당 파장 수, 두피 위 공간 주파수(파장/m), 카드별 랜덤 위상(rad) |
| `collision_margin`, `max_out`, `max_rise`, `front_extra_rise`, `crown_clearance` | 두피 간격, 헤어 두께 한계, 정점 상승 한계(앞머리는 추가 허용), 정수리 여유 |
| `regions.<영역>.length / sweep / sweep_dir / lift / wave_amp / droop` | 길이 배율, 빗질 강도(0~1), 빗질 목표 방향(Blender 좌표), 볼륨(m), 웨이브 진폭(m), 처짐(m) |
| `regions.nape.curl` | 목덜미 끝 말림(m) |

다른 헤어스타일(예: 〈클론 전쟁〉 애니메이션판 짧은 머리, 〈시스의 복수〉 긴 머리)은 이 JSON을 복사해 영역별 길이·방향만 바꾸면 된다.
