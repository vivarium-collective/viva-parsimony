// vr.js — WebXR ("View in VR") support for the parsimony 3D cell viewer.
//
// Adds immersive-VR viewing (Meta Quest browser, and any WebXR `immersive-vr`
// runtime) to the existing three.js scene without disturbing the desktop path:
//
//   • A "View in VR" button that is disabled until the browser reports a
//     compatible headset (`navigator.xr.isSessionSupported('immersive-vr')`),
//     then enters/exits the session on click.
//   • A "player" dolly that holds the camera in VR. The whole-cell model is in
//     Ångström coordinates (~20,000 Å across) while WebXR head-tracking is in
//     metres, so we scale + place the dolly to present the cell at a comfortable
//     size and let head movement explore it.
//   • Grab navigation (primary): hold grip or trigger and move your hand to
//     drag the whole world — pull a controller toward you to reel the cell in.
//     Grab with both hands and pull them apart to scale the cell up until you
//     are standing inside the cytoplasm (push together to shrink back out).
//   • Controller thumbstick locomotion (secondary): left stick flies (head-
//     relative), right stick X snap-turns, right stick Y scales the world.
//   • Exit: the B (right) / Y (left) face button ends the session from inside
//     the headset (the desktop "Exit VR" button is unreachable while immersed).
//
// The desktop OrbitControls / keyboard path is suspended for the duration of an
// XR session and restored on exit.

import * as THREE from "three";
import { resolveGrab, makeMotionGate, vignetteIntensity } from "./vr-helpers.js";

// --- VR scene framing (Ångström units) ---------------------------------------
// WORLD_SCALE: Å per "head metre". 1500 makes the ~20,000 Å cell read like a
// ~13 m room-sized object with sensible stereo depth; the right stick tunes it.
const WORLD_SCALE = 1500;
const START_BACK = 16000;     // Å the player starts back from cell centre (z+)
const FLY_SPEED = 0.7;        // head-metres / second at full stick deflection (gentler; grab is primary)
const SCALE_RATE = 0.6;       // world-scale change / second at full deflection
const SCALE_MIN = 150;        // clamp world scale so you can't shrink/grow into black
                             // (lower = cell can grow bigger → deeper "inside")
// Å per head-metre at the most "shrunk" end. The cell is ~20,000 Å, so
// S=200,000 puts the whole cell at ~0.1 m — a small object you can hold in front
// of you and turn over. (Was 9,000 ≈ 2 m, which only let it shrink to room-size.)
const SCALE_MAX = 200000;
const SNAP_ANGLE = Math.PI / 6;  // 30° comfort snap-turn (right stick X)
const DEADZONE = 0.18;

