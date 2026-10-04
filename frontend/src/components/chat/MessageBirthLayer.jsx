import React, { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useReducedMotion } from "../../hooks/useReducedMotion.js";

const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
const mix = (from, to, progress) => from + (to - from) * progress;
const ease = (value) => value < 0.5 ? 4 * value ** 3 : 1 - (-2 * value + 2) ** 3 / 2;

// One continuous outline owns the balloon and its curved connection to the bar.
// There is no text in this layer: the reserved semantic message takes over at rest.
function connectedOutline({ x, y, width, height, radius, neck, base }, source, attached) {
  const left = x - width / 2;
  const right = x + width / 2;
  const bottom = y + height;
  const r = Math.min(radius, width / 2, height / 2);
  const head = `M ${left + r} ${y} H ${right - r} Q ${right} ${y} ${right} ${y + r} V ${bottom - r} Q ${right} ${bottom} ${right - r} ${bottom}`;
  const tail = `H ${left + r} Q ${left} ${bottom} ${left} ${bottom - r} V ${y + r} Q ${left} ${y} ${left + r} ${y} Z`;
  if (!attached || bottom >= source.y - 1) return `${head} ${tail}`;

  const shoulder = Math.min(width * 0.29, Math.max(neck * 2, 16));
  const throatY = bottom + (source.y - bottom) * 0.45;
  return `${head} H ${x + shoulder}
    C ${x + neck} ${bottom}, ${x + neck} ${throatY}, ${source.x + neck} ${throatY}
    C ${source.x + neck} ${source.y - 7}, ${source.x + base} ${source.y - 3}, ${source.x + base} ${source.y + 2}
    Q ${source.x} ${source.y + 5} ${source.x - base} ${source.y + 2}
    C ${source.x - base} ${source.y - 3}, ${source.x - neck} ${source.y - 7}, ${source.x - neck} ${throatY}
    C ${x - neck} ${throatY}, ${x - neck} ${bottom}, ${x - shoulder} ${bottom} ${tail}`;
}

function shapeAt(progress, origin, target, isAqua) {
  const source = {
    x: origin.left + origin.width * (isAqua ? 0.35 : 0.66),
    y: origin.top
  };
  const destination = target.left + target.width / 2;
  const inflatedWidth = Math.min(target.width, Math.max(84, Math.min(origin.width * 0.39, 230)));
  const inflatedHeight = Math.min(target.height, isAqua ? 84 : 76);
  const endHeight = Math.min(target.height, isAqua ? 160 : 144);
  const frames = [
    { at: 0, x: source.x, y: source.y - 5, width: Math.min(62, target.width), height: 7, radius: 40, neck: 22, base: 38 },
    { at: 0.13, x: source.x, y: source.y - 27, width: Math.min(110, target.width), height: 29, radius: 40, neck: 24, base: 43 },
    { at: 0.38, x: source.x, y: source.y - inflatedHeight - 6, width: inflatedWidth, height: inflatedHeight, radius: 44, neck: 22, base: 33 },
    { at: 0.58, x: mix(source.x, destination, 0.12), y: source.y - inflatedHeight - 42, width: Math.min(target.width, inflatedWidth * 1.25), height: inflatedHeight, radius: 38, neck: 10, base: 21 },
    { at: 0.67, x: mix(source.x, destination, 0.2), y: source.y - inflatedHeight - 60, width: Math.min(target.width, inflatedWidth * 1.32), height: inflatedHeight, radius: 33, neck: 0.65, base: 2 },
    { at: 0.94, x: destination, y: target.top - 4, width: target.width, height: endHeight, radius: 28, neck: 0, base: 0 },
    { at: 1, x: destination, y: target.top, width: target.width, height: endHeight, radius: 28, neck: 0, base: 0 }
  ];
  const index = frames.findIndex((frame) => frame.at >= progress);
  const to = frames[Math.max(1, index)];
  const from = frames[Math.max(0, index - 1)];
  const phase = ease(clamp((progress - from.at) / (to.at - from.at), 0, 1));
  const shape = {};
  ["x", "y", "width", "height", "radius", "neck", "base"].forEach((key) => {
    shape[key] = mix(from[key], to[key], phase);
  });
  return { shape, source, attached: progress < 0.675 };
}

