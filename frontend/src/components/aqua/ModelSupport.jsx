import { useEffect } from "react";
import { useThree } from "@react-three/fiber";
import { Color, PMREMGenerator } from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
export { default as ModelErrorBoundary } from "./ModelErrorBoundary.jsx";

// The assets are cached by useLoader. Only this renderer's reflection target is owned here.
export function StudioReflections({ lowKey = false }) {
  const { gl, scene, invalidate } = useThree();
  useEffect(() => {
    const room = new RoomEnvironment();
    if (lowKey) {
      const adjusted = new Set();
      room.traverse((object) => {
        if (object.isPointLight) object.intensity *= 0.5;
        if (!object.isMesh || adjusted.has(object.material)) return;
        adjusted.add(object.material);
        if (object.material.isMeshBasicMaterial) {
          object.material.color.multiplyScalar(0.1);
          if (object.position.y < 20) {
            object.material.color.multiply(new Color("#c0e7ec"));
            object.scale.y *= 0.65;
          } else object.scale.z *= 0.45;
        } else object.material.color.set("#214858");
      });
    }
    const generator = new PMREMGenerator(gl);
    const target = generator.fromScene(room, 0.035);
    const previous = scene.environment;
    const previousIntensity = scene.environmentIntensity;
    scene.environment = target.texture;
    scene.environmentIntensity = lowKey ? 0.72 : 1;
    room.dispose();
    generator.dispose();
    invalidate();
    return () => {
      scene.environment = previous;
      scene.environmentIntensity = previousIntensity;
      target.dispose();
    };
  }, [gl, scene, invalidate, lowKey]);
  return null;
}

export function ContextGuard({ onFailure }) {
  const { gl } = useThree();
  useEffect(() => {
    const fail = (event) => {
      event.preventDefault();
      onFailure();
    };
    gl.domElement.addEventListener("webglcontextlost", fail);
    return () => gl.domElement.removeEventListener("webglcontextlost", fail);
  }, [gl, onFailure]);
  return null;
}

