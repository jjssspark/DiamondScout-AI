# 제미나이 이미지 생성 프롬프트 — 배경 2장 + 누끼 인물 3장

DiamondScout AI 스트라이크존 화면에 쓸 이미지다.
**배경판**과 **누끼 딴 인물**을 따로 받아서 코드로 겹친다.

## 왜 따로 받나

인물이 배경에 박혀 있으면 좌타/우타를 못 바꾸고, 공이 인물 앞뒤로 지나갈 수 없다.
누끼(투명 배경)로 받으면 레이어를 나눠서 **공이 타자 뒤로 지나갔다가 앞으로 나오는** 연출이 된다.

## 좌우는 뒤집어 쓴다 — 절반만 뽑으면 된다

유니폼에 글자·번호를 안 넣으므로 **우타자 이미지를 좌우 반전하면 좌타자가 된다.**
코드에서 `transform: scaleX(-1)` 한 줄이다. 그래서 손잡이별로 따로 안 뽑아도 된다.

**필요한 건 5장이다.** (포수 1장은 선택)

| # | 파일 | 쓰이는 곳 |
|---|---|---|
| A1 | `bg-pitcher-view.png` | 투수 모드 배경 |
| A2 | `bg-batter-view.png` | 타자 모드 배경 |
| B1 | `batter-front.png` | 투수 모드 — 타자 정면 (누끼) |
| B2 | `batter-back.png` | 타자 모드 — 타자 뒷모습 (누끼) |
| B3 | `pitcher-front.png` | 타자 모드 — 투수 정면 (누끼) |
| B4 | `catcher-back.png` | 투수 모드 — 포수 뒷모습 (누끼, 선택) |

저장 위치: `output/mockups/assets/`

---

# 1. 배경 2장 (인물 없음)

## A1 — 투수 시점 배경 (v2, 재작성)

내가 마운드에서 홈플레이트를 바라보는 화면. **던지는 시점.**

> **v1이 실패한 이유** — 투구판이 화면 하단을 가득 채우고 홈플레이트가 지평선까지
> 밀려나 아주 작게 나왔다. 존 격자를 얹을 자리가 안 나온다. 중간에 두 번째 마운드가
> 생기는 현상도 있었다. v2는 (1) 카메라를 아래로 15도 기울이고 (2) 투구판·마운드를
> 프레임에서 빼고 (3) 홈플레이트가 차지할 화면 비율을 숫자로 못 박았다.

```
A stylized 3D render of a baseball infield seen from the PITCHER'S
VIEWPOINT, looking toward home plate. The camera is 1.8 m above the
mound and TILTED DOWN 15 degrees so that home plate sits comfortably
inside the lower half of the frame, not near the horizon. 50mm
equivalent lens, no roll, no dutch angle.

Composition, locked — follow these proportions exactly:
- HOME PLATE is the subject. Center it horizontally. Its center sits
  about 62% of the way down from the top edge of the frame.
- Home plate must be LARGE and clearly readable — the white pentagon
  plus the two chalk batter's boxes flanking it together span roughly
  ONE THIRD of the total frame width.
- The pentagon is oriented with its flat edge toward the camera and
  its point away from the camera.
- Both batter's boxes are EMPTY, drawn with clean white chalk lines.
- Behind the plate: dirt, then the backstop, then a very dark neutral
  blurred stand area. No crowd faces, no advertising, no text.
- Above and around home plate: open, uncluttered space.
- Absolutely no people anywhere in frame.

DO NOT INCLUDE — these ruined earlier attempts:
- Do NOT show the pitcher's mound, the pitching rubber, or any dirt
  circle in the foreground. The camera stands ON the mound, so the
  mound is beneath and behind the camera, entirely out of frame.
- Do NOT place a second mound or a second dirt circle anywhere.
- The bottom edge of the frame should be plain infield grass or dirt,
  nothing else.

Style:
- Muted editorial sports-graphic look. NOT photorealistic, NOT cartoon.
- Flat even lighting, no harsh sun, no lens flare, no motion blur,
  no depth-of-field blur. Sharp throughout.
- Restrained palette: cream #f4f2ec light tones, warm beige dirt,
  desaturated sage-green grass, deep navy #14203c for dark areas.
  NO RED anywhere — red is reserved for the data overlay.
- No team logos, no signage, no numbers, no text of any kind.

Critical constraints:
- Keep the area directly ABOVE home plate visually QUIET and
  uncluttered — a strike zone grid will be composited there.
- No strike zone box, no grid, no arrows, no annotations, no watermark,
  no sparkle or star decoration in any corner.
- 16:10 aspect ratio.
```

