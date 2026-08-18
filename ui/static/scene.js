/* 덕아웃 콘솔 캔버스 씬 엔진.
   output/mockups/dugout-console.html(사용자 승인본)에서 이동했다 — Task 5Z Step 3.
   카메라 상수는 v4 확정값이다. v5(존 확대)는 사용자가 이미 철회했으므로
   되돌리지 말 것. 철회 사유는 계획서와 SDD 원장에 있다.

   이 파일은 그리기만 한다. 값의 진실 공급원은 Python(ui/scene.py)이고,
   window.dsScene.update(payload) 한 곳으로만 들어온다. */
(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }

  /* 표시용 상태. 목업에서는 이 객체가 조작의 주인이었지만 앱에서는 사본이다. */
  var S = { mode: "pitcher", bats: "L" };

  /* 9칸 점수 (씬 인덱스 0~8, 0~1). ui/scene.py의 build_scene_payload가 채운다.
     앱과 씬의 칸 번호 규약이 다르므로 변환은 Python에서 이미 끝나 있다. */
  var cells = [0, 0, 0, 0, 0, 0, 0, 0, 0];

  /* 존 칸 이름 (씬 인덱스 순. ui/scene.py의 SCENE_CELL_NAME과 같아야 한다) */
  var CELL_NAME = [
    "높은 바깥쪽", "높은 한가운데", "높은 몸쪽",
    "가운데 바깥쪽", "한가운데", "가운데 몸쪽",
    "낮은 바깥쪽", "낮은 한가운데", "낮은 몸쪽"
  ];

  var cv = null, ctx = null, mounted = false;

  /* 목업은 -1~1로 손수 적은 HEAT 배열을 썼다(음수=타자가 약한 칸). 앱은 0~1
     원점수를 받으므로 9칸 안에서 min~max로 펴서 같은 범위로 옮긴다. SVG 보드
     (ui/zone_heatmap.py의 vmin/vmax 정규화)와 같은 규칙이라 두 화면의 색이
     같은 의미를 갖는다. 값이 전부 같으면 0(중립)으로 둔다. */
  function heatOf(i) {
    var lo = Math.min.apply(null, cells), hi = Math.max.apply(null, cells);
    if (hi - lo < 1e-9) { return 0; }
    return ((cells[i] - lo) / (hi - lo)) * 2 - 1;
  }

  /* 설정은 ui/static/scene-config.js가 window.__dsSceneConfig로 넘겨준다.
     자산 경로·카메라 해·실측 치수를 그 파일 한 곳에 모아 두면, 사진이나 누끼를
     교체할 때 그리기 코드를 열어볼 이유가 없다. */
  var CFG = window.__dsSceneConfig;
  var ASSETS = CFG.ASSETS;
  var SCENE_W = CFG.SCENE_W;
  var SCENE_H = CFG.SCENE_H;
  var MODES = CFG.MODES;
  var PLATE_HALF = CFG.PLATE_HALF;
  var PLATE_DEPTH = CFG.PLATE_DEPTH;
  var SZ_BOT = CFG.SZ_BOT;
  var SZ_TOP = CFG.SZ_TOP;
  var BALL_R = CFG.BALL_R;
  var RUBBER_Z = CFG.RUBBER_Z;
  var BATTER_X = CFG.BATTER_X;


  var IMG = {};

  function reduceMotion() {
    return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  function M() { return MODES[S.mode]; }

  /* 좌타는 1루 쪽(Xw+)에 서므로 몸쪽이 Xw+, 우타는 반대 */
  function insideSign() { return S.bats === "L" ? 1 : -1; }

  /* 카메라 가로 위치(m). panMag가 있으면 타자가 선 쪽 반대로 패닝한다.
     좌우 부호는 insideSign() 하나에서만 나오므로 좌/우타가 정확히 거울상이 된다. */
  function camXOf(m) {
    return (m.panMag === undefined) ? m.cam.X : insideSign() * m.panMag;
  }

  /* ── 월드 → 화면 ─────────────────────────────────────────────────
     ★ 두 시점의 좌우 반전이 일어나는 유일한 지점이 아래 Xc 한 줄이다. ★ */
  function proj(Xw, Yw, Zw) {
    var m = M();
    var Xc = m.dir * (Xw - camXOf(m));
    var Zc = m.dir * (Zw - m.cam.Z);
    var Yc = Yw - m.cam.Y;
    var k = m.F / Zc;
    return { u: SCENE_W * 0.5 + Xc * k, v: SCENE_H * m.cyRatio - Yc * k, z: Zc, k: k };
  }

  function ballRadiusAt(Zc) { return M().F * BALL_R / Zc; }

  /* ── 존 셀 (표준 인덱스 0~8: col 0=바깥쪽·2=몸쪽 / row 0=높은·2=낮은) ── */
  function colEdgeX(col) {
    var s = insideSign();
    return [s * (-PLATE_HALF + 2 * PLATE_HALF * (col / 3)),
            s * (-PLATE_HALF + 2 * PLATE_HALF * ((col + 1) / 3))];
  }
  function cellCenterWorld(idx) {
    var col = idx % 3, row = (idx / 3) | 0;
    return {
      X: insideSign() * (-PLATE_HALF + 2 * PLATE_HALF * ((col + 0.5) / 3)),
      Y: SZ_TOP - (SZ_TOP - SZ_BOT) * ((row + 0.5) / 3),
      Z: PLATE_DEPTH / 2
    };
  }
  function cellRect(idx, Zw) {
    var col = idx % 3, row = (idx / 3) | 0;
    var ex = colEdgeX(col);
    var yT = SZ_TOP - (SZ_TOP - SZ_BOT) * (row / 3);
    var yB = SZ_TOP - (SZ_TOP - SZ_BOT) * ((row + 1) / 3);
    var a = proj(ex[0], yT, Zw), b = proj(ex[1], yB, Zw);
    var x = Math.min(a.u, b.u), w = Math.abs(b.u - a.u);
    var y = Math.min(a.v, b.v), h = Math.abs(b.v - a.v);
    return { x: x, y: y, w: w, h: h, cx: x + w / 2, cy: y + h / 2 };
  }
  /* 존은 플레이트 깊이만큼의 '부피'다. 카메라에 가까운 면을 near로 잡는다. */
  function zoneFaces() {
    var a = proj(0, 0, 0).z, b = proj(0, 0, PLATE_DEPTH).z;
    return a <= b ? { near: 0, far: PLATE_DEPTH } : { near: PLATE_DEPTH, far: 0 };
  }

  /* ── 자체 점검 ───────────────────────────────────────────────────
     셀 0(높은 바깥쪽)은 두 시점에서 화면 반대편에 찍혀야 한다.
     한쪽이라도 같은 편에 찍히면 몸쪽/바깥쪽 추천이 뒤집힌 것이므로 즉시 잡아야 한다.
     콘솔은 실패했을 때만 더럽힌다. window.dsSelfCheck.mirror()로 직접 확인 가능. */
  function mirrorSelfCheck() {
    var keep = S.mode, mid = SCENE_W / 2;
    S.mode = "pitcher"; var a = cellRect(0, 0).cx - mid;
    S.mode = "batter";  var b = cellRect(0, 0).cx - mid;
    S.mode = keep;
    return { ok: a * b < 0, pitcherOffset: Math.round(a), batterOffset: Math.round(b) };
  }
  /* 두 시점에서 공의 원근 방향이 반대인지 확인한다.
     투수 모드는 멀어지며 작아지고(반지름 감소), 타자 모드는 다가오며 커진다(증가). */
  function pitchScaleCheck() {
    var keep = S.mode, res = {};
    ["pitcher", "batter"].forEach(function (mode) {
      S.mode = mode;
      var spin = spinOf("FF"), target = cellCenterWorld(4), r = [];
      [0.2, 0.6, 1.0].forEach(function (t) {
        var p = flightPos(easeApproach(t), target, spin);
        r.push(+ballRadiusAt(proj(p.X, p.Y, p.Z).z).toFixed(2));
      });
      res[mode] = { radii: r, direction: r[2] < r[0] ? "shrinking" : "growing" };
    });
    S.mode = keep;
    res.ok = res.pitcher.direction === "shrinking" && res.batter.direction === "growing";
    return res;
  }

  /* 구종별로 화면에 실제 적용되는 회전값. rpm 순서와 톱스핀 역방향이 유지되는지 본다. */
  function spinCheck() {
    var res = {};
    Object.keys(SPIN).forEach(function (code) {
      var sp = SPIN[code];
      res[code] = {
        rpm: sp.rpm,
        tiltDeg: sp.tilt,
        revPerSec: +(sp.rpm / 700).toFixed(2),
        direction: Math.cos(sp.tilt * Math.PI / 180) >= 0 ? "backspin(+)" : "topspin(-)"
      };
    });
    res.ok = res.ST.revPerSec > res.FF.revPerSec &&
             res.FF.revPerSec > res.FS.revPerSec &&
             res.CU.direction !== res.FF.direction;
    return res;
  }

  /* 누끼 3장이 각 모드에서 실제 몇 px로 그려지는지 */
  function figuresCheck() {
    var keep = S.mode, res = {};
    ["pitcher", "batter"].forEach(function (mode) {
      S.mode = mode;
      renderScene(1);
      res[mode] = JSON.parse(JSON.stringify(lastFigurePx));
      lastFigurePx = {};
    });
    S.mode = keep;
    renderScene(1);
    return res;
  }

  window.dsSelfCheck = {
    mirror: mirrorSelfCheck, pitchScale: pitchScaleCheck, spin: spinCheck,
    figures: figuresCheck
  };

  /* ── 구종별 회전·무브먼트 ────────────────────────────────────────
     rpm·회전축은 컨트롤러가 준 MLB 평균값 그대로다.
     tilt는 시계 표기를 도(°)로: 12시=0, 1시=30, 1시30분=45, 2시30분=75, 3시=90, 7시30분=225.
     화면 회전수는 rpm/700 rev/s로 축소한다 — 실제 2300 rpm은 초당 38회전이라 잔상만 남는다.
     비율은 그대로라 FS(1400)가 가장 느리고 ST(2600)가 가장 빠르며, CU만 톱스핀이라 역방향이다.
     dx/dz는 무회전 직선 대비 휘는 양(m). dx+ = Xw+(1루 쪽, 좌투수 암사이드), dz+ = 덜 떨어짐. */
  var SPIN = {
    FF: { rpm: 2300, tilt:   0, dx:  0.13, dz:  0.42 },
    SI: { rpm: 2150, tilt:  45, dx:  0.36, dz:  0.10 },
    FC: { rpm: 2400, tilt:  30, dx: -0.13, dz:  0.22 },
    SL: { rpm: 2450, tilt:  75, dx: -0.32, dz: -0.06 },
    ST: { rpm: 2600, tilt:  90, dx: -0.58, dz: -0.03 },
    CU: { rpm: 2550, tilt: 225, dx: -0.20, dz: -0.48 },
    CH: { rpm: 1750, tilt:  45, dx:  0.31, dz: -0.13 },
    FS: { rpm: 1400, tilt:   5, dx:  0.06, dz: -0.40 }
  };
  function spinOf(code) { return SPIN[code] || SPIN.FF; }

  /* 좌완 투수의 릴리스. 투수는 우리를 마주보므로 투수의 왼팔은 Xw+(1루) 쪽이다. */
  var RELEASE = { X: 0.55, Y: 1.86, Z: RUBBER_Z - 1.98 };

  /* 조준점을 target-(dx,dz)로 잡고 t²로 휘게 하면 목표에 정확히 도달한다.
     실제 마그누스도 후반에 몰려 나타나므로 t² 가중이 눈에도 맞다. */
  function flightPos(tz, target, spin) {
    var aX = target.X - spin.dx, aY = target.Y - spin.dz;
    var e = tz * tz;
    return {
      X: RELEASE.X + (aX - RELEASE.X) * tz + spin.dx * e,
      Y: RELEASE.Y + (aY - RELEASE.Y) * tz + spin.dz * e,
      Z: RELEASE.Z + (target.Z - RELEASE.Z) * tz
    };
  }
  /* 손을 떠날 때 빠르고 화면을 채울수록 느려 보이게 — 거리 진행을 앞쪽에 몰아준다 */
  function easeApproach(t) { return 1 - Math.pow(1 - t, 2.6); }

  /* ── 야구공 ──────────────────────────────────────────────────────
     실밥 두 줄의 대칭축을 tilt 방향으로 눕혀 회전축이 읽히게 하고, angle만큼 굴린다. */
  function drawBaseball(x, y, r, angle, tiltDeg) {
    if (r < 0.7) { r = 0.7; }
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(angle);
    var g = ctx.createRadialGradient(-r * 0.32, -r * 0.34, r * 0.1, 0, 0, r);
    g.addColorStop(0, "#ffffff");
    g.addColorStop(0.7, "#ffffff");
    g.addColorStop(1, "#e6e1d3");
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(0, 0, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "#6b6555";
    ctx.lineWidth = Math.max(0.4, r * 0.07);
    ctx.stroke();
    if (r >= 2.6) {
      ctx.rotate(tiltDeg * Math.PI / 180);
      ctx.strokeStyle = "#c8102e";
      ctx.lineWidth = Math.max(0.6, r * 0.14);
      ctx.lineCap = "round";
      for (var s = -1; s <= 1; s += 2) {
        ctx.beginPath();
        ctx.moveTo(s * r * 0.60, -r * 0.72);
        ctx.quadraticCurveTo(s * r * 0.14, 0, s * r * 0.60, r * 0.72);
        ctx.stroke();
      }
    }
    ctx.restore();
  }

  /* ── 인물 레이어 ─────────────────────────────────────────────────
     실루엣은 발밑·머리끝을 투영해 얻은 박스 안에 정규 좌표로 그린다
     (인물은 Z 두께가 얇아 박스 근사로 충분하다). */
  /* ── 누끼 인물 레이어 ────────────────────────────────────────────
     각 누끼는 "이미지 전체 높이가 월드 몇 m인가"(worldH)와 "발이 이미지 가로
     어디에 있나"(footFrac)로 배치한다. 타자 누끼는 배트가 머리 위로 삐져나와
     있어 이미지 높이를 곧장 키로 쓰면 사람이 작아진다. 아래는 알파 실측이다.

       cut-batter-front  440x953  머리끝 row 97 / 발 row 952 → 사람이 이미지의 89.7%
                                  → 키 1.85 m 기준 이미지 전체 = 2.062 m, 발 midFrac 0.479
       cut-catcher-front 420x546  사람 97.8% → 앉은키 1.15 m → 이미지 1.176 m, 발 0.504
       cut-pitcher-front 200x552  사람 99.1% → 키 1.90 m    → 이미지 1.917 m, 발 0.615
                                  (레그킥이라 축발이 가운데가 아니다) */
  function figureDepth(Xw, Zw) { return proj(Xw, 0, Zw).z; }

  /* 발을 기준점으로 지면에 세운다. 좌우 반전도 발을 축으로 돌린다 —
     이미지 중심을 축으로 뒤집으면 발이 옆으로 미끄러진다. */
  function drawCutout(img, spec, Xw, flip) {
    var feet = proj(Xw, 0, spec.Z);
    var hpx;
    if (spec.photo) {
      /* 사진 정합 우선: 기하학 대신 배경 사진에 그려진 마운드 축척에 맞춘다.
         (사진의 마운드가 실제보다 약 2.7배 작게 그려져 있다 — 리포트 8-4) */
      hpx = spec.worldH * spec.photo.pxPerMeter;
      feet = { u: spec.photo.u, v: spec.photo.v };
    } else {
      /* hpx/footV는 배경이 실측 대상이 아닐 때(투수 모드는 필드를 코드로 그린다)
         쓰는 화면 좌표 고정값이다. 가로 위치(u)는 건드리지 않고 그대로 proj()에서
         받는다 — 좌우 반전이 여전히 proj() 한 곳에서만 일어나게 하려는 것이다. */
      hpx = (spec.hpx !== undefined) ? spec.hpx : M().F * spec.worldH / feet.z;
      if (spec.footV !== undefined) { feet = { u: feet.u, v: spec.footV }; }
    }
    var wpx = hpx * (img.naturalWidth / img.naturalHeight);
    ctx.save();
    ctx.globalAlpha = spec.alpha === undefined ? 1 : spec.alpha;
    ctx.translate(feet.u, 0);
    if (flip) { ctx.scale(-1, 1); }
    ctx.drawImage(img, -wpx * spec.footFrac, feet.v - hpx, wpx, hpx);
    ctx.restore();
    return { w: Math.round(wpx), h: Math.round(hpx) };
  }

  /* 누끼의 좌우 반전은 여기 한 곳에서만 결정한다.
     - 타자 : cut-batter-front.png 원본이 좌타자다. 배팅 글러브 낀 손이 이미지
              오른쪽(= 그 사람의 왼쪽 어깨)에 얹혀 있고, 뒤쪽 어깨가 왼쪽이라는 건
              오른쪽 어깨가 투수를 향한다는 뜻이다. 그래서 우타일 때만 뒤집는다.
              (서는 위치는 별개다 — 좌타는 1루 쪽이라 투수 시점에서 화면 왼쪽이다.)
     - 투수 : Rodón이 좌투라 항상 뒤집는다
     - 포수 : 정면이고 좌우 대칭에 가까워 뒤집지 않는다 */
  function figureFlip(spec) {
    if (spec.key === "pitcherFront") { return true; }
    if (spec.key === "batterFront") { return S.bats === "R"; }
    return false;
  }

  var lastFigurePx = {};   /* 실제 렌더 크기(px). dsSelfCheck.figures()로 읽는다. */

  function drawFigure(spec) {
    if (!spec || spec.off) { return null; }
    var img = IMG[spec.key];
    if (!img) { return null; }   /* 로드 전에는 그리지 않는다 (빈 사람 프레임 방지) */
    var Xw = (spec.X !== undefined) ? spec.X : insideSign() * (spec.Xmag || BATTER_X);
    lastFigurePx[spec.key] = drawCutout(img, spec, Xw, figureFlip(spec));
    return lastFigurePx[spec.key];
  }

  /* ── 코드 스탠드인 배경 (이미지 슬롯이 비었을 때만) ───────────── */
  function drawBackdrop() {
    var m = M();
    var hz = SCENE_H * m.cyRatio;

    ctx.fillStyle = "#f4f2ec";
    ctx.fillRect(0, 0, SCENE_W, SCENE_H);
    if (drawBackgroundImage()) { return; }   /* 사진이 있으면 지면·플레이트는 사진 것을 쓴다 */

    /* 먼 배경(백스톱·외야벽)은 수평선 위 어두운 띠로 눌러 준다 */
    ctx.fillStyle = "#14203c";
    ctx.globalAlpha = 0.14;
    ctx.fillRect(0, Math.max(0, hz - 46), SCENE_W, 46);
    ctx.globalAlpha = 1;

    /* 잔디 → 내야 흙 */
    var grassEdge = proj(0, 0, m.dir > 0 ? 30 : -12).v;
    ctx.fillStyle = "#1f8a4c";
    ctx.globalAlpha = 0.20;
    ctx.fillRect(0, hz, SCENE_W, Math.max(0, grassEdge - hz));
    ctx.globalAlpha = 1;
    ctx.fillStyle = "#e6e1d3";
    ctx.fillRect(0, Math.max(hz, grassEdge), SCENE_W, SCENE_H);

    /* 마운드 — 타자 모드에서만 정면으로 보인다 */
    if (S.mode === "batter") {
      var mZ = RUBBER_Z - 0.5;
      var mC = proj(0, 0.25, mZ);
      var mHalf = m.F * 2.74 / (mZ + 2.198);
      ctx.fillStyle = "#f7f5ef";
      ctx.beginPath();
      ctx.ellipse(mC.u, mC.v + 2, mHalf, Math.max(2.5, mHalf * 0.17), 0, 0, Math.PI * 2);
      ctx.fill();
      var r1 = proj(-0.305, 0.25, RUBBER_Z), r2 = proj(0.305, 0.25, RUBBER_Z);
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(r1.u, r1.v - 1.5, r2.u - r1.u, 2.5);
    }

    /* 타석 초크 라인 (양쪽 박스) */
    var bz0 = PLATE_DEPTH / 2 - 0.914, bz1 = PLATE_DEPTH / 2 + 0.914;
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 1.6;
    ctx.globalAlpha = 0.7;
    [0.368, 1.587, -0.368, -1.587].forEach(function (x) {
      var a = proj(x, 0, bz0), b = proj(x, 0, bz1);
      ctx.beginPath(); ctx.moveTo(a.u, a.v); ctx.lineTo(b.u, b.v); ctx.stroke();
    });
    [bz0, bz1].forEach(function (z) {
      [[0.368, 1.587], [-1.587, -0.368]].forEach(function (seg) {
        var a = proj(seg[0], 0, z), b = proj(seg[1], 0, z);
        ctx.beginPath(); ctx.moveTo(a.u, a.v); ctx.lineTo(b.u, b.v); ctx.stroke();
      });
    });
    ctx.globalAlpha = 1;

    drawPlate();
  }

  /* 홈플레이트 — 꼭짓점은 항상 포수 쪽(Zw=0)이다.
     투수 모드에서는 평평한 앞변이, 타자 모드에서는 뾰족한 끝이 카메라를 향한다. */
  function drawPlate() {
    var pts = [proj(0, 0, 0),
               proj(-PLATE_HALF, 0, PLATE_HALF),
               proj(-PLATE_HALF, 0, PLATE_DEPTH),
               proj(PLATE_HALF, 0, PLATE_DEPTH),
               proj(PLATE_HALF, 0, PLATE_HALF)];
    ctx.beginPath();
    ctx.moveTo(pts[0].u, pts[0].v);
    for (var i = 1; i < pts.length; i++) { ctx.lineTo(pts[i].u, pts[i].v); }
    ctx.closePath();
    ctx.fillStyle = "#ffffff";
    ctx.fill();
    ctx.strokeStyle = "#14203c";
    ctx.lineWidth = 1.6;
    ctx.globalAlpha = 0.5;
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  /* ── 존 프리즘 ───────────────────────────────────────────────────
     존 평면 자체는 시선축과 나란해 사다리꼴이 되지 않는다. 그래서 실제
     스트라이크존이 '플레이트 깊이만큼의 부피'라는 점을 살려 근접면과 원접면을
     잇는 상자로 그린다 → 소실점을 향한 원근이 눈에 보인다. */
  function drawZonePrism(targetIdx) {
    var f = zoneFaces();
    var nT = proj(0, SZ_TOP, f.near), nB = proj(0, SZ_BOT, f.near);
    var nx = [proj(colEdgeX(0)[0], 0, f.near).u, proj(colEdgeX(2)[1], 0, f.near).u];
    var fx = [proj(colEdgeX(0)[0], 0, f.far).u, proj(colEdgeX(2)[1], 0, f.far).u];
    var fT = proj(0, SZ_TOP, f.far), fB = proj(0, SZ_BOT, f.far);
    var nL = Math.min(nx[0], nx[1]), nR = Math.max(nx[0], nx[1]);
    var fL = Math.min(fx[0], fx[1]), fR = Math.max(fx[0], fx[1]);

    ctx.strokeStyle = "#14203c";
    ctx.globalAlpha = 0.30;
    ctx.lineWidth = 1;
    [[nL, nT.v, fL, fT.v], [nR, nT.v, fR, fT.v],
     [nL, nB.v, fL, fB.v], [nR, nB.v, fR, fB.v]].forEach(function (L) {
      ctx.beginPath(); ctx.moveTo(L[0], L[1]); ctx.lineTo(L[2], L[3]); ctx.stroke();
    });
    ctx.strokeRect(fL, fT.v, fR - fL, fB.v - fT.v);
    ctx.globalAlpha = 1;

    /* 인물·사진이 뒤에 깔리면 격자가 묻힌다. 셀 틴트 전에 얇은 흰 스크림을 깔아
       존 영역만 한 톤 띄운다. 셀별 의미(초록/앰버)는 그대로 위에 얹힌다. */
    ctx.fillStyle = "#ffffff";
    ctx.globalAlpha = 0.30;
    ctx.fillRect(nL, nT.v, nR - nL, nB.v - nT.v);
    ctx.globalAlpha = 1;

    for (var i = 0; i < 9; i++) {
      var r = cellRect(i, f.near), h = heatOf(i);
      if (h > 0.15) { ctx.fillStyle = "#b8860b"; ctx.globalAlpha = h * 0.34; }
      else if (h < -0.15) { ctx.fillStyle = "#1f8a4c"; ctx.globalAlpha = Math.abs(h) * 0.26; }
      else { ctx.fillStyle = "#f7f5ef"; ctx.globalAlpha = 0.26; }
      ctx.fillRect(r.x, r.y, r.w, r.h);
      ctx.globalAlpha = 0.55;
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 1;
      ctx.strokeRect(r.x, r.y, r.w, r.h);
      ctx.globalAlpha = 1;
    }

    /* 목표 칸 — 근접면을 채우고 원접면까지 터널로 이어 깊이를 준다 */
    var tn = cellRect(targetIdx, f.near), tf = cellRect(targetIdx, f.far);
    ctx.fillStyle = "#c8102e";
    ctx.globalAlpha = 0.20;
    [[tn.y, tf.y], [tn.y + tn.h, tf.y + tf.h]].forEach(function (e) {
      ctx.beginPath();
      ctx.moveTo(tn.x, e[0]); ctx.lineTo(tf.x, e[1]);
      ctx.lineTo(tf.x + tf.w, e[1]); ctx.lineTo(tn.x + tn.w, e[0]);
      ctx.closePath(); ctx.fill();
    });
    ctx.globalAlpha = 0.8;
    ctx.fillRect(tn.x, tn.y, tn.w, tn.h);
    ctx.globalAlpha = 1;
    ctx.strokeStyle = "#c8102e";
    ctx.lineWidth = 2;
    ctx.strokeRect(tn.x, tn.y, tn.w, tn.h);

    ctx.strokeStyle = "#14203c";
    ctx.lineWidth = 2.5;
    ctx.strokeRect(nL, nT.v, nR - nL, nB.v - nT.v);

    /* 존 아래 모서리에서 플레이트 같은 X의 지면까지 수직 낙하선.
       존 하단이 지면 0.457 m라 그냥 두면 공중에 뜬 것처럼 보인다. */
    ctx.strokeStyle = "#14203c";
    ctx.globalAlpha = 0.22;
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    [colEdgeX(0)[0], colEdgeX(2)[1]].forEach(function (x) {
      var a = proj(x, SZ_BOT, f.near), b = proj(x, 0, f.near);
      ctx.beginPath(); ctx.moveTo(a.u, a.v); ctx.lineTo(b.u, b.v); ctx.stroke();
    });
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;

    return { L: nL, R: nR, T: nT.v, B: nB.v, face: f.near };
  }

  /* 라벨은 투영된 셀 중심에서 위치를 뽑으므로 시점이 바뀌면 자동으로 따라간다 */
  function drawZoneLabels(box) {
    ctx.save();
    ctx.font = "700 11px -apple-system, BlinkMacSystemFont, 'Apple SD Gothic Neo', sans-serif";
    ctx.textBaseline = "middle";
    /* 라벨이 인물·사진 위에 오므로 흰 테두리를 둘러 배경과 무관하게 읽히게 한다 */
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 3;
    ctx.lineJoin = "round";
    ctx.fillStyle = "#14203c";
    function label(t, x, y) {
      ctx.globalAlpha = 0.9;
      ctx.strokeText(t, x, y);
      ctx.globalAlpha = 1;
      ctx.fillText(t, x, y);
    }
    /* 행 라벨은 존의 '타자 쪽'에 붙인다. 투수 모드는 카메라를 패닝해 존이 화면
       가장자리로 가므로(camXOf), 늘 왼쪽에 두면 우타에서 라벨이 캔버스 밖으로 잘린다.
       패닝이 없는 타자 모드는 지금까지대로 항상 왼쪽이다. */
    var rowRight = M().panMag !== undefined && insideSign() < 0;
    ctx.textAlign = rowRight ? "left" : "right";
    ["높은", "가운데", "낮은"].forEach(function (t, r) {
      label(t, rowRight ? box.R + 7 : box.L - 7, cellRect(r * 3, box.face).cy);
    });
    ctx.textAlign = "center";
    ["바깥쪽", "한가운데", "몸쪽"].forEach(function (t, i) {
      label(t, cellRect(6 + i, box.face).cx, box.B + 13);
    });
    ctx.restore();
  }

  function drawGuide(target, spin) {
    ctx.save();
    ctx.strokeStyle = "#c8102e";
    ctx.globalAlpha = 0.28;
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    for (var i = 0; i <= 44; i++) {
      var p = flightPos(i / 44, target, spin);
      var s = proj(p.X, p.Y, p.Z);
      if (i === 0) { ctx.moveTo(s.u, s.v); } else { ctx.lineTo(s.u, s.v); }
    }
    ctx.stroke();
    ctx.restore();
  }

  /* ── 프레임 ───────────────────────────────────────────────────── */
  var resizeBound = false;
  var anim = { raf: 0, start: 0, dur: 840, idx: 0, code: "FF" };

  function drawBallAt(t, spin, target) {
    var tz = easeApproach(t);
    var pos = flightPos(tz, target, spin);
    var s = proj(pos.X, pos.Y, pos.Z);
    var dir = Math.cos(spin.tilt * Math.PI / 180) >= 0 ? 1 : -1;
    var angle = dir * 2 * Math.PI * (spin.rpm / 700) * (t * anim.dur / 1000);

    for (var k = 9; k >= 1; k--) {
      var tb = t - k * 0.028;
      if (tb <= 0) { continue; }
      var pb = flightPos(easeApproach(tb), target, spin);
      var sb = proj(pb.X, pb.Y, pb.Z);
      if (sb.z <= 0.05) { continue; }
      ctx.globalAlpha = 0.16 * (1 - k / 10);
      ctx.fillStyle = "#c8102e";
      ctx.beginPath();
      ctx.arc(sb.u, sb.v, Math.max(0.5, ballRadiusAt(sb.z) * 0.9), 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    if (s.z > 0.05) { drawBaseball(s.u, s.v, ballRadiusAt(s.z), angle, spin.tilt); }
    return s.z;
  }

  function renderScene(t) {
    var m = M();
    ctx.clearRect(0, 0, SCENE_W, SCENE_H);
    drawBackdrop();

    var spin = spinOf(anim.code);
    var target = cellCenterWorld(anim.idx);

    /* 그리는 순서: 원경 인물 → (공) → 근경 인물 → 존 → (공) → 라벨 */
    drawFigure(m.far);

    var nearXw = (m.near.X !== undefined) ? m.near.X
               : insideSign() * (m.near.Xmag || BATTER_X);
    /* 근경 인물이 없으면 공이 무언가 뒤로 갈 일이 없으므로 무한대로 둔다 */
    var nearZ = m.near.off ? Infinity : figureDepth(nearXw, m.near.Z);
    var ballZ = proj(0, 0, flightPos(easeApproach(t), target, spin).Z).z;
    var ballBehind = ballZ > nearZ;

    drawGuide(target, spin);
    if (ballBehind) { drawBallAt(t, spin, target); }
    drawFigure(m.near);

    /* 존은 방송 그래픽처럼 인물 위에 얹는다. 인물 뒤에 두면 타자 몸이 격자를 가린다. */
    var box = drawZonePrism(anim.idx);
    if (!ballBehind) { drawBallAt(t, spin, target); }

    drawZoneLabels(box);
  }

  function playPitch() {
    if (anim.raf) { window.cancelAnimationFrame(anim.raf); anim.raf = 0; }
    if (reduceMotion()) { renderScene(1); return; }
    anim.start = 0;
    function step(ts) {
      if (!anim.start) { anim.start = ts; }
      var t = Math.min(1, (ts - anim.start) / anim.dur);
      renderScene(t);
      if (t < 1) { anim.raf = window.requestAnimationFrame(step); }
      else { anim.raf = 0; }
    }
    anim.raf = window.requestAnimationFrame(step);
  }

  function sizeCanvas() {
    var dpr = Math.min(3, window.devicePixelRatio || 1);
    cv.width = Math.round(SCENE_W * dpr);
    cv.height = Math.round(SCENE_H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  /* 존이 화면상 좌우 반전됐는지(투수 모드) 투영 결과로 직접 판정한다.
     패드의 열 순서를 여기에 맞춰야 화면과 손이 어긋나지 않는다. */
  function zoneMirrored() {
    var face = zoneFaces().near;
    return cellRect(0, face).cx > cellRect(2, face).cx;
  }

  function heatWord(i) {
    return heatOf(i) > 0.15 ? "타자가 강한 코스"
         : heatOf(i) < -0.15 ? "타자가 약한 코스" : "보통";
  }

  /* 44px 이상을 보장하는 실제 조작·접근성 컨트롤.
     존 셀은 원근 투영이라 모바일에서 30px 아래로 내려가 탭 타깃이 될 수 없다. */
  function layoutCells() {
    var pad = $("coursePad");
    var mirrored = zoneMirrored();
    var html = '<span class="ds-coursepad__cap">코스 미리보기</span>';
    for (var row = 0; row < 3; row++) {
      for (var c = 0; c < 3; c++) {
        var i = row * 3 + (mirrored ? (2 - c) : c);
        html += '<button type="button" class="ds-coursebtn' +
          (i === anim.idx ? " is-on" : "") + '" data-cell="' + i +
          '" aria-pressed="' + (i === anim.idx ? "true" : "false") +
          '" aria-label="' + CELL_NAME[i] + " — " + heatWord(i) + '. 이 코스로 던져보기">' +
          CELL_NAME[i].replace(" ", "<br>") + "</button>";
      }
    }
    pad.innerHTML = html;
  }

  /* 코스를 고르면 그 코스로 던지는 장면을 재생한다.

     anim.idx가 존 프리즘과 공 궤적의 목표 칸이다. 예전에는 여기서 쓰이지 않는 변수만
     바꾸고 anim.idx를 안 건드려서, 버튼을 눌러도 같은 장면을 다시 그릴 뿐이었다.
     버튼도 눌린 티가 안 났다 - is-on과 aria-pressed가 anim.idx를 보기 때문이다. */
  function pickCell(i) {
    anim.idx = i;
    layoutCells();
    playPitch();
  }

  function bindPointerHandlers() {
  $("coursePad").addEventListener("click", function (ev) {
    var b = ev.target.closest ? ev.target.closest(".ds-coursebtn") : null;
    if (b) { pickCell(parseInt(b.getAttribute("data-cell"), 10)); }
  });

  /* 그림 위를 직접 눌러도 되게 하는 보조 경로(마우스). 좌표 → 셀 히트테스트. */
  $("sceneCells").addEventListener("click", function (ev) {
    var r = ev.currentTarget.getBoundingClientRect();
    var x = (ev.clientX - r.left) / r.width * SCENE_W;
    var y = (ev.clientY - r.top) / r.height * SCENE_H;
    var face = zoneFaces().near;
    for (var i = 0; i < 9; i++) {
      var c = cellRect(i, face);
      if (x >= c.x && x <= c.x + c.w && y >= c.y && y <= c.y + c.h) { pickCell(i); return; }
    }
  });
  }

  /* 배경 이미지 + 누끼 인물 로딩. 없으면 조용히 스탠드인으로 남는다. */
  function loadAssets() {
    var pending = 0;
    Object.keys(ASSETS).forEach(function (k) {
      if (!ASSETS[k]) { return; }
      var im = new Image();
      pending++;
      im.onload = function () {
        IMG[k] = im;
        /* 마지막 한 장까지 들어온 뒤 한 번만 다시 그린다 (장마다 재생하면 애니가 끊긴다) */
        if (--pending === 0) { render(); } else { renderScene(1); }
      };
      im.onerror = function () { IMG[k] = null; if (--pending === 0) { render(); } };
      im.src = ASSETS[k];
    });
  }
  /* 배경 래스터를 캔버스에 직접 crop 해 그린다. CSS object-fit보다 정확하고,
     bgCrop 사각형이 카메라 해와 한 세트로 묶여 있어 정렬이 어긋날 여지가 없다. */
  function drawBackgroundImage() {
    var m = M();
    var img = IMG[m.bgKey];
    if (!img) { return false; }
    var c = m.bgCrop;
    if (c) { ctx.drawImage(img, c.sx, c.sy, c.sw, c.sh, 0, 0, SCENE_W, SCENE_H); }
    else { ctx.drawImage(img, 0, 0, SCENE_W, SCENE_H); }
    return true;
  }

  /* ------------------------------------------------------------------
     결과 패널 렌더
     ------------------------------------------------------------------ */

  /* ------------------------------------------------------------------
     외부 진입점 — Gradio가 부른다
     ------------------------------------------------------------------ */

  /* 씬 1회 갱신. 목업의 render()는 램프·주자·패널까지 다 그렸지만, 앱에서는
     그쪽이 전부 Python(ui/console.py, ui/result_panel.py)의 몫이라 씬만 남았다. */
  function render() {
    if (!mounted) { return; }
    layoutCells();
    renderScene(1);
  }

  /* Gradio는 head= 스크립트를 앱 렌더 이전에 실행한다. 그래서 캔버스를 잡는 일과
     리스너 바인딩을 여기로 미룬다. 캔버스가 아직 없으면 다음 프레임에 다시 본다. */
  function mount() {
    var canvas = $("sceneCanvas");
    if (!canvas || !$("coursePad") || !$("sceneCells")) { return false; }
    /* mounted 플래그만 보고 빠져나가면 안 된다. Gradio가 이 블록을 다시 렌더하면
       canvas 엘리먼트가 통째로 교체되는데, 그러면 엔진은 DOM에서 떨어져 나간 옛
       canvas에 계속 그린다. 코스 패드는 그릴 때마다 새로 찾으니 멀쩡하고 그림만
       안 나오는, 원인을 짐작하기 어려운 상태가 된다. 실제로 분석 실행 직후 이렇게 됐다. */
    if (mounted && cv === canvas) { return true; }
    cv = canvas;
    ctx = cv.getContext("2d");
    mounted = true;
    sizeCanvas();
    bindPointerHandlers();
    loadAssets();
    if (!resizeBound) {
      resizeBound = true;
      window.addEventListener("resize", function () { sizeCanvas(); renderScene(1); });
    }
    return true;
  }

  function update(payload) {
    if (!payload) { return; }
    if (!mount()) {
      window.requestAnimationFrame(function () { update(payload); });
      return;
    }
    S.mode = payload.mode === "batter" ? "batter" : "pitcher";
    S.bats = payload.bats === "R" ? "R" : "L";
    if (payload.cells && payload.cells.length === 9) { cells = payload.cells.slice(); }
    if (typeof payload.target === "number") { anim.idx = payload.target; }
    render();

    /* 몸쪽/바깥쪽 반전 점검. 통과하면 조용하고, 깨지면 콘솔에 남긴다. */
    var chk = mirrorSelfCheck();
    if (!chk.ok) {
      window.console.warn("[DiamondScout] 존 좌우 반전 점검 실패 — " +
        "두 시점에서 같은 쪽에 그려지고 있습니다.", chk);
    }
  }

  /* 첫 화면을 그린다. update()는 분석 실행 결과가 올 때만 불리는데, 그 전까지
     #coursePad가 빈 div로 남아 버튼이 하나도 없다. 영역은 CSS로 보이니까 사용자
     눈에는 눌리지 않는 고장난 컨트롤로 보인다.

     데이터는 중립이다(cells가 전부 0이라 히트맵 색이 안 붙는다). 존과 코스 버튼만
     먼저 나오고, 분석을 돌리면 update()가 같은 자리에 실제 값을 채운다.

     Gradio가 DOM을 붙이기 전에 이 스크립트가 먼저 돌므로 프레임을 넘겨가며 기다린다.
     무한 재시도는 하지 않는다 - 씬이 없는 페이지에서 rAF 루프가 계속 도는 걸 막는다. */
  function bootstrap(tries) {
    if (mount()) { render(); return; }
    if (tries > 0) {
      window.requestAnimationFrame(function () { bootstrap(tries - 1); });
    }
  }
  bootstrap(180);

  window.dsScene = {
    mount: mount,
    update: update,
    play: function () { if (mounted) { playPitch(); } },
    selfCheck: function () {
      return {
        mirror: mirrorSelfCheck(),
        pitchScale: pitchScaleCheck(),
        spin: spinCheck(),
        figures: figuresCheck()
      };
    }
  };
})();