export function initVR({ renderer, scene, camera, button, onEnter, onExit }) {
  renderer.xr.enabled = true;

  // Player rig: camera lives under this in XR so we can move/scale the user
  // through the (huge, Å-scale) world. The headset drives the camera's local
  // pose; we drive the dolly.
  const dolly = new THREE.Group();
  dolly.name = "vr-dolly";

  const controllers = [renderer.xr.getController(0), renderer.xr.getController(1)];
  for (const c of controllers) {
    // Stash the live XRInputSource so we can read its gamepad buttons (grip /
    // trigger = "grab") and handedness each frame.
    c.addEventListener("connected", (e) => { c.userData.inputSource = e.data; });
    c.addEventListener("disconnected", () => { c.userData.inputSource = null; });
    // WebXR action EVENTS (select = trigger/pinch, squeeze = grip) are delivered
    // through a different path than gamepad button polling, and keep working on
    // Quest browser builds where the gamepad buttons/axes are frozen. Drive grab
    // from these so grab-to-drag works without any gamepad state.
    c.addEventListener("selectstart", () => { c.userData.selecting = true; });
    c.addEventListener("selectend", () => { c.userData.selecting = false; });
    c.addEventListener("squeezestart", () => { c.userData.squeezing = true; });
    c.addEventListener("squeezeend", () => { c.userData.squeezing = false; });
    dolly.add(c);
  }

  // Comfort vignette: a head-locked quad with a radial-alpha shader. Opacity is
  // driven each frame by smooth-motion magnitude (0 while still or grabbing).
  const vignetteMat = new THREE.ShaderMaterial({
    transparent: true, depthTest: false, depthWrite: false,
    uniforms: { uOpacity: { value: 0 } },
    vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`,
    fragmentShader: `
      varying vec2 vUv; uniform float uOpacity;
      void main(){
        float d = distance(vUv, vec2(0.5));
        float a = smoothstep(0.30, 0.50, d) * uOpacity;
        gl_FragColor = vec4(0.0, 0.0, 0.0, a);
      }`,
  });
  const vignette = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), vignetteMat);
  vignette.frustumCulled = false;
  vignette.renderOrder = 9999;
  vignette.visible = false;

  // One-shot controls hint: a head-anchored label drawn from a canvas texture.
  function makeHintTexture() {
    const c = document.createElement("canvas");
    c.width = 1024; c.height = 256;
    const x = c.getContext("2d");
    x.fillStyle = "rgba(10,12,18,0.82)";
    roundRect(x, 0, 0, c.width, c.height, 28); x.fill();
    x.fillStyle = "#eaf0ff";
    x.font = "600 44px system-ui, sans-serif";
    x.textAlign = "center"; x.textBaseline = "middle";
    x.fillText("Grab to move  ·  Two hands to zoom", c.width / 2, 92);
    x.fillText("Right stick to turn  ·  Face button to exit", c.width / 2, 168);
    const t = new THREE.CanvasTexture(c);
    t.anisotropy = 4;
    return t;
  }
  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }
  const hintMat = new THREE.MeshBasicMaterial({
    map: makeHintTexture(), transparent: true, depthTest: false, depthWrite: false,
  });
  const hint = new THREE.Mesh(new THREE.PlaneGeometry(0.8, 0.2), hintMat);
  hint.position.set(0, -0.25, -1.0); // head-anchored, slightly below center, 1 m out
  hint.renderOrder = 9998;
  hint.frustumCulled = false;
  hint.visible = false;
  let hintHideAt = 0;

  // Shown when the session delivers HAND input instead of controllers: our
  // grip/trigger/thumbstick controls cannot read hands, so say so explicitly
  // rather than leaving every control silently dead.
  const handWarnCanvas = document.createElement("canvas");
  handWarnCanvas.width = 1024; handWarnCanvas.height = 256;
  {
    const x = handWarnCanvas.getContext("2d");
    x.fillStyle = "rgba(45,12,12,0.92)";
    roundRect(x, 0, 0, 1024, 256, 28); x.fill();
    x.fillStyle = "#ffd9d9";
    x.textAlign = "center"; x.textBaseline = "middle";
    x.font = "600 44px system-ui, sans-serif";
    x.fillText("Hand tracking detected", 512, 70);
    x.font = "500 32px system-ui, sans-serif";
    x.fillText("Pick up your Touch controllers for full controls", 512, 140);
    x.fillText("(or pinch thumb + index to drag the cell)", 512, 190);
  }
  const handWarnMat = new THREE.MeshBasicMaterial({
    map: new THREE.CanvasTexture(handWarnCanvas), transparent: true, depthTest: false, depthWrite: false });
  const handWarn = new THREE.Mesh(new THREE.PlaneGeometry(0.85, 0.21), handWarnMat);
  handWarn.position.set(0, 0.18, -1.0);
  handWarn.renderOrder = 9998;
  handWarn.frustumCulled = false;
  handWarn.visible = false;

  // ── TEMP input diagnostic HUD (gated behind ?vrdebug; remove after debugging) ─
  // Live readout of WebXR input state, head-locked, so we can see ON-DEVICE
  // whether controllers/gamepads are being delivered when controls don't respond.
  const DEBUG_INPUT = new URLSearchParams(location.search).has("vrdebug");
  const dbgCanvas = document.createElement("canvas");
  dbgCanvas.width = 1024; dbgCanvas.height = 512;
  const dbgCtx = dbgCanvas.getContext("2d");
  const dbgTex = new THREE.CanvasTexture(dbgCanvas);
  const dbgMesh = new THREE.Mesh(
    new THREE.PlaneGeometry(0.9, 0.45),
    new THREE.MeshBasicMaterial({ map: dbgTex, transparent: true, depthTest: false, depthWrite: false }));
  dbgMesh.position.set(0, 0.0, -0.9);
  dbgMesh.renderOrder = 10000;
  dbgMesh.frustumCulled = false;
  dbgMesh.visible = false;
  let _dbgLast = 0;
  let _dbgFrames = 0;
  let _dbgFps = 0;
  let _sessSel = 0, _sessSqz = 0;  // session-level select/squeeze event counts
  function updateDebugHUD(now, dt) {
    if (!DEBUG_INPUT) return;
    _dbgFrames++;                         // counts EVERY frame updateVR runs
    if (dt > 0) _dbgFps += (1 / dt - _dbgFps) * 0.1;  // smoothed fps
    if (now - _dbgLast < 150) return;     // throttle redraw only
    _dbgLast = now;
    const lines = [];
    const srcs = (session && session.inputSources) ? Array.from(session.inputSources) : [];
    lines.push(`fps≈${_dbgFps.toFixed(0)} frames=${_dbgFrames} t=${(now / 1000).toFixed(1)}s inputSources=${srcs.length}`);
    // Cross-check the standard Gamepad API (separate from XR input sources):
    const ngp = (navigator.getGamepads && navigator.getGamepads()) || [];
    const real = Array.from(ngp).filter(Boolean);
    const navPressed = real.map(g => (g.buttons || []).map((b, j) => b.pressed ? j : null).filter(v => v !== null).join(",")).join(" | ");
    lines.push(`navGamepads=${real.length} pressed=[${navPressed}]`);
    srcs.forEach((s, i) => {
      const gp = s.gamepad;
      const pressed = gp && gp.buttons ? gp.buttons.map((b, j) => (b.pressed || b.value > 0.1) ? j : null).filter(v => v !== null).join(",") : "-";
      const ax = gp && gp.axes ? Array.from(gp.axes).map(a => a.toFixed(2)).join(" ") : "-";
      lines.push(`#${i} ${s.handedness || "?"} ray=${s.targetRayMode || "?"} gp=${gp ? ("btn" + (gp.buttons ? gp.buttons.length : 0)) : "NULL"} hand=${s.hand ? "Y" : "N"} prof=${(s.profiles && s.profiles[0]) || "?"}`);
      lines.push(`   pressed=[${pressed}] axes=[${ax}]`);
    });
    lines.push(`ctrl0.src=${controllers[0].userData.inputSource ? "Y" : "N"} ctrl1.src=${controllers[1].userData.inputSource ? "Y" : "N"}`);
    const ev = (c) => `${c.userData.selecting ? "S" : "-"}${c.userData.squeezing ? "Q" : "-"}`;
    lines.push(`EVENTS  ctrl0=${ev(controllers[0])} ctrl1=${ev(controllers[1])}  (S=select/trigger Q=squeeze/grip)`);
    lines.push(`vis=${session ? session.visibilityState : "-"} sessSel=${_sessSel} sessSqz=${_sessSqz} grab L=${_grab.left ? 1 : 0} R=${_grab.right ? 1 : 0}`);
    const hh = (c) => (c.userData.inputSource && c.userData.inputSource.handedness) || "?";
    const pp = (c) => `${c.position.x.toFixed(2)},${c.position.y.toFixed(2)},${c.position.z.toFixed(2)}`;
    lines.push(`c0 ${hh(controllers[0])} pos=${pp(controllers[0])}`);
    lines.push(`c1 ${hh(controllers[1])} pos=${pp(controllers[1])}`);
    dbgCtx.fillStyle = "rgba(0,0,0,0.85)";
    dbgCtx.fillRect(0, 0, dbgCanvas.width, dbgCanvas.height);
    dbgCtx.fillStyle = "#3f6";
    dbgCtx.font = "26px monospace";
    dbgCtx.textBaseline = "top";
    lines.forEach((ln, i) => dbgCtx.fillText(ln, 14, 12 + i * 32));
    dbgTex.needsUpdate = true;
  }

  // ── support detection → button state ──────────────────────────────────────
  function setButton(state, label, title) {
    if (!button) return;
    button.dataset.vrState = state;
    button.textContent = label;
    button.disabled = state === "unavailable";
    button.title = title || "";
  }

  if (!("xr" in navigator) || !navigator.xr) {
    setButton("unavailable", "VR unavailable", "This browser has no WebXR support.");
  } else {
    setButton("checking", "View in VR", "Checking for a headset…");
    navigator.xr.isSessionSupported("immersive-vr").then((ok) => {
      if (ok) setButton("ready", "View in VR", "Enter immersive VR");
      else setButton("unavailable", "VR unavailable", "No compatible VR headset detected.");
    }).catch(() => {
      setButton("unavailable", "VR unavailable", "No compatible VR headset detected.");
    });
    // Headsets can be connected after load — re-check on device change.
    navigator.xr.addEventListener?.("devicechange", () => {
      navigator.xr.isSessionSupported("immersive-vr").then((ok) => {
        if (ok && button.dataset.vrState === "unavailable") setButton("ready", "View in VR", "Enter immersive VR");
      }).catch(() => {});
    });
  }

  // ── enter / exit ──────────────────────────────────────────────────────────
  let session = null;

  async function enterVR() {
    if (session) return;
    try {
      session = await navigator.xr.requestSession("immersive-vr", {
        optionalFeatures: ["local-floor", "bounded-floor", "hand-tracking", "layers"],
      });
    } catch (e) {
      setButton("ready", "View in VR", "Could not start VR: " + (e?.message || e));
      session = null;
      return;
    }
    renderer.xr.setReferenceSpaceType("local"); // head ≈ origin; we place the dolly
    // Lighten the stereo GPU load so the Quest can't lock up (a GPU hang is what
    // makes even the Meta button stop responding and forces a hardware restart):
    // render the eye buffers at 0.8× and apply maximum fixed-foveation so the
    // periphery is cheap. setFramebufferScaleFactor must be set before setSession.
    try { renderer.xr.setFramebufferScaleFactor?.(0.8); } catch (_) {}
    await renderer.xr.setSession(session);
    try { renderer.xr.setFoveation?.(1.0); } catch (_) {}

    // Session-level select/squeeze listeners: a second delivery path for the grab
    // signal (counts for the debug HUD, and drives grab by matching the event's
    // input source to a controller by handedness) — in case the per-controller
    // events three.js forwards don't fire on this browser build.
    const setGrabFromSession = (val, isSqueeze) => (e) => {
      if (val) { if (isSqueeze) _sessSqz++; else _sessSel++; }
      const h = e.inputSource && e.inputSource.handedness;
      if (h === "left" || h === "right") _grab[h] = val;
    };
    session.addEventListener("selectstart", setGrabFromSession(true, false));
    session.addEventListener("selectend", setGrabFromSession(false, false));
    session.addEventListener("squeezestart", setGrabFromSession(true, true));
    session.addEventListener("squeezeend", setGrabFromSession(false, true));

    // Frame the cell: drop the camera into the dolly, place the user back from
    // centre looking toward it, scaled so the cell is comfortably sized.
    camera.userData._parentBeforeVR = camera.parent;
    // The dolly scales the Å-scale world into metres for the headset, so the
    // cell sits a few metres from the camera in view space. The desktop near/far
    // (tuned for Å, near ~200) would clip the whole cell inside the near plane →
    // black. Use metre-scale near/far in VR; restore on exit.
    camera.userData._nearBeforeVR = camera.near;
    camera.userData._farBeforeVR = camera.far;
    // Near plane at 15 cm (not 2 cm): anything closer renders with extreme
    // binocular disparity the eyes can't fuse → double vision. 15 cm keeps stereo
    // comfortable while still letting you get close to look inside the cell.
    camera.near = 0.15;
    camera.far = 2000;
    camera.updateProjectionMatrix();
    dolly.scale.setScalar(WORLD_SCALE);
    dolly.position.set(0, 0, START_BACK);
    dolly.rotation.set(0, 0, 0);
    dolly.add(camera);
    camera.add(vignette);
    vignette.visible = true;
    vignetteMat.uniforms.uOpacity.value = 0; // reset so a session ended mid-fly doesn't flash a stale vignette on re-enter
    camera.add(hint);
    hint.visible = true;
    hintHideAt = performance.now() + 6000;
    camera.add(handWarn); // visibility toggled per-frame by hand-vs-controller detection
    if (DEBUG_INPUT) { camera.add(dbgMesh); dbgMesh.visible = true; }
    scene.add(dolly);

    setButton("active", "Exit VR", "Leave VR");
    onEnter?.();

    session.addEventListener("end", () => {
      session = null;
      // Restore desktop camera + controls.
      const parent = camera.userData._parentBeforeVR || scene;
      parent.add(camera);
      camera.remove(vignette);
      vignette.visible = false;
      camera.remove(hint);
      hint.visible = false;
      camera.remove(handWarn);
      handWarn.visible = false;
      camera.remove(dbgMesh);
      dbgMesh.visible = false;
      scene.remove(dolly);
      if (camera.userData._nearBeforeVR != null) {
        camera.near = camera.userData._nearBeforeVR;
        camera.far = camera.userData._farBeforeVR;
        camera.updateProjectionMatrix();
      }
      setButton("ready", "View in VR", "Enter immersive VR");
      onExit?.();
    });
  }

  button?.addEventListener("click", () => {
    if (button.dataset.vrState === "active") session?.end();
    else if (button.dataset.vrState === "ready") enterVR();
  });

  // ── per-frame locomotion (called from the main loop while presenting) ──────
  const _fwd = new THREE.Vector3();
  const _right = new THREE.Vector3();
  const _euler = new THREE.Euler(0, 0, 0, "YXZ");

  // Read a controller thumbstick. Quest reports the stick on axes[2],[3]; some
  // runtimes use [0],[1] — try the live pair. Returns [x, y] past the deadzone.
  function axesFor(handedness) {
    for (const src of (session && session.inputSources) || []) {
      if (src.handedness !== handedness || !src.gamepad) continue;
      const a = src.gamepad.axes || [];
      let x = a[2] || 0, y = a[3] || 0;
      if (Math.abs(x) < DEADZONE && Math.abs(y) < DEADZONE) { x = a[0] || 0; y = a[1] || 0; }
      return [Math.abs(x) > DEADZONE ? x : 0, Math.abs(y) > DEADZONE ? y : 0];
    }
    return [0, 0];
  }

  const _up = new THREE.Vector3(0, 1, 0);
  const _q = new THREE.Quaternion();
  let _snapArmed = false;
  const reassessGate = makeMotionGate(180);

  // ── grab-to-move / pinch-to-scale ─────────────────────────────────────────
  // Hold grip (or trigger) and move your hand to drag the whole world: pull a
  // controller toward you and the cell comes with it. Grab with BOTH hands and
  // change the spread between them to scale — pull your hands apart and the cell
  // grows around you until you're standing inside the cytoplasm.
  const _gPrev = new THREE.Vector3();    // last hand pos (dolly-local), 1-hand drag
  const _gMid = new THREE.Vector3();     // 2-hand midpoint (dolly-local)
  const _gPrevMid = new THREE.Vector3();
  const _gDelta = new THREE.Vector3();
  const _gShift = new THREE.Vector3();
  let _grabMode = 0;                      // 0 none, 1 one-hand, 2 two-hand
  let _grabHand = null;                   // the controller doing a 1-hand drag
  let _gPrevDist = 0;                     // last inter-hand distance (2-hand)

  // Grab state keyed by handedness, set from SESSION-level select/squeeze events
  // (the delivery path that actually fires on this hardware). updateGrab maps each
  // controller to its handedness to read it.
  const _grab = { left: false, right: false };
  const _haW = new THREE.Vector3();   // world-space hand positions (two-hand rotate)
  const _hbW = new THREE.Vector3();
  const _prevVec = new THREE.Vector3(); // previous inter-hand direction (two-hand rotate)
  const _curVec = new THREE.Vector3();

  function isGrabbing(ctrl) {
    const src = ctrl.userData.inputSource;
    const h = src && src.handedness;
    if (h && _grab[h]) return true;                       // session-event grab (primary)
    if (ctrl.userData.selecting || ctrl.userData.squeezing) return true; // per-controller events
    return resolveGrab(src && src.gamepad, null);          // gamepad fallback
  }
  function pulse(ctrl, intensity, ms) {
    const gp = ctrl.userData.inputSource && ctrl.userData.inputSource.gamepad;
    const act = gp && gp.hapticActuators && gp.hapticActuators[0];
    if (act && act.pulse) { try { act.pulse(intensity, ms); } catch (_) {} }
  }
  // Move the dolly so the world translates 1:1 with a hand's local movement:
  // worldMove = q * (scale * localDelta); the dolly moves opposite, so the
  // grabbed point stays locked under the hand.
  function applyDrag(localDelta) {
    _gDelta.copy(localDelta).multiplyScalar(dolly.scale.x).applyQuaternion(dolly.quaternion);
    dolly.position.sub(_gDelta);
  }

  // Returns true while a grab is active this frame (the main loop uses this to
  // defer the LOD reassess that would otherwise hitch mid-motion).
  function updateGrab() {
    const a = controllers[0], b = controllers[1];
    const ga = isGrabbing(a), gb = isGrabbing(b);
    const n = (ga ? 1 : 0) + (gb ? 1 : 0);

    if (n === 2) {
      _gMid.copy(a.position).add(b.position).multiplyScalar(0.5);
      const dist = a.position.distanceTo(b.position);
      if (_grabMode !== 2) {
        _grabMode = 2;
        _gPrevMid.copy(_gMid);
        _gPrevDist = dist;
        a.getWorldPosition(_haW); b.getWorldPosition(_hbW);
        _prevVec.subVectors(_hbW, _haW).normalize();
        pulse(a, 0.4, 25); pulse(b, 0.4, 25);
      } else {
        // translate by midpoint movement…
        _gDelta.copy(_gMid).sub(_gPrevMid);
        applyDrag(_gDelta);
        // …and scale by the inter-hand distance ratio, holding the world
        // midpoint fixed: pos += q * ((sOld - sNew) * mid).
        if (_gPrevDist > 1e-4 && dist > 1e-4) {
          const sOld = dolly.scale.x;
          let sNew = sOld * (_gPrevDist / dist);   // hands apart → smaller scale → bigger cell
          sNew = Math.min(SCALE_MAX, Math.max(SCALE_MIN, sNew));
          _gShift.copy(_gMid).multiplyScalar(sOld - sNew).applyQuaternion(dolly.quaternion);
          dolly.position.add(_gShift);
          dolly.scale.setScalar(sNew);
        }
        // …and yaw-rotate by the twist of the inter-hand vector, so two hands can
        // turn the cell (thumbstick snap-turn is dead on some controllers).
        // Pivot about the CELL CENTRE (world origin — the pack is centred there),
        // NOT the hand midpoint: the hands are near the viewer while the cell is
        // far, so a hand-midpoint pivot made the distant cell revolve around the
        // user instead of spinning in place. World-space angle → no dolly feedback.
        a.getWorldPosition(_haW); b.getWorldPosition(_hbW);
        _curVec.subVectors(_hbW, _haW).normalize();
        // Full-arc (any-axis) rotation from the previous to the current inter-hand
        // direction — lets you tumble the cell in any direction, not just yaw.
        _q.setFromUnitVectors(_prevVec, _curVec).invert(); // camera counter-rotates → cell follows hands
        dolly.position.applyQuaternion(_q);   // pivot = world origin (cell centre)
        dolly.quaternion.premultiply(_q);
        _prevVec.copy(_curVec);
        _gPrevMid.copy(_gMid);
        _gPrevDist = dist;
      }
      return true;
    }

    if (n === 1) {
      const c = ga ? a : b;
      if (_grabMode !== 1 || _grabHand !== c) {
        _grabMode = 1;
        _grabHand = c;
        _gPrev.copy(c.position);
        pulse(c, 0.4, 25);
      } else {
        _gDelta.copy(c.position).sub(_gPrev);
        applyDrag(_gDelta);
        _gPrev.copy(c.position);
      }
      return true;
    }

    _grabMode = 0;
    _grabHand = null;
    return false;
  }

  function updateVR(dt, now) {
    if (!renderer.xr.isPresenting || !session) return false;

    if (hint.visible && now >= hintHideAt) hint.visible = false;
    updateDebugHUD(now, dt);

    // Hand-vs-controller: if the session delivers only hand input (no controller
    // gamepad), our grip/trigger/stick controls are inert — surface the warning.
    let hasController = false, hasHandSrc = false;
    for (const s of session.inputSources || []) {
      if (s.hand) hasHandSrc = true;
      if (!s.hand && s.gamepad) hasController = true;
    }
    handWarn.visible = hasHandSrc && !hasController;

    // In-headset exit: the desktop "Exit VR" button is unreachable while
    // immersed. Map ANY face button (A/B/X/Y) or thumbstick-click on either
    // controller to ending the session, read straight off the live input sources
    // so it works regardless of controller-binding quirks. Locomotion/grab use
    // the triggers, grips and stick axes — buttons 3/4/5 are otherwise free.
    for (const src of session.inputSources || []) {
      const b = src.gamepad && src.gamepad.buttons;
      if (!b) continue;
      if ((b[3] && b[3].pressed) || (b[4] && b[4].pressed) || (b[5] && b[5].pressed)) {
        try { session.end(); } catch (_) {}
        return true;
      }
    }

    let smoothMotion = 0;

    // Direct manipulation takes priority: while grabbing, skip stick locomotion
    // so the two don't fight.
    if (updateGrab()) {
      hint.visible = false;
      reassessGate.noteMotion(now);
      const cur = vignetteMat.uniforms.uOpacity.value;
      vignetteMat.uniforms.uOpacity.value = cur + (0 - cur) * Math.min(1, dt * 8);
      return true;
    }

    const xrCam = renderer.xr.getCamera();
    const head = xrCam.getWorldPosition(new THREE.Vector3());
    // Head yaw, so "forward" tracks where the user looks.
    _euler.setFromQuaternion(xrCam.quaternion);
    const yaw = _euler.y;
    _fwd.set(-Math.sin(yaw), 0, -Math.cos(yaw));
    _right.set(Math.cos(yaw), 0, -Math.sin(yaw));

    // LEFT stick → fly (head-relative; head-metres → Å via the dolly scale).
    const [lx, ly] = axesFor("left");
    if (lx || ly) {
      const step = FLY_SPEED * dt * dolly.scale.x;
      dolly.position.addScaledVector(_fwd, -ly * step);
      dolly.position.addScaledVector(_right, lx * step);
      reassessGate.noteMotion(now);
      smoothMotion = Math.max(smoothMotion, Math.hypot(lx, ly));
    }

    const [rx, ry] = axesFor("right");
    // RIGHT stick X → comfortable snap-turn about the head (rotate your view).
    if (Math.abs(rx) > 0.6) {
      if (!_snapArmed) {
        _snapArmed = true;
        _q.setFromAxisAngle(_up, rx > 0 ? -SNAP_ANGLE : SNAP_ANGLE);
        dolly.position.sub(head).applyQuaternion(_q).add(head);
        dolly.quaternion.premultiply(_q);
        reassessGate.noteMotion(now);
      }
    } else if (Math.abs(rx) < 0.3) {
      _snapArmed = false;
    }
    // RIGHT stick Y → scale the world about the head (zoom in/out), clamped so it
    // can't shrink to a dot or balloon you inside a mesh (both read as black).
    if (ry) {
      const want = dolly.scale.x * Math.exp(-ry * SCALE_RATE * dt);
      const newScale = Math.min(SCALE_MAX, Math.max(SCALE_MIN, want));
      const factor = newScale / dolly.scale.x;
      const delta = head.clone().sub(dolly.position);
      dolly.position.copy(head).addScaledVector(delta, -factor);
      dolly.scale.setScalar(newScale);
      reassessGate.noteMotion(now);
      smoothMotion = Math.max(smoothMotion, Math.abs(ry));
    }
    // Ease toward the target opacity so it fades rather than snaps.
    const target = vignetteIntensity(smoothMotion);
    const cur = vignetteMat.uniforms.uOpacity.value;
    vignetteMat.uniforms.uOpacity.value = cur + (target - cur) * Math.min(1, dt * 8);
    return false;
  }

  return {
    updateVR,
    maybeReassess(now) { return reassessGate.shouldFire(now); },
    get presenting() { return renderer.xr.isPresenting; },
  };
}
