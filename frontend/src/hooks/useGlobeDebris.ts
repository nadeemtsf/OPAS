import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import axios from "axios";
import type { GlobeMethods } from "react-globe.gl";
import type { Debris, DebrisInstance, HoveredDebris } from "../types";
import { API_BASE, EARTH_RADIUS_KM } from "../constants";

const DEBRIS_GEO = new THREE.SphereGeometry(0.5, 6, 6);
const DEBRIS_MAT = new THREE.MeshBasicMaterial({
  color: 0x64b4ff,
  transparent: true,
  opacity: 0.7,
});

export function useGlobeDebris(globeRef: React.RefObject<GlobeMethods | undefined>) {
  const debrisRef = useRef<DebrisInstance[]>([]);
  const instancedRef = useRef<THREE.InstancedMesh | null>(null);
  const [debrisReady, setDebrisReady] = useState(false);
  const [hoveredDebris, setHoveredDebris] = useState<HoveredDebris | null>(null);

  useEffect(() => {
    axios.get(`${API_BASE}/debris`).then(({ data }) => {
      debrisRef.current = data.debris.map((d: Debris) => ({
        lat: d.location.coordinates[1],
        lng: d.location.coordinates[0],
        alt: d.altitude_km / EARTH_RADIUS_KM,
        name: d.name,
        norad_id: d.norad_id,
        altitude_km: d.altitude_km,
      }));
      setDebrisReady(true);
    });
  }, []);

  useEffect(() => {
    if (!debrisReady || !globeRef.current) return;

    const globe = globeRef.current;
    const scene = globe.scene();

    if (instancedRef.current) {
      scene.remove(instancedRef.current);
      instancedRef.current.dispose();
    }

    const pts = debrisRef.current;
    if (pts.length === 0) return;

    const mesh = new THREE.InstancedMesh(DEBRIS_GEO, DEBRIS_MAT, pts.length);
    const dummy = new THREE.Object3D();

    for (let i = 0; i < pts.length; i++) {
      const coords = globe.getCoords(pts[i].lat, pts[i].lng, pts[i].alt);
      if (coords) {
        dummy.position.set(coords.x, coords.y, coords.z);
        dummy.updateMatrix();
        mesh.setMatrixAt(i, dummy.matrix);
      }
    }
    mesh.instanceMatrix.needsUpdate = true;
    scene.add(mesh);
    instancedRef.current = mesh;

    return () => {
      if (instancedRef.current) {
        scene.remove(instancedRef.current);
      }
    };
  }, [debrisReady, globeRef]);

  useEffect(() => {
    if (!debrisReady || !globeRef.current) return;

    const globe = globeRef.current;
    const renderer = globe.renderer();
    const camera = globe.camera();
    const canvas: HTMLCanvasElement = renderer.domElement;

    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2();
    let rafId: number | null = null;
    let lastEvent: MouseEvent | null = null;

    function setAutoRotate(enabled: boolean) {
      const controls = globeRef.current?.controls?.();
      if (controls) controls.autoRotate = enabled;
    }

    function tick() {
      rafId = null;
      if (!lastEvent || !instancedRef.current) return;

      const rect = canvas.getBoundingClientRect();
      mouse.x = ((lastEvent.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((lastEvent.clientY - rect.top) / rect.height) * 2 + 1;

      raycaster.setFromCamera(mouse, camera);
      const intersects = raycaster.intersectObject(instancedRef.current);

      if (intersects.length > 0 && intersects[0].instanceId !== undefined) {
        const id = intersects[0].instanceId;
        const debris = debrisRef.current[id];
        if (debris) {
          setHoveredDebris({ x: lastEvent.clientX, y: lastEvent.clientY, data: debris });
          setAutoRotate(false);
          return;
        }
      }
      setHoveredDebris(null);
      setAutoRotate(true);
    }

    function onMouseMove(e: MouseEvent) {
      lastEvent = e;
      if (rafId === null) {
        rafId = requestAnimationFrame(tick);
      }
    }

    function onMouseLeave() {
      setHoveredDebris(null);
      setAutoRotate(true);
    }

    canvas.addEventListener("mousemove", onMouseMove);
    canvas.addEventListener("mouseleave", onMouseLeave);

    return () => {
      canvas.removeEventListener("mousemove", onMouseMove);
      canvas.removeEventListener("mouseleave", onMouseLeave);
      if (rafId !== null) cancelAnimationFrame(rafId);
    };
  }, [debrisReady, globeRef]);

  useEffect(() => {
    function enable() {
      const controls = globeRef.current?.controls?.();
      if (controls) {
        controls.autoRotate = true;
        controls.autoRotateSpeed = 0.25;
      }
    }
    enable();
    const timer = setTimeout(enable, 200);
    return () => clearTimeout(timer);
  }, [globeRef]);

  return { hoveredDebris, debrisReady };
}
