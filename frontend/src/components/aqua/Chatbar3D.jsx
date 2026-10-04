import React, { Suspense, useEffect, useLayoutEffect, useMemo } from "react";
import { Canvas, useLoader, useThree } from "@react-three/fiber";
import { Box3, Color, FrontSide, Mesh, ShaderMaterial, Vector3 } from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import chatbarUrl from "../../assets/models/Chatbar.glb?url";
import { ContextGuard, ModelErrorBoundary, StudioReflections } from "./ModelSupport.jsx";

const CONTROL_NODES = new Set([
  "AQUA_Placeholder_FRONT",
  "AQUA_Cursor",
  "AQUA_Send_Arrow_Shaft",
  "AQUA_Send_Arrow_Head",
  "AQUA_Backdrop",
]);

function createTransmissionReceiver() {
  return new ShaderMaterial({
    uniforms: {
      upperTint: { value: new Color("#304d5b") },
      lowerTint: { value: new Color("#172e40") },
    },
    vertexShader: `
      varying vec3 receiverPosition;
      void main() {
        vec4 worldPosition = modelMatrix * vec4(position, 1.0);
        receiverPosition = worldPosition.xyz;
        gl_Position = projectionMatrix * viewMatrix * worldPosition;
      }
    `,
    fragmentShader: `
      uniform vec3 upperTint;
      uniform vec3 lowerTint;
      varying vec3 receiverPosition;
      void main() {
        float across = smoothstep(-6.0, 6.0, receiverPosition.x);
        float lower = smoothstep(-1.1, 1.1, receiverPosition.z);
        vec2 lightDistance = vec2((receiverPosition.x + 2.2) / 5.0,
                                  (receiverPosition.z + 0.5) / 1.5);
        float light = exp(-dot(lightDistance, lightDistance));
        vec3 tint = mix(upperTint, lowerTint, lower * 0.58 + across * 0.12);
        tint += upperTint * light * 0.055;
        // Keep the in-scene transmission sample partially transparent so the page
        // illumination still shows through the canvas instead of becoming a solid fill.
        gl_FragColor = vec4(tint, 0.78);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }
    `,
  });
}

