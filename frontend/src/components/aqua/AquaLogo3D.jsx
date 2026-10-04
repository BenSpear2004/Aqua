import React, { Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useLoader, useThree } from "@react-three/fiber";
import { useReducedMotion } from "../../hooks/useReducedMotion.js";
import { AnimationMixer, Box3, Group, Vector3 } from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { clone } from "three/examples/jsm/utils/SkeletonUtils.js";
import logoUrl from "../../assets/models/AQUA_V2_Final.glb?url";
import AquaLogoFallback from "./AquaLogoFallback.jsx";
import { ContextGuard, ModelErrorBoundary, StudioReflections } from "./ModelSupport.jsx";
import "./model.css";

function LogoModel({ reducedMotion, onReady }) {
  const gltf = useLoader(GLTFLoader, logoUrl);
  const { camera, size, invalidate } = useThree();
  const { model, bounds, skeletons } = useMemo(() => {
    const source = gltf.scenes.find((scene) => scene.name === "AQUA_V2_STUDIO") ?? gltf.scene;
    // Clone the wave's bones as well as the scene, without mutating cached GLB resources.
    const copy = clone(source);
    const ownedSkeletons = new Set();
    copy.traverse((node) => {
      if (node.isSkinnedMesh) {
        ownedSkeletons.add(node.skeleton);
        node.frustumCulled = false;
      }
    });
    const assetBounds = new Box3().setFromObject(copy, true);
    const center = assetBounds.getCenter(new Vector3());
    const group = new Group();
    group.add(copy);
    group.position.copy(center).multiplyScalar(-1);
    return { model: group, bounds: assetBounds.getSize(new Vector3()), skeletons: ownedSkeletons };
  }, [gltf]);
  const mixerRef = useRef(null);

  useEffect(() => () => {
    skeletons.forEach((skeleton) => skeleton.dispose());
  }, [skeletons]);

  useLayoutEffect(() => {
    const aspect = size.width / Math.max(size.height, 1);
    const height = Math.max(bounds.y * 1.09, bounds.x * 1.09 / aspect);
    camera.left = -height * aspect / 2;
    camera.right = height * aspect / 2;
    camera.top = height / 2;
    camera.bottom = -height / 2;
    camera.position.set(0, 0, 12);
    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();
    invalidate();
  }, [bounds, camera, size.width, size.height, invalidate]);

  useEffect(() => {
    const readyFrame = requestAnimationFrame(onReady);
    let renderTimer;
    let refreshVisibility;
    if (!reducedMotion) {
      const idle = gltf.animations.find((clip) => clip.name === "AQUA_Idle");
      if (idle) {
        const mixer = new AnimationMixer(model);
        mixer.clipAction(idle).play();
        mixerRef.current = mixer;
        refreshVisibility = () => {
          clearInterval(renderTimer);
          if (!document.hidden) {
            invalidate();
            renderTimer = setInterval(invalidate, 1000 / 30);
          }
        };
        document.addEventListener("visibilitychange", refreshVisibility);
        refreshVisibility();
      }
    }
    return () => {
      cancelAnimationFrame(readyFrame);
      clearInterval(renderTimer);
      if (refreshVisibility) document.removeEventListener("visibilitychange", refreshVisibility);
      mixerRef.current?.stopAllAction();
      mixerRef.current?.uncacheRoot(model);
      mixerRef.current = null;
    };
  }, [gltf, model, onReady, reducedMotion, invalidate]);

  useFrame((_, delta) => mixerRef.current?.update(Math.min(delta, 0.05)));
  return <primitive object={model} dispose={null} />;
}

// The canvas draws on demand. Switching between the large and compact logo
// changes its pixel ratio, which clears the drawing buffer, so draw again
// right away and once more after the CSS resize transition has finished.
function RedrawOnChange({ signal }) {
  const { invalidate } = useThree();
  useEffect(() => {
    invalidate();
    const timer = setTimeout(invalidate, 700);
    return () => clearTimeout(timer);
  }, [signal, invalidate]);
  return null;
}

export default function AquaLogo3D({ compact = false }) {
  const reducedMotion = Boolean(useReducedMotion());
  const [mobile, setMobile] = useState(() => window.matchMedia("(max-width: 700px)").matches);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const onReady = useCallback(() => setReady(true), []);
  const onFailure = useCallback(() => setFailed(true), []);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 700px)");
    const update = () => setMobile(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  return (
    <div className={`logo-scene${compact ? " logo-scene--compact" : ""}`} aria-hidden="true">
      {(!ready || failed) && <AquaLogoFallback compact={compact} />}
      {!failed && (
        <ModelErrorBoundary onFailure={onFailure}>
          <Canvas
            orthographic
            camera={{ position: [0, 0, 12], near: 0.1, far: 40 }}
            // One pixel ratio for both sizes: the canvas keeps its full size
            // either way, and changing the ratio clears the drawing buffer.
            dpr={mobile ? [1, 1.15] : [1, 1.5]}
            // The compact logo is a CSS scale() of this canvas. Measure the
            // untransformed layout size, or the canvas shrinks to the scaled
            // size and stays tiny and blurry after the scale is removed
            // (a transform change does not trigger a new measurement).
            resize={{ offsetSize: true }}
            fallback={null}
            frameloop="demand"
            gl={{ alpha: true, antialias: true, powerPreference: "low-power" }}
            onCreated={({ gl }) => {
              gl.setClearColor(0x000000, 0);
              gl.toneMappingExposure = 1.04;
            }}
          >
            <ContextGuard onFailure={onFailure} />
            <RedrawOnChange signal={`${compact}-${mobile}`} />
            <StudioReflections />
            <ambientLight intensity={0.6} />
            <directionalLight position={[-3, 5, 8]} intensity={2.2} color="#e9fcff" />
            <directionalLight position={[4, 0, 3]} intensity={1.15} color="#74d4ed" />
            <Suspense fallback={null}>
              <LogoModel reducedMotion={reducedMotion} onReady={onReady} />
            </Suspense>
          </Canvas>
        </ModelErrorBoundary>
      )}
    </div>
  );
}