**A1 합격 기준** — 이것만 보면 된다.

- [ ] 화면 하단에 **투구판·마운드가 없는가** (있으면 실패, 다시)
- [ ] 홈플레이트가 **화면 세로 60% 근처**에 있고, 타석 포함해 **가로폭의 1/3쯤** 되는가
- [ ] 마운드처럼 생긴 흙 원이 **하나도 없는가**
- [ ] 홈플레이트 위쪽이 비어 있는가

## A2 — 타자 시점 배경

내가 타석에 서서 마운드를 바라보는 화면. **치는 시점.**

```
A stylized 3D render of a baseball field seen from BEHIND AND SLIGHTLY
ABOVE A BATTER'S SHOULDER in the batter's box, looking out toward the
pitcher's mound. Over-the-shoulder sports-game camera. The camera sits
2.0 m above ground, 1.5 m behind the batter's box, angled very slightly
downward. 50mm equivalent lens, no roll, horizon level.

Composition, locked:
- The pitcher's mound in the CENTER of frame at the vanishing point,
  clearly visible with the pitching rubber, at realistic distance
  (18.44 m). No pitcher figure on it.
- Home plate in the near foreground at the BOTTOM of frame, partially
  cropped by the frame edge, seen from behind at a steep angle.
- Empty batter's boxes with chalk lines in the foreground.
- Infield dirt, then neutral green grass, then a blurred very dark
  neutral outfield wall area far behind the mound — no crowd faces,
  no advertising, no text.
- Absolutely no people anywhere in frame.

Style:
- Muted editorial sports-graphic look. NOT photorealistic, NOT cartoon.
- Flat even lighting, no harsh sun, no lens flare, no motion blur,
  no depth-of-field blur. Sharp throughout.
- Restrained palette: cream #f4f2ec light tones, warm beige dirt,
  desaturated sage-green grass, deep navy #14203c for dark areas.
  NO RED anywhere — red is reserved for the data overlay.
- No team logos, no signage, no numbers, no text of any kind.

Critical constraints:
- Keep the CENTER of the frame, between the plate and the mound,
  visually QUIET — a strike zone grid will be composited there.
- No strike zone box, no grid, no arrows, no annotations, no watermark.
- 16:10 aspect ratio.
```

---

# 2. 누끼 인물 3장

**누끼 공통 규칙 — 아래 세 프롬프트에 이미 다 들어가 있다.**

- 배경은 **순수 마젠타 `#FF00FF`** 단색. 야구 유니폼에 절대 안 나오는 색이라 깔끔하게 빠진다.
  (제미나이가 투명 PNG를 바로 주면 그게 더 좋다. 그 경우 마젠타 문장은 무시해도 된다.)
- 바닥 그림자·반사 없음. 그림자가 있으면 배경에 합성했을 때 두 겹이 된다.
- 발끝까지 전신. 잘리면 지면에 세울 수 없다.
- 로고·등번호·글자 없음. 좌우 반전해서 재사용하기 위해서다.

## B1 — 타자 정면 (투수 모드용)

투수가 마운드에서 바라보는 타자. **정면으로 나를 향해 선 모습.**

