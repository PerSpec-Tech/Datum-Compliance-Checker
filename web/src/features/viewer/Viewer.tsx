import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { ApiError, api, type Mesh } from "../../api/client";
import type { LivePack, Status } from "../../api/types";
import { Icon, STATUS_META, Spinner, StatusMark } from "../../components/ui";
import { useTheme } from "../../lib/theme";

// the IFC is tessellated server-side (/api/models/{v}/mesh) so the browser only needs three.js.
// Elements are coloured by their worst result status, matched on IFC GlobalId.

const NEUTRAL = 0x9a9aa1;

interface Props {
  modelVersion: string;
  statusByGuid: Map<string, Status>;
  /** What the open result is about: elements, a plot side, or the whole building. */
  focus: FocusTarget | null;
  onPick?: (guid: string) => void;
  /** Shows the setbacks from this project's live pack. */
  projectId?: string;
}

/** Where the camera goes for a result. */
export type FocusTarget =
  | { kind: "elements"; guids: string[] }
  | { kind: "edge"; a: number[]; b: number[] }
  | { kind: "building"; view: "front" | "top" };

export default function Viewer({ modelVersion, statusByGuid, focus, onPick, projectId }: Props) {
  const mesh = useQuery({ queryKey: ["mesh", modelVersion], queryFn: () => api.mesh(modelVersion), retry: false });
  const pack = useQuery({
    queryKey: ["live-pack", projectId],
    queryFn: () => api.livePack(projectId!),
    enabled: !!projectId,
    retry: false,
    staleTime: 60_000,
  });
  const [setbacks, setSetbacks] = useState(true);
  const host = useRef<HTMLDivElement>(null);
  const scene = useRef<{
    view: (kind: "fit" | "top" | "front" | "iso") => void;
    focus: (target: FocusTarget | null) => void;
    xray: (on: boolean) => void;
    setbacks: (pack: LivePack | null) => void;
    dispose: () => void;
  } | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const theme = useTheme();
  const [point, setPoint] = useState<[number, number, number] | null>(null);
  const [xray, setXray] = useState(true);
  const pickRef = useRef(onPick);
  pickRef.current = onPick;

  useEffect(() => {
    if (!mesh.data || !host.current) return;
    const { elements, spaces, context = [] } = mesh.data;
    scene.current = build(host.current, elements, spaces, context, statusByGuid, (g) => pickRef.current?.(g), setHover, setPoint, theme === "light");
    return () => scene.current?.dispose();
  }, [mesh.data, statusByGuid, theme]);

  const focusKey = JSON.stringify(focus);
  useEffect(() => {
    scene.current?.focus(focus);
  }, [focusKey, mesh.data, statusByGuid]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    scene.current?.xray(xray);
  }, [xray, mesh.data, statusByGuid]);

  useEffect(() => {
    scene.current?.setbacks(setbacks && pack.data?.envelope ? pack.data : null);
  }, [setbacks, pack.data, mesh.data, statusByGuid, theme]);

  if (mesh.error) {
    const notFound = mesh.error instanceof ApiError && mesh.error.status === 404;
    return (
      <div className="panel grid h-full min-h-[320px] place-items-center p-6 text-center text-sm text-fg-2">
        {notFound ? (
          <div>
            <p className="h2 text-fg">results are in Revit</p>
            <p className="mt-1">
              This model was sent from the Revit add-in. Open <em>Datum → Results</em> to see each issue on the
              element itself.
            </p>
          </div>
        ) : (
          <p>The 3D view couldn't be loaded: {String(mesh.error)}</p>
        )}
      </div>
    );
  }

  return (
    <div className="panel relative h-full min-h-[360px] overflow-hidden bg-surface-low">
      <div ref={host} className="absolute inset-0" />
      {mesh.isLoading && (
        <div className="absolute inset-0 grid place-items-center text-sm text-fg-2">
          <span className="flex items-center gap-2">
            <Spinner /> preparing the 3D view
          </span>
        </div>
      )}
      {hover && (
        <div className="pointer-events-none absolute left-3 top-3 rounded-sm border border-line bg-surface-overlay px-2 py-1 text-xs shadow-[0_4px_12px_rgba(0,0,0,0.4)]">{hover}</div>
      )}
      <div className="pointer-events-none absolute bottom-3 right-3 flex flex-col gap-1 rounded-sm border border-line-subtle bg-surface px-2 py-1.5">
        {(["fail", "unverifiable", "pass"] as Status[]).map((s) => (
          <span key={s} className="flex items-center gap-2">
            <span
              className={`h-2.5 w-2.5 ${STATUS_META[s].dashed ? "border border-dashed border-fg" : ""}`}
              style={STATUS_META[s].dashed ? undefined : { background: `#${STATUS_META[s].hex.toString(16).padStart(6, "0")}` }}
            />
            <StatusMark status={s} />
          </span>
        ))}
      </div>
      <div className="readout pointer-events-none absolute bottom-3 left-1/2 max-w-[60%] -translate-x-1/2 truncate">
        {point
          ? `x ${point[0].toFixed(2)}  y ${point[1].toFixed(2)}  z ${point[2].toFixed(2)} m`
          : "drag: orbit · right / middle-drag: pan · wheel: zoom · Shift + middle: orbit · double-middle: fit"}
      </div>
      {mesh.data && (
        <div className="absolute left-1/2 top-3 flex -translate-x-1/2 gap-1">
          <div className="flex rounded-sm border border-line-subtle bg-surface">
            {(
              [
                ["fit", "home", "Zoom to fit (double-click the middle button)"],
                ["top", "plan", "From above"],
                ["front", "layers", "From the front (the road)"],
                ["iso", "cube", "3D view"],
              ] as const
            ).map(([k, icon, title]) => (
              <button key={k} onClick={() => scene.current?.view(k)} className="btn-ghost h-7 px-2 text-xs" title={title}>
                <Icon name={icon} size={12} /> {k === "iso" ? "3D" : k}
              </button>
            ))}
          </div>
          {pack.data?.envelope && (
            <button
              onClick={() => setSetbacks((v) => !v)}
              aria-pressed={setbacks}
              className={`btn-secondary h-7 bg-surface px-2.5 text-xs ${setbacks ? "border-fg text-fg" : ""}`}
              title="The buildable line: the plot inset by the margin each side needs"
            >
              <Icon name="ruler" size={12} /> setbacks
            </button>
          )}
          <button
            onClick={() => setXray((x) => !x)}
            className="btn-secondary h-7 bg-surface px-2.5 text-xs"
            title="See the rooms through the walls and floors"
          >
            <Icon name={xray ? "eye" : "cube"} size={12} /> {xray ? "walls: x-ray" : "walls: solid"}
          </button>
        </div>
      )}

    </div>
  );
}

