import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useReducedMotion } from "../../hooks/useReducedMotion.js";

function makeBubble(id, surface, compact, fraction = Math.random()) {
  const size = Math.random() > 0.91 && !compact ? 36 + Math.random() * 4 : 14 + Math.random() * 20;
  const inset = size / 2 + 3;
  return {
    id,
    size,
    x: surface.left + Math.max(inset, Math.min(surface.width - inset, surface.width * fraction)),
    y: surface.top,
    drift: (Math.random() - 0.5) * 40,
    wobble: (Math.random() - 0.5) * 14,
    rise: (compact ? 70 : 80) + Math.random() * (compact ? 64 : 100),
    duration: 1700 + Math.random() * 1550,
    opacity: 0.5 + Math.random() * 0.34
  };
}

export default function ThinkingBubbles({ active, originRef, effectKey, cancelled = false }) {
  const reducedMotion = useReducedMotion();
  const [bubbles, setBubbles] = useState([]);
  const nextId = useRef(0);
  const pool = useRef([]);
  useEffect(() => {
    pool.current = [];
    setBubbles([]);
  }, [effectKey, reducedMotion, cancelled]);

  useEffect(() => {
    if (reducedMotion || !active || cancelled) return undefined;
    let spawnTimer = 0;
    const seedTimers = [];
    let disposed = false;
    const emit = (fraction) => {
      if (disposed) return;
      const now = performance.now();
      pool.current = pool.current.filter((bubble) => bubble.expires > now);
      const surface = originRef?.current?.getBoundingClientRect();
      const compact = window.innerWidth < 700;
      const limit = compact ? 6 : 10;
      if (surface?.width > 30 && surface.top > 0 && surface.top < window.innerHeight && pool.current.length < limit) {
        const bubble = makeBubble(nextId.current++, surface, compact, fraction);
        pool.current.push({ ...bubble, expires: now + bubble.duration + 100 });
        setBubbles([...pool.current]);
      }
    };
    const spawn = () => {
      emit();
      spawnTimer = window.setTimeout(spawn, 190 + Math.random() * (window.innerWidth < 700 ? 210 : 110));
    };
    // Populate all five regions early, with independent starts and lifetimes.
    [0.06, 0.28, 0.49, 0.71, 0.94].forEach((fraction, index) => {
      seedTimers.push(window.setTimeout(() => emit(fraction + (Math.random() - 0.5) * 0.04), index * (65 + Math.random() * 20)));
    });
    spawnTimer = window.setTimeout(spawn, 420);
    const clear = () => {
      pool.current = [];
      setBubbles([]);
    };
    window.addEventListener("resize", clear);
    window.addEventListener("wheel", clear, { capture: true, passive: true });
    window.addEventListener("touchmove", clear, { capture: true, passive: true });
    window.visualViewport?.addEventListener("resize", clear);
    return () => {
      disposed = true;
      window.clearTimeout(spawnTimer);
      seedTimers.forEach((timer) => window.clearTimeout(timer));
      window.removeEventListener("resize", clear);
      window.removeEventListener("wheel", clear, true);
      window.removeEventListener("touchmove", clear, true);
      window.visualViewport?.removeEventListener("resize", clear);
    };
  }, [active, effectKey, originRef, reducedMotion, cancelled]);

  const remove = (id) => {
    pool.current = pool.current.filter((bubble) => bubble.id !== id);
    setBubbles([...pool.current]);
  };
  if (reducedMotion || !bubbles.length) return null;

  return createPortal(
    <div className="thinking-bubbles" aria-hidden="true">
      {bubbles.map((bubble) => (
        <span
          className="thinking-bubble"
          key={bubble.id}
          style={{
            left: bubble.x - bubble.size / 2,
            top: bubble.y - bubble.size,
            "--bubble-size": `${bubble.size}px`,
            "--bubble-drift": `${bubble.drift}px`,
            "--bubble-wobble": `${bubble.wobble}px`,
            "--bubble-rise": `${bubble.rise}px`,
            "--bubble-duration": `${bubble.duration}ms`,
            "--bubble-opacity": bubble.opacity
          }}
          onAnimationEnd={(event) => {
            if (event.target === event.currentTarget) remove(bubble.id);
          }}
        >
          <span className="thinking-bubble__body" />
          <span className="thinking-bubble__rim" />
        </span>
      ))}
    </div>,
    document.body
  );
}
