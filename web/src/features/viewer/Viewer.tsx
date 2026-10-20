import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { ApiError, api, type Mesh } from "../../api/client";
import type { Status } from "../../api/types";
import { STATUS_META, Spinner, StatusMark } from "../../components/ui";

// P6.8: the IFC is tessellated server-side (/api/models/{v}/mesh) so the browser only needs three.js.
// Elements are coloured by their worst result status, matched on IFC GlobalId.

const NEUTRAL = 0x9a9aa1;

interface Props {
  modelVersion: string;
  statusByGuid: Map<string, Status>;
  selectedGuid: string | null;
  onPick?: (guid: string) => void;
}

export default function Viewer({ modelVersion, statusByGuid, selectedGuid, onPick }: Props) {
  const mesh = useQuery({ queryKey: ["mesh", modelVersion], queryFn: () => api.mesh(modelVersion), retry: false });
  const host = useRef<HTMLDivElement>(null);
  const scene = useRef<{
    focus: (guid: string | null) => void;
    xray: (on: boolean) => void;
    dispose: () => void;
  } | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [point, setPoint] = useState<[number, number, number] | null>(null);
  const [xray, setXray] = useState(true);
  const pickRef = useRef(onPick);
  pickRef.current = onPick;

  useEffect(() => {
    if (!mesh.data || !host.current) return;
    const { elements, spaces, context = [] } = mesh.data;
    scene.current = build(host.current, elements, spaces, context, statusByGuid, (g) => pickRef.current?.(g), setHover, setPoint);
    return () => scene.current?.dispose();
  }, [mesh.data, statusByGuid]);

  useEffect(() => {
    scene.current?.focus(selectedGuid);
  }, [selectedGuid, mesh.data, statusByGuid]);

  useEffect(() => {
    scene.current?.xray(xray);
  }, [xray, mesh.data, statusByGuid]);

  if (mesh.error) {
    const notFound = mesh.error instanceof ApiError && mesh.error.status === 404;
    return (
      <div className="panel grid h-full min-h-[320px] place-items-center p-6 text-center text-sm text-fg-2">
        {notFound ? (
          <div>
            <p className="h2 text-fg">results are in Revit</p>
            <p className="mt-1">
              This model was sent from the Revit add-in. Open <em>Compliance → Results</em> to see each issue on the
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
      <div className="readout pointer-events-none absolute bottom-3 left-3">
        {point ? `x ${point[0].toFixed(2)}  y ${point[1].toFixed(2)}  z ${point[2].toFixed(2)} m` : "x —  y —  z — m"}
      </div>
      {mesh.data && (
        <button
          onClick={() => setXray((x) => !x)}
          className="btn-secondary absolute right-3 top-3 h-7 bg-surface px-2.5 text-xs"
          title="See the rooms through the walls and floors"
        >
          {xray ? "walls: x-ray" : "walls: solid"}
        </button>
      )}
      {!hover && <p className="pointer-events-none absolute left-3 top-3 text-2xs text-fg-3">drag to orbit · scroll to zoom</p>}
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
) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  el.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
  camera.up.set(0, 0, 1); // IFC is Z-up
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x2a2a2e, 2.0));
  const sun = new THREE.DirectionalLight(0xffffff, 1.4);
  sun.position.set(30, -40, 60);
  scene.add(sun);

  const meshes: THREE.Mesh[] = [];
  const shell: THREE.Mesh[] = []; // walls, slabs, roofs: see-through in X-ray mode
  let pickTargets: THREE.Mesh[] = meshes; // in X-ray mode clicks go through the shell to the rooms
  const byGuid = new Map<string, THREE.Mesh[]>();
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
    mesh.userData = { guid: m.parent && statusByGuid.has(m.parent) ? m.parent : m.guid, label: `${m.name} · ${m.type.replace(/^Ifc/, "")}`, base: color };
    if (status && STATUS_META[status].dashed) {
      // can't verify: a dashed outline, never colour alone (guidelines 10)
      const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(g, 30),
        new THREE.LineDashedMaterial({ color: 0xf2f2f3, dashSize: 0.25, gapSize: 0.18 }),
      );
      edges.computeLineDistances();
      mesh.add(edges);
    } else if (!isSpace) {
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(g, 30), new THREE.LineBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.45 }));
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
      color: isSite ? 0x1c1c1f : isRoad ? 0x2a2a2e : 0x38383d,
      transparent: !isSite && !isRoad,
      opacity: isSite || isRoad ? 1 : 0.5,
      roughness: 0.95,
    });
    const mesh = new THREE.Mesh(g, mat);
    mesh.userData = { label: isSite ? "Plot" : m.name };
    if (isSite) mesh.add(new THREE.LineSegments(new THREE.EdgesGeometry(g, 30), new THREE.LineBasicMaterial({ color: 0x9a9aa1 })));
    scene.add(mesh);
    contextMeshes.push(mesh);
  }

  const all = new THREE.Box3();
  meshes.forEach((m) => all.expandByObject(m));
  contextMeshes.filter((m) => m.userData.label === "Plot").forEach((m) => all.expandByObject(m));
  const frame = (box: THREE.Box3, tight: boolean) => {
    if (box.isEmpty()) return;
    const c = box.getCenter(new THREE.Vector3());
    const r = Math.max(box.getSize(new THREE.Vector3()).length() / 2, tight ? 2 : 5);
    // Fit the narrower of the two fields of view (the panel is often taller than wide).
    const vfov = (camera.fov * Math.PI) / 180;
    const hfov = 2 * Math.atan(Math.tan(vfov / 2) * Math.max(camera.aspect, 0.3));
    const d = r / Math.sin(Math.min(vfov, hfov) / 2);
    controls.target.copy(c);
    camera.position.copy(c).add(new THREE.Vector3(0.9, -1.3, 0.9).normalize().multiplyScalar(d * (tight ? 1.4 : 1.05)));
    camera.near = d / 100;
    camera.far = d * 100;
    camera.updateProjectionMatrix();
  };

  // Until the user moves the camera, keep the whole model framed as the panel settles its size
  // (on first build the panel can still be zero-sized).
  let userMoved = false;
  let focused: THREE.Box3 | null = null;
  controls.addEventListener("start", () => (userMoved = true));
  const resize = () => {
    const w = el.clientWidth;
    const h = el.clientHeight;
    if (w < 2 || h < 2) return;
    renderer.setSize(w, h, false);
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    if (!userMoved) frame(focused ?? all, !!focused);
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
  let down = { x: 0, y: 0 };
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
  renderer.domElement.addEventListener("pointerdown", onDown);
  renderer.domElement.addEventListener("pointerup", onUp);
  renderer.domElement.addEventListener("pointermove", onMove);

  let raf = 0;
  const loop = () => {
    controls.update();
    renderer.render(scene, camera);
    raf = requestAnimationFrame(loop);
  };
  loop();

  return {
    xray(on: boolean) {
      const shellSet = new Set(shell);
      pickTargets = on ? meshes.filter((m) => !shellSet.has(m)) : meshes;
      for (const m of shell) {
        const mat = m.material as THREE.MeshStandardMaterial;
        mat.transparent = on;
        mat.opacity = on ? 0.12 : 1;
        mat.depthWrite = !on;
        mat.needsUpdate = true;
        const edges = m.children[0] as THREE.LineSegments | undefined;
        if (edges) {
          const em = edges.material as THREE.LineBasicMaterial;
          em.color.setHex(on ? 0xf2f2f3 : 0x000000);
          em.opacity = on ? 0.14 : 0.45;
        }
      }
    },
    focus(guid: string | null) {
      meshes.forEach((m) => {
        const mat = m.material as THREE.MeshStandardMaterial;
        mat.emissive.setHex(0x000000);
      });
      const targets = guid ? byGuid.get(guid) : undefined;
      if (!targets) return;
      const box = new THREE.Box3();
      targets.forEach((m) => {
        (m.material as THREE.MeshStandardMaterial).emissive.setHex(0x505057);
        box.expandByObject(m);
      });
      focused = box;
      userMoved = false;
      frame(box, true);
    },
    dispose() {
      cancelAnimationFrame(raf);
      ro.disconnect();
      controls.dispose();
      renderer.domElement.removeEventListener("pointerdown", onDown);
      renderer.domElement.removeEventListener("pointerup", onUp);
      renderer.domElement.removeEventListener("pointermove", onMove);
      [...meshes, ...contextMeshes].forEach((m) => {
        m.geometry.dispose();
        (m.material as THREE.Material).dispose();
      });
      renderer.dispose();
      renderer.domElement.remove();
    },
  };
}