function build(
  el: HTMLDivElement,
  elements: Mesh[],
  spaces: Mesh[],
  context: Mesh[],
  statusByGuid: Map<string, Status>,
  pick: (guid: string) => void,
  setHover: (label: string | null) => void,
  setPoint: (p: [number, number, number] | null) => void,
  light = false,
) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  el.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
  camera.up.set(0, 0, 1); // IFC is Z-up
  const controls = new OrbitControls(camera, renderer.domElement);
  // Navigation as in Revit: wheel zooms to the cursor, middle-drag pans, Shift + middle-drag orbits,
  // double-click the middle button to fit. Left-drag orbits and right-drag pans too (laptops, other
  // viewers). No inertia: the view stops the moment the mouse is let go.
  controls.enableDamping = false;
  controls.zoomToCursor = true;
  controls.screenSpacePanning = true;
  controls.rotateSpeed = 0.6;
  controls.zoomSpeed = 1.1;
  controls.maxPolarAngle = Math.PI * 0.55; // not far under the ground
  controls.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.PAN, RIGHT: THREE.MOUSE.PAN };
  scene.add(new THREE.HemisphereLight(0xffffff, light ? 0xb4b4b9 : 0x2a2a2e, light ? 2.4 : 2.0));
  const sun = new THREE.DirectionalLight(0xffffff, 1.4);
  sun.position.set(30, -40, 60);
  scene.add(sun);

  const meshes: THREE.Mesh[] = [];
  const shell: THREE.Mesh[] = []; // walls, slabs, roofs: see-through in X-ray mode
  let pickTargets: THREE.Mesh[] = meshes; // in X-ray mode clicks go through the shell to the rooms
  const byGuid = new Map<string, THREE.Mesh[]>();
  // Everything but the dashed "can't verify" items is drawn merged by look: a few draw calls per
  // colour instead of two per element, so a tower stays smooth. Each element's own mesh stays in the
  // scene, hidden, for picking and for the focus highlight.
  type Look = { color: number; transparent: boolean; opacity: number; depthWrite: boolean; edges: boolean; shell: boolean };
  const plain = new Map<string, { geoms: THREE.BufferGeometry[]; look: Look }>();
  const batched = new Set<THREE.Mesh>();
  const batches: { mesh: THREE.Mesh; edges: THREE.LineSegments; shell: boolean }[] = [];
  const add = (m: Mesh, isSpace: boolean) => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(m.v, 3));
    g.setIndex(m.f);
    g.computeVertexNormals();
    const status = statusByGuid.get(m.guid) ?? (m.parent ? statusByGuid.get(m.parent) : undefined);
    const isShell = !status && /^Ifc(Wall|Slab|Roof|Covering|Plate|Column|Beam)/.test(m.type);
    const isGlass = !status && m.type === "IfcWindow";
    const color = status ? STATUS_META[status].hex : isGlass ? 0x7a7a80 : m.type === "IfcDoor" ? 0x505057 : NEUTRAL;
    const mat = new THREE.MeshStandardMaterial({
      color,
      transparent: isSpace || isGlass,
      // failures carry the colour; passes stay quiet so the reds read first
      opacity: isSpace ? ({ fail: 0.75, unverifiable: 0.3, pass: 0.1 } as Record<string, number>)[status ?? ""] ?? 0.05 : isGlass ? 0.5 : 1,
      depthWrite: !isSpace && !isGlass,
      roughness: 0.8,
      side: THREE.DoubleSide,
    });
    const mesh = new THREE.Mesh(g, mat);
    mesh.userData = { guid: m.parent && statusByGuid.has(m.parent) ? m.parent : m.guid, label: `${m.name} · ${m.type.replace(/^Ifc/, "")}`, base: color, isSpace };
    if (!(status && STATUS_META[status].dashed)) {
      const look: Look = { color, transparent: mat.transparent, opacity: mat.opacity, depthWrite: mat.depthWrite, edges: !isSpace, shell: isShell };
      const key = JSON.stringify(look);
      const b = plain.get(key) ?? { geoms: [], look };
      b.geoms.push(g);
      plain.set(key, b);
      mesh.visible = false;
      batched.add(mesh);
    } else {
      // can't verify: a dashed outline, never colour alone (guidelines 10)
      const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(g, 30),
        new THREE.LineDashedMaterial({ color: light ? 0x0a0a0b : 0xf2f2f3, dashSize: 0.25, gapSize: 0.18 }),
      );
      edges.computeLineDistances();
      mesh.add(edges);
    }
    scene.add(mesh);
    meshes.push(mesh);
    if (isShell) shell.push(mesh);
    const key = mesh.userData.guid as string;
    byGuid.set(key, [...(byGuid.get(key) ?? []), mesh]);
  };
  elements.forEach((m) => add(m, false));
  spaces.forEach((m) => add(m, true));
  for (const { geoms, look } of plain.values()) {
    const g = mergeGeometries(geoms, false);
    if (!g) continue;
    const mesh = new THREE.Mesh(
      g,
      new THREE.MeshStandardMaterial({ color: look.color, transparent: look.transparent, opacity: look.opacity, depthWrite: look.depthWrite, roughness: 0.8, side: THREE.DoubleSide }),
    );
    const edges = new THREE.LineSegments(
      look.edges ? (mergeGeometries(geoms.map((x) => new THREE.EdgesGeometry(x, 30)), false) ?? new THREE.BufferGeometry()) : new THREE.BufferGeometry(),
      new THREE.LineBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.45 }),
    );
    mesh.add(edges);
    scene.add(mesh);
    batches.push({ mesh, edges, shell: look.shell });
  }

  // Site context: plot ground, roads, neighbours. Hover shows the name; not selectable.
  const contextMeshes: THREE.Mesh[] = [];
  for (const m of context) {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(m.v, 3));
    g.setIndex(m.f);
    g.computeVertexNormals();
    const isSite = m.type === "IfcSite";
    const isRoad = /road|street|lane/i.test(m.name) || m.type === "IfcRoad";
    const mat = new THREE.MeshStandardMaterial({
      color: light ? (isSite ? 0xf0f0f1 : isRoad ? 0xc8c8cc : 0xdcdcdf) : isSite ? 0x1c1c1f : isRoad ? 0x2a2a2e : 0x38383d,
      transparent: !isSite && !isRoad,
      opacity: isSite || isRoad ? 1 : 0.5,
      roughness: 0.95,
    });
    const mesh = new THREE.Mesh(g, mat);
    mesh.userData = { label: isSite ? "Plot" : m.name };
    if (isSite) mesh.add(new THREE.LineSegments(new THREE.EdgesGeometry(g, 30), new THREE.LineBasicMaterial({ color: light ? 0x75757a : 0x9a9aa1 })));
    scene.add(mesh);
    contextMeshes.push(mesh);
  }

  const all = new THREE.Box3();
  meshes.forEach((m) => all.expandByObject(m, true));
  const building = all.clone(); // the building alone (all also takes in the plot)
  let marker: THREE.Object3D | null = null;
  const addMarker = (o: THREE.Object3D) => {
    marker = o;
    scene.add(o);
  };
  const dropMarker = () => {
    if (!marker) return;
    scene.remove(marker);
    marker.traverse((o) => {
      const mm = o as THREE.Mesh;
      mm.geometry?.dispose();
      (mm.material as THREE.Material | undefined)?.dispose();
    });
    marker = null;
  };
  contextMeshes.filter((m) => m.userData.label === "Plot").forEach((m) => all.expandByObject(m));
  let anim: { p0: THREE.Vector3; p1: THREE.Vector3; t0: THREE.Vector3; t1: THREE.Vector3; start: number } | null = null;
  const frame = (box: THREE.Box3, tight: boolean, from = new THREE.Vector3(0.9, -1.3, 0.9), glide = false) => {
    if (box.isEmpty()) return;
    const c = box.getCenter(new THREE.Vector3());
    const r = Math.max(box.getSize(new THREE.Vector3()).length() / 2, tight ? 2 : 5);
    // Fit the narrower of the two fields of view (the panel is often taller than wide).
    const vfov = (camera.fov * Math.PI) / 180;
    const hfov = 2 * Math.atan(Math.tan(vfov / 2) * Math.max(camera.aspect, 0.3));
    const d = r / Math.sin(Math.min(vfov, hfov) / 2);
    const to = c.clone().add(from.clone().normalize().multiplyScalar(d * (tight ? 1.4 : 1.05)));
    camera.near = Math.min(camera.near, d / 100);
    camera.far = Math.max(camera.far, d * 100);
    camera.updateProjectionMatrix();
    if (glide) {
      anim = { p0: camera.position.clone(), p1: to, t0: controls.target.clone(), t1: c, start: performance.now() };
    } else {
      anim = null;
      controls.target.copy(c);
      camera.position.copy(to);
    }
  };

  // Until the user moves the camera, keep the whole model framed as the panel settles its size
  // (on first build the panel can still be zero-sized).
  let userMoved = false;
  let focused: THREE.Box3 | null = null;
  controls.addEventListener("start", () => {
    userMoved = true;
    anim = null; // the user takes over mid-glide
  });
  const resize = () => {
    const w = el.clientWidth;
    const h = el.clientHeight;
    if (w < 2 || h < 2) return;
    renderer.setSize(w, h, false);
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    if (!userMoved && !anim) frame(focused ?? all, false, focused ? new THREE.Vector3(0.5, -0.8, 1.6) : undefined);
  };
  const ro = new ResizeObserver(resize);
  ro.observe(el);
  frame(all, false);
  resize();

  const ray = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  const hit = (e: PointerEvent) => {
    const r = renderer.domElement.getBoundingClientRect();
    ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    return ray.intersectObjects([...pickTargets, ...contextMeshes], false)[0]?.object as THREE.Mesh | undefined;
  };
  const hitPoint = (e: PointerEvent) => {
    const r = renderer.domElement.getBoundingClientRect();
    ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    return ray.intersectObjects([...meshes, ...contextMeshes], false)[0]?.point ?? null;
  };
  let down = { x: 0, y: 0 };
  let lastMiddle = 0;
  // Runs before the orbit controls (capture), so it can choose what this drag does.
  const onDownFirst = (e: PointerEvent) => {
    if (e.button === 1) {
      e.preventDefault(); // no browser autoscroll
      controls.mouseButtons.MIDDLE = e.shiftKey ? THREE.MOUSE.ROTATE : THREE.MOUSE.PAN;
      const now = performance.now();
      if (now - lastMiddle < 350) {
        frame(all, false, undefined, true); // double middle click: zoom to fit, as in Revit
        lastMiddle = 0;
        return;
      }
      lastMiddle = now;
    }
    const orbit = (e.button === 0 && !e.shiftKey && !e.ctrlKey && !e.metaKey) || (e.button === 1 && e.shiftKey);
    if (!orbit) return;
    // Orbit around what is under the cursor: the pivot goes to that depth on the view axis, so the
    // view doesn't jump when the drag starts.
    const h = hitPoint(e);
    if (!h) return;
    const fwd = new THREE.Vector3();
    camera.getWorldDirection(fwd);
    const depth = h.clone().sub(camera.position).dot(fwd);
    if (depth > camera.near * 2) controls.target.copy(camera.position).addScaledVector(fwd, depth);
  };
  const onDown = (e: PointerEvent) => (down = { x: e.clientX, y: e.clientY });
  const onUp = (e: PointerEvent) => {
    if (Math.hypot(e.clientX - down.x, e.clientY - down.y) > 4) return; // a drag, not a click
    const m = hit(e);
    if (m?.userData.guid) pick(m.userData.guid as string);
  };
  const onMove = (e: PointerEvent) => {
    const r = renderer.domElement.getBoundingClientRect();
    ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const h = ray.intersectObjects([...pickTargets, ...contextMeshes], false)[0];
    setHover((h?.object.userData.label as string | undefined) ?? null);
    setPoint(h ? [h.point.x, h.point.y, h.point.z] : null);
  };
  renderer.domElement.addEventListener("pointerdown", onDownFirst, { capture: true });
  renderer.domElement.addEventListener("pointerdown", onDown);
  const noMenu = (e: Event) => e.preventDefault(); // right-drag pans
  renderer.domElement.addEventListener("contextmenu", noMenu);
  renderer.domElement.addEventListener("pointerup", onUp);
  renderer.domElement.addEventListener("pointermove", onMove);

  let raf = 0;
  const loop = () => {
    if (anim) {
      const k = Math.min(1, (performance.now() - anim.start) / 450);
      const e = 1 - Math.pow(1 - k, 3); // ease out
      camera.position.lerpVectors(anim.p0, anim.p1, e);
      controls.target.lerpVectors(anim.t0, anim.t1, e);
      if (k >= 1) anim = null;
    }
    controls.update();
    renderer.render(scene, camera);
    raf = requestAnimationFrame(loop);
  };
  loop();

  // Setbacks: the buildable line on the ground and faint walls up to the building height.
  let envelope: THREE.Group | null = null;
  const dropEnvelope = () => {
    if (!envelope) return;
    scene.remove(envelope);
    envelope.traverse((o) => {
      const m = o as THREE.Mesh;
      m.geometry?.dispose();
      (m.material as THREE.Material | undefined)?.dispose();
    });
    envelope = null;
  };

  return {
    setbacks(pack: LivePack | null) {
      dropEnvelope();
      if (!pack?.envelope || pack.envelope.length < 3) return;
      const ring = pack.envelope;
      const top = pack.height.current_m ?? Math.max(all.max.z, 3);
      const ink = light ? 0x0a0a0b : 0xf2f2f3;
      envelope = new THREE.Group();
      const line = (z: number, dashed: boolean) => {
        const pts = [...ring, ring[0]].map((p) => new THREE.Vector3(p[0], p[1], z));
        const l = new THREE.Line(
          new THREE.BufferGeometry().setFromPoints(pts),
          dashed
            ? new THREE.LineDashedMaterial({ color: ink, dashSize: 0.6, gapSize: 0.35 })
            : new THREE.LineBasicMaterial({ color: ink, transparent: true, opacity: 0.25 }),
        );
        l.computeLineDistances();
        envelope!.add(l);
      };
      line(0.03, true);
      line(top, false);
      const v: number[] = [];
      ring.forEach((p, i) => {
        const q = ring[(i + 1) % ring.length];
        v.push(p[0], p[1], 0, q[0], q[1], 0, q[0], q[1], top, p[0], p[1], 0, q[0], q[1], top, p[0], p[1], top);
      });
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.Float32BufferAttribute(v, 3));
      envelope.add(
        new THREE.Mesh(g, new THREE.MeshBasicMaterial({ color: ink, transparent: true, opacity: 0.05, depthWrite: false, side: THREE.DoubleSide })),
      );
      scene.add(envelope);
    },
    xray(on: boolean) {
      const shellSet = new Set(shell);
      pickTargets = on ? meshes.filter((m) => !shellSet.has(m)) : meshes;
      for (const m of [...shell.filter((x) => !batched.has(x)), ...batches.filter((b) => b.shell).map((b) => b.mesh)]) {
        const mat = m.material as THREE.MeshStandardMaterial;
        mat.transparent = on;
        mat.opacity = on ? 0.12 : 1;
        mat.depthWrite = !on;
        mat.needsUpdate = true;
        const edges = m.children[0] as THREE.LineSegments | undefined;
        if (edges) {
          const em = edges.material as THREE.LineBasicMaterial;
          em.color.setHex(on ? (light ? 0x0a0a0b : 0xf2f2f3) : 0x000000);
          em.opacity = on ? 0.14 : 0.45;
        }
      }
    },
    view(kind: "fit" | "top" | "front" | "iso") {
      const box = focused ?? all;
      const dir = { fit: new THREE.Vector3(0.9, -1.3, 0.9), iso: new THREE.Vector3(0.9, -1.3, 0.9), top: new THREE.Vector3(0, -0.001, 1), front: new THREE.Vector3(0, -1, 0.12) }[kind];
      userMoved = true;
      frame(kind === "fit" ? all : box, false, dir, true);
    },
    focus(t: FocusTarget | null) {
      meshes.forEach((m) => {
        const mat = m.material as THREE.MeshStandardMaterial;
        mat.emissive.setHex(0x000000);
        if (batched.has(m)) m.visible = false;
      });
      renderer.clippingPlanes = [];
      dropMarker();
      if (!t) return;
      const centre = building.getCenter(new THREE.Vector3());
      // Look from outside, on the side of the building where the issue is (not always one corner).
      const outward = (p: THREE.Vector3, up: number) => {
        const v = new THREE.Vector3(p.x - centre.x, p.y - centre.y, 0);
        if (v.length() < 1.5) v.set(0.5, -0.8, 0);
        v.normalize();
        return new THREE.Vector3(v.x, v.y, up);
      };
      if (t.kind === "edge") {
        // A plot side: drawn red on the ground and looked at from outside the plot.
        const a = new THREE.Vector3(t.a[0], t.a[1], 0.08), b = new THREE.Vector3(t.b[0], t.b[1], 0.08);
        const len = a.distanceTo(b);
        const bar = new THREE.Mesh(new THREE.BoxGeometry(len, 0.6, 0.12), new THREE.MeshBasicMaterial({ color: 0xd22b10 }));
        bar.position.copy(a).add(b).multiplyScalar(0.5);
        bar.rotation.z = Math.atan2(b.y - a.y, b.x - a.x);
        addMarker(bar);
        const mid = bar.position.clone();
        const view = new THREE.Box3().setFromPoints([a, b]).expandByVector(new THREE.Vector3(4, 4, 0));
        view.max.z = 6; // the side and the margin beside it, not the whole tower
        focused = view;
        userMoved = false;
        frame(view, false, outward(mid, 0.9), true);
        return;
      }
      if (t.kind === "building") {
        // Height: the building from the front with its height marked; other whole-building results from above.
        if (t.view === "front") {
          const h = building.max.z - building.min.z;
          const post = new THREE.Mesh(new THREE.BoxGeometry(0.35, 0.35, h), new THREE.MeshBasicMaterial({ color: 0xd22b10 }));
          post.position.set(building.max.x + 1.5, building.min.y - 1.5, building.min.z + h / 2);
          addMarker(post);
        }
        focused = building.clone();
        userMoved = false;
        frame(building, false, t.view === "front" ? new THREE.Vector3(0.25, -1, 0.15) : new THREE.Vector3(0, -0.001, 1), true);
        return;
      }
      const targets = t.guids.flatMap((g) => byGuid.get(g) ?? []);
      // A section cut just above the element: the floors above disappear, so a room is seen in its
      // own floor, from above, instead of the camera flying in among the walls.
      if (!targets.length) return;
      const box = new THREE.Box3();
      targets.forEach((m) => {
        const mat = m.material as THREE.MeshStandardMaterial;
        mat.emissive.setHex(0x505057);
        if (batched.has(m)) {
          // drawn over its merged copy while it is the focus
          m.visible = true;
          mat.polygonOffset = true;
          mat.polygonOffsetFactor = -1;
          mat.polygonOffsetUnits = -1;
        }
        box.expandByObject(m, true);
      });
      // An element through several storeys (a stair) is shown at its lowest storey.
      if (box.max.z - box.min.z > 4.5) box.max.z = box.min.z + 3.2;
      renderer.clippingPlanes = [new THREE.Plane(new THREE.Vector3(0, 0, -1), box.max.z + 0.05)];
      // The element itself drawn in ink, so it stands out even among other failures of the same colour.
      const ink = new THREE.Group();
      targets.forEach((m) => ink.add(new THREE.LineSegments(new THREE.EdgesGeometry(m.geometry, 30), new THREE.LineBasicMaterial({ color: light ? 0x0a0a0b : 0xf2f2f3 }))));
      addMarker(ink);
      const room = targets.some((m) => m.userData.isSpace);
      // A room: its part of the floor, from above. A door, stair or other element: close up.
      const view = room ? box.clone().expandByVector(new THREE.Vector3(4, 4, 0)) : box.clone().expandByVector(new THREE.Vector3(1.2, 1.2, 0.3));
      focused = view;
      userMoved = false;
      frame(view, !room, outward(box.getCenter(new THREE.Vector3()), room ? 1.8 : 1.1), true);
    },
    dispose() {
      dropEnvelope();
      dropMarker();
      cancelAnimationFrame(raf);
      ro.disconnect();
      controls.dispose();
      renderer.domElement.removeEventListener("pointerdown", onDownFirst, { capture: true });
      renderer.domElement.removeEventListener("pointerdown", onDown);
      renderer.domElement.removeEventListener("contextmenu", noMenu);
      renderer.domElement.removeEventListener("pointerup", onUp);
      renderer.domElement.removeEventListener("pointermove", onMove);
      [...meshes, ...contextMeshes].forEach((m) => {
        m.geometry.dispose();
        (m.material as THREE.Material).dispose();
      });
      batches.forEach((b) => {
        b.mesh.geometry.dispose();
        (b.mesh.material as THREE.Material).dispose();
        b.edges.geometry.dispose();
        (b.edges.material as THREE.Material).dispose();
      });
      renderer.dispose();
      renderer.domElement.remove();
    },
  };
}