function ChatbarModel({ desktop, onLayout, onReady }) {
  const gltf = useLoader(GLTFLoader, chatbarUrl);
  const { camera, size, invalidate } = useThree();
  const { model, body, button, buttonDepth, buttonBasePosition, ownedMaterials } = useMemo(() => {
    const selected = gltf.scenes.find((scene) => scene.name === "AQUA_CHAT_BAR_V6_CLEAR_GLASS");
    if (!selected) throw new Error("The supplied clear-glass chat bar scene is unavailable.");
    const copy = selected.clone(true);
    const materials = new Map();
    copy.traverse((node) => {
      if (CONTROL_NODES.has(node.name)) node.visible = false;
      if (!node.isMesh || !node.visible) return;
      const original = node.material;
      if (!materials.has(original)) materials.set(original, original.clone());
      node.material = materials.get(original);
      // The GLB exports transmission and IOR, but no volume extension. Derive browser
      // thickness from the original mesh; retain its supplied tint, roughness and IOR.
      if (node.material.isMeshPhysicalMaterial) {
        node.geometry.computeBoundingBox();
        node.material.thickness = node.geometry.boundingBox.getSize(new Vector3()).y;
      }
    });
    const shell = copy.getObjectByName("AQUA_Single_Clear_Glass_Body");
    const send = copy.getObjectByName("AQUA_Glass_Send_Button");
    if (!shell || !send) throw new Error("The supplied chat bar has no usable shell or send region.");
    // Both source meshes are closed; the rear transmission pass adds stray reflections.
    shell.material.side = FrontSide;
    send.material.side = FrontSide;
    // The visible front bevel is +z. Keep its transmission, but remove its specular
    // stripes so the continuous upper/-z reflection remains the sole bright edge.
    shell.material.onBeforeCompile = (shader) => {
      shader.fragmentShader = shader.fragmentShader.replace(
        "#include <transmission_fragment>",
        `#include <transmission_fragment>
         #ifdef USE_TRANSMISSION
           totalSpecular *= 1.0 - smoothstep(0.1, 0.48, vWorldPosition.z);
         #endif`
      );
    };
    // WebGL transmission cannot sample the DOM underneath a transparent canvas. These
    // inset receivers use original asset geometry with a softly lit aqua gradient.
    // The outer GLB remains the visible glass and refracts this in-scene illumination.
    const depthMaterial = createTransmissionReceiver();
    const depth = new Mesh(shell.geometry, depthMaterial);
    depth.name = "Browser_Transmission_Receiver";
    depth.scale.set(0.995, 0.22, 0.85);
    depth.position.y = -0.2;
    copy.add(depth);
    const buttonDepth = new Mesh(send.geometry, depthMaterial);
    buttonDepth.scale.set(0.84, 0.2, 0.84);
    buttonDepth.position.copy(send.position);
    buttonDepth.position.y -= 0.06;
    copy.add(buttonDepth);
    return { model: copy, body: shell, button: send, buttonDepth, buttonBasePosition: send.position.clone(), ownedMaterials: [...materials.values(), depthMaterial] };
  }, [gltf]);

  useLayoutEffect(() => {
    const aspect = size.width / Math.max(size.height, 1);
    // Keep the same width; a taller vertical field gives desktop a shorter shell.
    const verticalScale = desktop ? 0.88 : 1;
    camera.left = -6.4;
    camera.right = 6.4;
    camera.top = 6.4 / aspect / verticalScale;
    camera.bottom = -6.4 / aspect / verticalScale;
    camera.position.set(0, 22, 7);
    camera.lookAt(0, 0.1, 0);
    camera.updateProjectionMatrix();
    camera.updateMatrixWorld(true);
    button.position.copy(buttonBasePosition);
    buttonDepth.position.copy(buttonBasePosition);
    buttonDepth.position.y -= 0.06;
    model.updateMatrixWorld(true);

    const project = (point) => {
      const projected = point.clone().project(camera);
      return { x: (projected.x + 1) * size.width / 2, y: (1 - projected.y) * size.height / 2 };
    };
    const bounds = new Box3().setFromObject(body);
    const usefulMin = bounds.min.x + 0.5;
    const usefulMax = bounds.max.x - 0.5;
    let upperSurface = size.height;
    let lowerSurface = 0;
    const position = body.geometry.attributes.position;
    const vertex = new Vector3();
    for (let index = 0; index < position.count; index += 1) {
      vertex.fromBufferAttribute(position, index).applyMatrix4(body.matrixWorld);
      if (vertex.x >= usefulMin && vertex.x <= usefulMax) {
        const projectedY = project(vertex).y;
        upperSurface = Math.min(upperSurface, projectedY);
        lowerSurface = Math.max(lowerSurface, projectedY);
      }
    }
    const left = project(new Vector3(usefulMin, 0, 0)).x;
    const right = project(new Vector3(usefulMax, 0, 0)).x;
    const textPlane = size.width < 480 ? 0.1 : 0.48;
    const promptLeft = project(new Vector3(-4.98, textPlane, 0));
    const promptRight = project(new Vector3(4.13, textPlane, 0));
    const promptHeight = Math.max(44, Math.min(68, size.width * 0.062));
    const shellCenter = (upperSurface + lowerSurface) / 2;
    if (desktop) {
      // Center the supplied glass button in the shell, moving only this clone.
      const worldCenter = button.getWorldPosition(new Vector3());
      const before = project(worldCenter).y;
      const step = project(worldCenter.clone().add(new Vector3(0, 0, 1))).y - before;
      worldCenter.z += (shellCenter - before) / step;
      button.position.copy(button.parent.worldToLocal(worldCenter));
      buttonDepth.position.z += button.position.z - buttonBasePosition.z;
      model.updateMatrixWorld(true);
    }
    const buttonCenter = project(button.getWorldPosition(new Vector3()));
    const buttonBounds = new Box3().setFromObject(button);
    const buttonWidth = (buttonBounds.max.x - buttonBounds.min.x) * size.width / 12.8;
    const targetSize = Math.max(44, Math.min(72, buttonWidth));
    const targetHeight = desktop ? Math.max(44, targetSize * verticalScale) : targetSize;
    onLayout({
      surface: { left, top: upperSurface, width: right - left, height: 1 },
      prompt: { left: promptLeft.x, top: (desktop ? shellCenter : promptLeft.y) - promptHeight / 2, width: promptRight.x - promptLeft.x, height: promptHeight },
      button: { left: buttonCenter.x - targetSize / 2, top: buttonCenter.y - targetHeight / 2, width: targetSize, height: targetHeight },
    });
    invalidate();
  }, [body, button, buttonDepth, buttonBasePosition, desktop, camera, model, onLayout, size.width, size.height, invalidate]);

  useEffect(() => {
    const frame = requestAnimationFrame(onReady);
    return () => cancelAnimationFrame(frame);
  }, [onReady]);
  useEffect(() => () => ownedMaterials.forEach((material) => material.dispose()), [ownedMaterials]);

  return <primitive object={model} dispose={null} />;
}

export default function Chatbar3D({ desktop = false, focused, onLayout, onReady, onFailure }) {
  return (
    <div className="chat-bar-model" aria-hidden="true">
      <ModelErrorBoundary onFailure={onFailure}>
        <Canvas
          orthographic
          camera={{ position: [0, 22, 7], near: 0.1, far: 45 }}
          dpr={[1, 1.35]}
          frameloop="demand"
          fallback={null}
          gl={{ alpha: true, antialias: true, powerPreference: "low-power" }}
          onCreated={({ gl }) => {
            gl.setClearColor(0x000000, 0);
            gl.toneMappingExposure = 0.98;
          }}
        >
          <ContextGuard onFailure={onFailure} />
          <StudioReflections lowKey />
          <ambientLight intensity={0.4} />
          <directionalLight position={[-4, 8, 5]} intensity={focused ? 1.05 : 0.8} color="#d8f8fc" />
          <directionalLight position={[5, 4, -3]} intensity={0.55} color="#6bd8ed" />
          <Suspense fallback={null}>
            <ChatbarModel desktop={desktop} onLayout={onLayout} onReady={onReady} />
          </Suspense>
        </Canvas>
      </ModelErrorBoundary>
    </div>
  );
}
