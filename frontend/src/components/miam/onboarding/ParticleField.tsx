import { useRef, useEffect } from 'react';

export interface PendingBurst {
  id: string;
  fromX: number; // 0-1 normalised screen coords
  fromY: number;
  targetOrbitRadius: number;
  color: string;
  label: string;
}

const MAX_PARTICLES = 200;
const PARTICLES_PER_BURST = 12;

interface Particle {
  active: boolean;
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number; // 1 → 0
  size: number;
}

export default function ParticleField({
  pendingBurst,
  onBurstComplete,
}: {
  pendingBurst: PendingBurst | null;
  onBurstComplete?: () => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const particlesRef = useRef<Particle[]>(
    Array.from({ length: MAX_PARTICLES }, () => ({
      active: false,
      x: 0, y: 0, vx: 0, vy: 0,
      life: 0, size: 2,
    }))
  );
  const processedBursts = useRef(new Set<string>());
  const rafRef = useRef<number>(0);

  // Spawn burst on pending change
  useEffect(() => {
    if (!pendingBurst || processedBursts.current.has(pendingBurst.id)) return;
    processedBursts.current.add(pendingBurst.id);

    const canvas = canvasRef.current;
    if (!canvas) return;
    const cx = pendingBurst.fromX * canvas.offsetWidth;
    const cy = pendingBurst.fromY * canvas.offsetHeight;
    const centerX = canvas.offsetWidth / 2;
    const centerY = canvas.offsetHeight / 2;

    let spawned = 0;
    for (let i = 0; i < MAX_PARTICLES && spawned < PARTICLES_PER_BURST; i++) {
      const p = particlesRef.current[i];
      if (p.active) continue;
      p.active = true;
      p.x = cx + (Math.random() - 0.5) * 20;
      p.y = cy + (Math.random() - 0.5) * 20;
      const dx = centerX - p.x;
      const dy = centerY - p.y;
      const len = Math.sqrt(dx * dx + dy * dy) || 1;
      const speed = 60 + Math.random() * 80;
      p.vx = (dx / len) * speed + (Math.random() - 0.5) * 40;
      p.vy = (dy / len) * speed + (Math.random() - 0.5) * 40;
      p.life = 1.0;
      p.size = 2 + Math.random() * 2;
      spawned++;
    }

    if (onBurstComplete) setTimeout(onBurstComplete, 600);
  }, [pendingBurst, onBurstComplete]);

  // Single RAF loop — draw particles on 2D canvas
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d')!;
    let last = performance.now();

    const resize = () => {
      canvas.width = canvas.offsetWidth;
      canvas.height = canvas.offsetHeight;
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);

    const loop = (now: number) => {
      const dt = Math.min((now - last) / 1000, 0.05);
      last = now;

      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const damping = Math.pow(0.96, dt * 60);

      for (const p of particlesRef.current) {
        if (!p.active) continue;
        p.life -= dt * 1.2;
        if (p.life <= 0) { p.active = false; continue; }
        p.vx *= damping;
        p.vy *= damping;
        p.x += p.vx * dt;
        p.y += p.vy * dt;

        const alpha = p.life * 0.35;
        ctx.beginPath();
        const grad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.size * 2);
        grad.addColorStop(0, `rgba(212,168,85,${alpha})`);
        grad.addColorStop(1, 'rgba(212,168,85,0)');
        ctx.fillStyle = grad;
        ctx.arc(p.x, p.y, p.size * 2, 0, Math.PI * 2);
        ctx.fill();
      }

      rafRef.current = requestAnimationFrame(loop);
    };

    rafRef.current = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(rafRef.current);
      ro.disconnect();
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
        zIndex: 1,
      }}
    />
  );
}