```
A single baseball batter, full body, isolated as a cutout asset.

Pose and angle:
- A RIGHT-HANDED batter in a balanced ready batting stance, seen from
  the FRONT — the batter faces the camera directly, chest and face
  toward the viewer, as a pitcher on the mound would see them.
- Bat held up off the back shoulder, elbows relaxed, knees slightly
  bent, weight centered. Alert but not mid-swing.
- Head turned to face the camera, eyes forward.
- Full body visible from cleats to helmet, nothing cropped.
- Camera at chest height, 50mm equivalent lens, no tilt, no roll,
  straight-on view with no perspective distortion.

Style:
- Muted editorial sports-graphic look. NOT photorealistic, NOT cartoon.
- Flat even lighting from the front, soft form shading only.
- Deep navy #14203c uniform, white helmet, neutral grey-brown bat,
  white pants with a navy belt. NO RED anywhere.
- Generic uniform: no team logo, no number, no name, no text, no
  recognizable player likeness.

CUTOUT REQUIREMENTS — critical:
- The background must be a single FLAT, UNIFORM pure magenta #FF00FF
  filling the entire frame. Nothing else in the background.
- NO ground, NO floor, NO shadow, NO reflection, NO gradient,
  NO vignette, NO scenery.
- The figure must not touch or overlap the frame edges — leave clear
  magenta margin on all four sides.
- Crisp, clean edges suitable for keying out.
- Vertical portrait aspect ratio, 3:4.
```

## B2 — 타자 뒷모습 (타자 모드용)

내가 타석에 섰을 때 앞에 보이는 내 뒷모습. **뒤통수와 등이 보인다.**

```
A single baseball batter, full body, isolated as a cutout asset.

Pose and angle:
- A RIGHT-HANDED batter in a balanced ready batting stance, seen from
  BEHIND — the back of the helmet and the back of the jersey face the
  camera, as an over-the-shoulder sports-game camera would see them.
- The batter's head is turned slightly to the side, looking out toward
  where a pitcher would be, so a sliver of the cheek and helmet earflap
  is visible but the back of the head dominates.
- Bat held up off the back shoulder, visible above the shoulder line.
- Slight three-quarter turn so the stance reads clearly rather than a
  perfectly flat back view.
- Full body visible from cleats to helmet, nothing cropped.
- Camera at upper-chest height, 50mm equivalent lens, no tilt, no roll.

Style:
- Muted editorial sports-graphic look. NOT photorealistic, NOT cartoon.
- Flat even lighting, soft form shading only.
- Deep navy #14203c uniform, white helmet, neutral grey-brown bat,
  white pants with a navy belt. NO RED anywhere.
- Generic uniform: absolutely no team logo, NO NUMBER ON THE BACK,
  no name across the shoulders, no text, no recognizable player.

CUTOUT REQUIREMENTS — critical:
- The background must be a single FLAT, UNIFORM pure magenta #FF00FF
  filling the entire frame. Nothing else in the background.
- NO ground, NO floor, NO shadow, NO reflection, NO gradient,
  NO vignette, NO scenery.
- The figure must not touch or overlap the frame edges — leave clear
  magenta margin on all four sides.
- Crisp, clean edges suitable for keying out.
- Vertical portrait aspect ratio, 3:4.
```

> 뒷모습은 등번호가 특히 잘 생긴다. 받은 이미지에 번호가 있으면 다시 뽑는다.

## B3 — 투수 정면 (타자 모드용)

타자가 타석에서 바라보는 투수. **마운드 위에서 나를 향해 던지려는 자세.**

```
A single baseball pitcher, full body, isolated as a cutout asset.

Pose and angle:
- A RIGHT-HANDED pitcher at the top of the leg lift, just before
  driving toward the plate — front knee raised, glove hand tucked in
  front of the chest, throwing arm beginning to separate behind.
- Seen from the FRONT, facing the camera directly, as a batter standing
  in the box would see them.
- Head up, eyes toward the camera.
- Full body visible from cleats to cap, nothing cropped.
- Camera at chest height, 50mm equivalent lens, no tilt, no roll,
  straight-on view with no perspective distortion.

Style:
- Muted editorial sports-graphic look. NOT photorealistic, NOT cartoon.
- Flat even lighting from the front, soft form shading only.
- Deep navy #14203c uniform and cap, white pants with a navy belt,
  neutral brown glove. NO RED anywhere.
- Generic uniform: no team logo, no number, no name, no text, no
  recognizable player likeness.

CUTOUT REQUIREMENTS — critical:
- The background must be a single FLAT, UNIFORM pure magenta #FF00FF
  filling the entire frame. Nothing else in the background.
- NO ground, NO mound, NO floor, NO shadow, NO reflection, NO gradient,
  NO vignette, NO scenery.
- The figure must not touch or overlap the frame edges — leave clear
  magenta margin on all four sides.
- Crisp, clean edges suitable for keying out.
- Vertical portrait aspect ratio, 3:4.
```

