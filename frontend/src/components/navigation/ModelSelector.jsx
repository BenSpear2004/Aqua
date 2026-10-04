import React, { useEffect, useId, useLayoutEffect, useRef, useState } from "react";

export default function ModelSelector({ models = [], selectedModelId, onSelectModel }) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const id = useId();
  const rootRef = useRef(null);
  const triggerRef = useRef(null);
  const optionRefs = useRef([]);
  const searchRef = useRef({ value: "", time: 0 });
  const selected = models.find((model) => model.id === selectedModelId);
  const selectedIndex = Math.max(0, models.findIndex((model) => model.id === selectedModelId));

  const close = (restoreFocus = false) => {
    setOpen(false);
    searchRef.current = { value: "", time: 0 };
    if (restoreFocus) triggerRef.current?.focus();
  };
  const show = (index = selectedIndex) => {
    if (!models.length) return;
    searchRef.current = { value: "", time: 0 };
    setActiveIndex(index);
    setOpen(true);
  };

  useLayoutEffect(() => {
    if (open) optionRefs.current[activeIndex]?.focus();
  }, [open, activeIndex]);

  useEffect(() => {
    if (!open) return undefined;
    const outside = (event) => {
      if (!rootRef.current?.contains(event.target)) setOpen(false);
    };
    const escape = (event) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener("pointerdown", outside, true);
    document.addEventListener("focusin", outside, true);
    document.addEventListener("keydown", escape, true);
    return () => {
      document.removeEventListener("pointerdown", outside, true);
      document.removeEventListener("focusin", outside, true);
      document.removeEventListener("keydown", escape, true);
    };
  }, [open]);

  const handleMenuKey = (event) => {
    if (event.key === "Tab") {
      // Tab continues through the sidebar's normal controls after dismissing.
      close(true);
      return;
    }
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      if (event.key === "Home") setActiveIndex(0);
      else if (event.key === "End") setActiveIndex(models.length - 1);
      else setActiveIndex((index) => (index + (event.key === "ArrowDown" ? 1 : -1) + models.length) % models.length);
      return;
    }
    if (event.key.length !== 1 || event.key === " " || event.ctrlKey || event.metaKey || event.altKey) return;
    event.preventDefault();
    const now = Date.now();
    const value = (now - searchRef.current.time < 650 ? searchRef.current.value : "") + event.key.toLocaleLowerCase();
    searchRef.current = { value, time: now };
    const query = [...value].every((character) => character === value[0]) ? value[0] : value;
    for (let offset = 1; offset <= models.length; offset += 1) {
      const index = (activeIndex + offset) % models.length;
      if (models[index].name.toLocaleLowerCase().startsWith(query)) {
        setActiveIndex(index);
        break;
      }
    }
  };

  return (
    <div className="model-selector" ref={rootRef} data-model-menu-open={open ? "true" : undefined}>
      <span className="model-selector__label" id={`${id}-label`}>AI model</span>
      <button
        className="model-selector__trigger"
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? `${id}-menu` : undefined}
        aria-labelledby={`${id}-label ${id}-name`}
        disabled={!models.length}
        onClick={() => open ? close(true) : show()}
        onKeyDown={(event) => {
          if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
          event.preventDefault();
          show(event.key === "ArrowDown" ? 0 : models.length - 1);
        }}
      >
        <span className="model-selector__name" id={`${id}-name`}>{selected?.name ?? "Select a model"}</span>
        <svg className="model-selector__chevron" viewBox="0 0 20 20" aria-hidden="true"><path d="m5 7.5 5 5 5-5" /></svg>
      </button>
      {open && (
        <div className="model-selector__menu" id={`${id}-menu`} role="menu" aria-label="AI models" onKeyDown={handleMenuKey}>
          {models.map((model, index) => (
            <button
              key={model.id}
              type="button"
              role="menuitemradio"
              className="model-selector__option"
              data-model-id={model.id}
              aria-checked={model.id === selectedModelId}
              tabIndex={index === activeIndex ? 0 : -1}
              ref={(element) => { optionRefs.current[index] = element; }}
              onFocus={() => setActiveIndex(index)}
              onClick={() => { onSelectModel?.(model.id); close(true); }}
            >
              <span className="model-selector__option-copy">
                <span className="model-selector__option-name">{model.name}</span>
                {model.description && <span className="model-selector__description">{model.description}</span>}
              </span>
              {model.id === selectedModelId && <svg className="model-selector__check" viewBox="0 0 20 20" aria-hidden="true"><path d="m4.5 10 3.5 3.5 7.5-7.5" /></svg>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