export default function MessageBirthLayer({ message, originRef, onComplete }) {
  const reducedMotion = useReducedMotion();
  const gradientId = useId().replace(/:/g, "");
  const pathsRef = useRef([]);
  const highlightRef = useRef(null);
  const lowerHighlightRef = useRef(null);
  const pressureRef = useRef(null);
  const lifecycleRef = useRef(0);
  const onCompleteRef = useRef(onComplete);
  const [ready, setReady] = useState(false);
  onCompleteRef.current = onComplete;

  useEffect(() => {
    const lifecycle = ++lifecycleRef.current;
    let frame = 0;
    let timeout = 0;
    let finished = false;
    let startedAt = null;
    let attempts = 0;
    let targetNode = null;
    const isAqua = message.role === "aqua";
    const duration = isAqua ? 940 : 880;
    const finish = () => {
      if (finished) return;
      finished = true;
      window.cancelAnimationFrame(frame);
      window.clearTimeout(timeout);
      setReady(false);
      onCompleteRef.current?.(message.id);
    };

    if (reducedMotion) {
      finish();
      return undefined;
    }

    const measure = () => {
      const originNode = originRef?.current;
      if (!originNode || !targetNode?.isConnected) return null;
      const origin = originNode.getBoundingClientRect();
      const target = targetNode.getBoundingClientRect();
      const scroller = targetNode.closest(".conversation__scroll")?.getBoundingClientRect();
      const visibleTop = Math.max(0, scroller?.top || 0);
      const visibleBottom = Math.min(window.innerHeight, scroller?.bottom || origin.top);
      if (origin.width < 30 || origin.top < 0 || origin.top > window.innerHeight ||
          target.width < 1 || target.height < 1 || target.top < visibleTop - 8 || target.top >= visibleBottom) {
        return null;
      }
      return { origin, target };
    };

    const animate = (now) => {
      if (finished) return;
      const geometry = measure();
      if (!geometry) {
        finish();
        return;
      }
      if (!pathsRef.current[0]) {
        frame = window.requestAnimationFrame(animate);
        return;
      }
      startedAt ??= now;
      const progress = clamp((now - startedAt) / duration, 0, 1);
      const { shape, source, attached } = shapeAt(progress, geometry.origin, geometry.target, isAqua);
      const outline = connectedOutline(shape, source, attached);
      pathsRef.current.forEach((path) => path?.setAttribute("d", outline));
      const edge = Math.min(shape.radius, shape.height / 2);
      highlightRef.current?.setAttribute("d", `M ${shape.x - shape.width / 2 + edge * 0.65} ${shape.y + edge * 0.8} Q ${shape.x - shape.width / 2 + edge * 0.75} ${shape.y + 3} ${shape.x - shape.width / 2 + edge * 1.6} ${shape.y + 3} H ${shape.x + shape.width * 0.22}`);
      lowerHighlightRef.current?.setAttribute("d", `M ${shape.x + shape.width * 0.08} ${shape.y + shape.height - 3} H ${shape.x + shape.width / 2 - edge} Q ${shape.x + shape.width / 2 - 3} ${shape.y + shape.height - 3} ${shape.x + shape.width / 2 - 3} ${shape.y + shape.height - edge}`);
      pressureRef.current?.setAttribute("cx", source.x);
      pressureRef.current?.setAttribute("cy", source.y);
      pressureRef.current?.setAttribute("rx", 36 + Math.sin(progress * Math.PI) * 20);
      pressureRef.current?.setAttribute("opacity", Math.max(0, 0.7 * (1 - progress / 0.72)));
      if (progress === 1) finish();
      else frame = window.requestAnimationFrame(animate);
    };

    const findTarget = () => {
      const article = [...document.querySelectorAll("[data-message-id]")].find((node) => node.dataset.messageId === message.id);
      targetNode = article?.querySelector(".message__bubble") || article;
      if ((!targetNode || !originRef?.current) && attempts++ < 8) {
        frame = window.requestAnimationFrame(findTarget);
        return;
      }
      if (!measure()) {
        finish();
        return;
      }
      setReady(true);
      frame = window.requestAnimationFrame(animate);
    };
    // Let React reserve the message and the intelligent scroller settle first.
    frame = window.requestAnimationFrame(() => {
      frame = window.requestAnimationFrame(findTarget);
    });
    timeout = window.setTimeout(finish, duration + 360);
    window.addEventListener("resize", finish);
    window.addEventListener("wheel", finish, { capture: true, passive: true });
    window.addEventListener("touchmove", finish, { capture: true, passive: true });
    window.addEventListener("keydown", interruptKeyboard);
    window.visualViewport?.addEventListener("resize", finish);
    function interruptKeyboard(event) {
      if (["PageUp", "PageDown", "Home", "End"].includes(event.key) && event.target?.tagName !== "TEXTAREA") finish();
    }

    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(timeout);
      window.removeEventListener("resize", finish);
      window.removeEventListener("wheel", finish, true);
      window.removeEventListener("touchmove", finish, true);
      window.removeEventListener("keydown", interruptKeyboard);
      window.visualViewport?.removeEventListener("resize", finish);
      // A real unmount reveals the reserved message. StrictMode's replay starts a
      // newer lifecycle synchronously, so its rehearsal cleanup does not end birth.
      if (!finished) queueMicrotask(() => {
        if (lifecycleRef.current === lifecycle) onCompleteRef.current?.(message.id);
      });
    };
  }, [message.id, message.role, originRef, reducedMotion]);

  if (!ready || reducedMotion) return null;
  return createPortal(
    <svg className={`message-birth${message.role === "aqua" ? " message-birth--aqua" : ""}`} aria-hidden="true">
      <defs>
        <linearGradient id={`${gradientId}-glass`} x1="0" y1="0" x2="0.32" y2="1">
          <stop offset="0" stopColor="#e2fbff" stopOpacity="0.55" />
          <stop offset="0.06" stopColor="#88cddc" stopOpacity="0.3" />
          <stop offset="0.28" stopColor="#304d5b" stopOpacity="0.52" />
          <stop offset="0.65" stopColor="#172e40" stopOpacity="0.54" />
          <stop offset="0.93" stopColor="#4a94ae" stopOpacity="0.4" />
          <stop offset="1" stopColor="#a2e6f1" stopOpacity="0.48" />
        </linearGradient>
        <radialGradient id={`${gradientId}-reflection`} cx="0.2" cy="0.02" r="0.85">
          <stop offset="0" stopColor="#f5ffff" stopOpacity="0.44" />
          <stop offset="0.1" stopColor="#e3fbff" stopOpacity="0.22" />
          <stop offset="0.34" stopColor="#abefff" stopOpacity="0" />
          <stop offset="0.78" stopColor="#68cae9" stopOpacity="0.03" />
          <stop offset="1" stopColor="#a6e9f5" stopOpacity="0.22" />
        </radialGradient>
      </defs>
      <ellipse ref={pressureRef} className="message-birth__pressure" ry="4" />
      <path ref={(node) => { pathsRef.current[0] = node; }} className="message-birth__body" fill={`url(#${gradientId}-glass)`} />
      <path ref={(node) => { pathsRef.current[1] = node; }} className="message-birth__reflection" fill={`url(#${gradientId}-reflection)`} />
      <path ref={highlightRef} className="message-birth__highlight" />
      <path ref={lowerHighlightRef} className="message-birth__highlight message-birth__highlight--lower" />
    </svg>,
    document.body
  );
}