## B4 — 포수 뒷모습 (선택)

투수 모드에서 타자 아래쪽에 앉혀 현실감을 준다. 없어도 화면은 성립한다.

```
A single baseball catcher, full body, isolated as a cutout asset.

Pose and angle:
- A catcher in a low crouch behind home plate, seen from BEHIND —
  the back of the mask, chest protector straps, and shin guards face
  the camera, as a pitcher on the mound would see them.
- Glove hand raised and held up as a target, visible past the shoulder.
- Full body visible from cleats to mask, nothing cropped.
- Camera at standing chest height looking slightly down, 50mm
  equivalent lens, no roll.

Style:
- Muted editorial sports-graphic look. NOT photorealistic, NOT cartoon.
- Flat even lighting, soft form shading only.
- Deep navy #14203c gear and uniform, grey shin guards, neutral brown
  mitt. NO RED anywhere.
- Generic gear: no team logo, no number, no text, no recognizable player.

CUTOUT REQUIREMENTS — critical:
- The background must be a single FLAT, UNIFORM pure magenta #FF00FF
  filling the entire frame. Nothing else in the background.
- NO ground, NO plate, NO floor, NO shadow, NO reflection, NO gradient,
  NO scenery.
- The figure must not touch or overlap the frame edges.
- Crisp, clean edges suitable for keying out.
- Square aspect ratio, 1:1.
```

---

# 3. 받은 이미지 점검표

## 배경 2장

- [ ] **인물이 하나도 없는가** — 한 명이라도 있으면 다시
- [ ] A1: 홈플레이트가 하단 중앙, 타석 두 개가 비어 있는가
- [ ] A2: 마운드가 정중앙 소실점에 있는가
- [ ] **수평선이 안 기울었는가** — 기울면 존 격자가 삐뚤어 보인다
- [ ] 존 격자가 올라갈 중앙 영역이 비어 있는가
- [ ] 빨간색이 없는가
- [ ] 관중 얼굴·광고판·글자가 없는가

## 누끼 3장

- [ ] **배경이 균일한 마젠타 단색인가** (또는 진짜 투명 PNG인가)
- [ ] **그림자·바닥이 없는가** — 있으면 합성 시 그림자가 두 겹이 된다
- [ ] **발끝까지 다 들어왔는가**
- [ ] 인물이 프레임 가장자리에 안 닿았는가
- [ ] **등번호·이름·로고가 없는가** (B2 뒷모습에서 특히 잘 생긴다)
- [ ] 빨간색이 없는가
- [ ] B1은 정면, B2는 뒷모습, B3은 정면이 맞는가

---

# 4. 좌우 반전 주의

우타자/우투수만 뽑아서 코드로 뒤집는다. 그래서:

- 유니폼에 **글자·번호가 있으면 뒤집었을 때 거울 글씨가 된다.** 그래서 전부 금지했다.
- 얼굴에 비대칭 요소(한쪽에만 있는 무언가)가 크면 뒤집었을 때 어색하다. 받은 이미지가
  많이 비대칭이면 좌타/우타를 따로 뽑는 편이 낫다 — 그때 알려주면 프롬프트를 나눠 쓴다.

---

# 5. 이미지가 없어도 진행된다

배경·인물 없이도 원근 존과 투구 애니메이션은 코드로 먼저 만든다.
이미지가 오면 레이어만 갈아끼우도록 슬롯을 비워두므로 작업이 멈추지 않는다.
