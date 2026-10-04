import React from "react";
import staticLogoUrl from "../../assets/models/AQUA_V2_Final_static.svg?url";
import "./model.css";

export default function AquaLogoFallback({ compact = false }) {
  return (
    <div className={`logo-fallback${compact ? " logo-fallback--compact" : ""}`} aria-hidden="true">
      <img src={staticLogoUrl} alt="" draggable="false" />
    </div>
  );
}
