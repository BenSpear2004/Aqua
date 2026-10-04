import React, { useEffect, useState } from "react";
import { useReducedMotion } from "../../hooks/useReducedMotion.js";
import "./water-sparkles.css";

// Stable positions keep the ambient light from jumping when chat state changes.
const sparkles = Array.from({ length: 44 }, (_, index) => ({
  left: 2 + ((index * 0.61803398875 + 0.13) % 1) * 96,
  top: 2 + ((index * 0.75487766625 + 0.29) % 1) * 96,
  size: index % 7 === 0 ? 5 : 1.8 + (index % 4) * 0.6,
  drift: 17 + (index % 9) * 1.7,
  shimmer: 4.6 + (index % 6) * 0.8,
  delay: -index * 2.31,
  sway: (index % 2 ? 1 : -1) * (8 + index % 13),
}));

export default function WaterSparkles() {
  const reducedMotion = useReducedMotion();
  const [hidden, setHidden] = useState(() => document.hidden);

  useEffect(() => {
    const update = () => setHidden(document.hidden);
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);

  return (
    <div
      className={`water-sparkles${reducedMotion ? " water-sparkles--still" : ""}`}
      data-paused={hidden ? "true" : undefined}
      aria-hidden="true"
    >
      {sparkles.map((sparkle, index) => (
        <span
          key={index}
          className={`water-sparkle${index % 7 === 0 ? " water-sparkle--glint" : ""}`}
          style={{
            left: `${sparkle.left}%`,
            top: `${sparkle.top}%`,
            "--sparkle-size": `${sparkle.size}px`,
            "--sparkle-drift": `${sparkle.drift}s`,
            "--sparkle-shimmer": `${sparkle.shimmer}s`,
            "--sparkle-delay": `${sparkle.delay}s`,
            "--sparkle-sway": `${sparkle.sway}px`,
          }}
        >
          <span className="water-sparkle__light" />
        </span>
      ))}
    </div>
  );
}
