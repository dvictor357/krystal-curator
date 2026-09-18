"use client";
import { useEffect, useRef } from "react";

/**
 * Breathing amber dot grid behind the page. One canvas, 30 fps cap, paused when the
 * tab is hidden, skipped entirely under prefers-reduced-motion. Pointer-events none.
 */
export function AmbientField({ density = 44 }: { density?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    let width = 0;
    let height = 0;
    let dpr = 1;
    let frame = 0;
    let last = 0;
    let running = true;
    // A few slow drifters that light up nearby grid dots.
    const drifters = Array.from({ length: 5 }, (_, i) => ({
      x: Math.random(),
      y: Math.random(),
      vx: (Math.random() - 0.5) * 0.00012,
      vy: (Math.random() - 0.5) * 0.00012,
      phase: i * 1.3,
    }));
    function resize() {
      dpr = Math.min(2, window.devicePixelRatio || 1);
      width = window.innerWidth;
      height = window.innerHeight;
      canvas!.width = width * dpr;
      canvas!.height = height * dpr;
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    function draw(t: number) {
      if (!running) return;
      frame = requestAnimationFrame(draw);
      if (t - last < 33) return; // ~30 fps
      last = t;
      const time = t / 1000;
      ctx!.clearRect(0, 0, width, height);
      for (const d of drifters) {
        d.x = (d.x + d.vx * 16 + 1) % 1;
        d.y = (d.y + d.vy * 16 + 1) % 1;
      }
      const cols = Math.ceil(width / density) + 1;
      const rows = Math.ceil(height / density) + 1;
      for (let i = 0; i < cols; i++) {
        for (let j = 0; j < rows; j++) {
          const x = i * density + density / 2;
          const y = j * density + density / 2;
          // Slow breathing wave across the grid.
          const breathe =
            0.5 + 0.5 * Math.sin(time * 0.6 + i * 0.35 + j * 0.22);
          let glow = 0;
          for (const d of drifters) {
            const dx = x - d.x * width;
            const dy = y - d.y * height;
            const dist = Math.sqrt(dx * dx + dy * dy);
            if (dist < 160) glow = Math.max(glow, 1 - dist / 160);
          }
          const alpha = 0.035 + breathe * 0.045 + glow * 0.45;
          const radius = 1 + glow * 1.2;
          ctx!.beginPath();
          ctx!.arc(x, y, radius, 0, Math.PI * 2);
          ctx!.fillStyle = `rgba(255, 154, 0, ${alpha.toFixed(3)})`;
          ctx!.fill();
        }
      }
    }
    function visibility() {
      running = document.visibilityState === "visible";
      if (running) {
        last = 0;
        frame = requestAnimationFrame(draw);
      } else cancelAnimationFrame(frame);
    }
    resize();
    window.addEventListener("resize", resize);
    document.addEventListener("visibilitychange", visibility);
    frame = requestAnimationFrame(draw);
    return () => {
      running = false;
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", resize);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [density]);
  return <canvas ref={ref} className="ambient" aria-hidden="true" />;
}
