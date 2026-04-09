import { useRef, useEffect } from 'react';

export interface OrbitEntity {
  id: string;
  label: string;
  color: string;
  orbitRadius: number;
  orbitSpeed: number;
  orbitPhase: number;
  size: number;
  iconUrl?: string;
  answerSummary?: string;
}

// Icon mapping
import iconDiet from '@assets/icon-diet.png';
import iconCuisine from '@assets/icon-cuisine.png';
import iconFlavors from '@assets/icon-flavors.png';
import iconTextures from '@assets/icon-textures.png';
import iconSkill from '@assets/icon-skill.png';
import iconKitchen from '@assets/icon-kitchen.png';
import iconBudget from '@assets/icon-budget.png';
import iconVibe from '@assets/icon-vibe.png';
import iconAdventure from '@assets/icon-adventure.png';
import iconNutrition from '@assets/icon-nutrition.png';
import iconSocial from '@assets/icon-social.png';
import iconHabits from '@assets/icon-habits.png';
import iconValues from '@assets/icon-values.png';
import iconInterests from '@assets/icon-interests.png';
import iconLocation from '@assets/icon-location.png';
import iconInspiration from '@assets/icon-inspiration.png';

const iconMap: Record<string, string> = {
  'icon-diet.png': iconDiet,
  'icon-cuisine.png': iconCuisine,
  'icon-flavors.png': iconFlavors,
  'icon-textures.png': iconTextures,
  'icon-skill.png': iconSkill,
  'icon-kitchen.png': iconKitchen,
  'icon-budget.png': iconBudget,
  'icon-vibe.png': iconVibe,
  'icon-adventure.png': iconAdventure,
  'icon-nutrition.png': iconNutrition,
  'icon-social.png': iconSocial,
  'icon-habits.png': iconHabits,
  'icon-values.png': iconValues,
  'icon-interests.png': iconInterests,
  'icon-location.png': iconLocation,
  'icon-inspiration.png': iconInspiration,
};

export function getIconUrl(iconFile: string): string {
  return iconMap[iconFile] || iconDiet;
}

// ─── Physics constants ──────────────────────────────────────────────────────────────────────────────────
const GRAVITY       = 0.0004;  // px/frame² attraction toward centre
const DAMPING       = 0.985;   // velocity multiplier per frame — high = lazy float
const RESTITUTION   = 0.4;     // bounce coefficient
const ENTITY_RADIUS = 48;      // px — collision circle
const REPULSE_RADIUS = 60;     // px — soft repulsion around centre
const NOISE         = 0.00015; // tiny random nudge per frame

interface Body {
  id: string;
  x: number;  // px offset from container centre
  y: number;
  vx: number;
  vy: number;
}

interface OrbitLabelsProps {
  entities: OrbitEntity[];
  newEntityId?: string | null;
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  interactive?: boolean;
}

export default function OrbitLabels({
  entities,
  newEntityId,
  selectedId,
  onSelect,
  interactive,
}: OrbitLabelsProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  // Map entity id → its DOM div ref
  const divRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  // Physics bodies — keyed by id, stable across renders
  const bodiesRef = useRef<Map<string, Body>>(new Map());
  const rafRef = useRef<number>(0);
  const entitiesRef = useRef(entities);
  entitiesRef.current = entities;
  const interactiveRef = useRef<boolean>(!!interactive);

  // Keep interactiveRef in sync with the prop so the RAF loop sees updates
  useEffect(() => {
    interactiveRef.current = !!interactive;
  }, [interactive]);

  // Initialise new bodies when entities list changes
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const hw = container.offsetWidth / 2;
    const hh = container.offsetHeight / 2;
    const maxR = Math.min(hw, hh) * 0.72;

    for (const e of entities) {
      if (!bodiesRef.current.has(e.id)) {
        const isNew = e.id === newEntityId;
        const angle = Math.random() * Math.PI * 2;
        const r = isNew ? maxR * 1.1 : maxR * (0.3 + Math.random() * 0.5);
        bodiesRef.current.set(e.id, {
          id: e.id,
          x: Math.cos(angle) * r,
          y: Math.sin(angle) * r,
          vx: 0,
          vy: 0,
        });
      }
    }
    // Remove stale bodies
    const ids = new Set(entities.map(e => e.id));
    for (const id of bodiesRef.current.keys()) {
      if (!ids.has(id)) bodiesRef.current.delete(id);
    }
  }, [entities, newEntityId]);

  // Single RAF physics + render loop
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const loop = () => {
      const bodies = Array.from(bodiesRef.current.values());
      const n = bodies.length;

      // 1. Gravity toward centre + centre repulsion
      for (const body of bodies) {
        const dist = Math.sqrt(body.x * body.x + body.y * body.y);
        if (dist > 0.5) {
          const nx = -body.x / dist;
          const ny = -body.y / dist;

          if (interactiveRef.current) {
            // Gather mode: strong pull toward center for completion screen
            const GATHER_GRAVITY = 0.006;
            body.vx += nx * GATHER_GRAVITY * dist;
            body.vy += ny * GATHER_GRAVITY * dist;
          } else {
            // Normal float mode
            if (dist > REPULSE_RADIUS) {
              body.vx += nx * GRAVITY * dist;
              body.vy += ny * GRAVITY * dist;
            } else {
              body.vx -= nx * GRAVITY * REPULSE_RADIUS * 0.5;
              body.vy -= ny * GRAVITY * REPULSE_RADIUS * 0.5;
            }
          }
        }
      }

      // 2. Pairwise collision resolution — sequential, one pass
      for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
          const a = bodies[i];
          const b = bodies[j];
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const d = Math.sqrt(dx * dx + dy * dy);
          const minD = ENTITY_RADIUS * 2;
          if (d < minD && d > 0.1) {
            const overlap = (minD - d) / 2;
            const nx = dx / d;
            const ny = dy / d;
            a.x += nx * overlap;
            a.y += ny * overlap;
            b.x -= nx * overlap;
            b.y -= ny * overlap;
            const rvx = a.vx - b.vx;
            const rvy = a.vy - b.vy;
            const dot = rvx * nx + rvy * ny;
            if (dot < 0) {
              const imp = dot * (1 + RESTITUTION) * 0.5;
              a.vx -= imp * nx;
              a.vy -= imp * ny;
              b.vx += imp * nx;
              b.vy += imp * ny;
            }
          }
        }
      }

      // 3. Damping + noise + integrate + clamp
      const hw = container.offsetWidth / 2;
      const hh = container.offsetHeight / 2;
      const maxR = Math.min(hw, hh) - ENTITY_RADIUS - 4;
      for (const b of bodies) {
        b.vx = b.vx * DAMPING + (Math.random() - 0.5) * NOISE;
        b.vy = b.vy * DAMPING + (Math.random() - 0.5) * NOISE;
        b.x += b.vx;
        b.y += b.vy;
        // Soft boundary — push back if outside
        const r = Math.sqrt(b.x * b.x + b.y * b.y);
        if (r > maxR) {
          const scale = maxR / r;
          b.x *= scale;
          b.y *= scale;
          b.vx *= -RESTITUTION;
          b.vy *= -RESTITUTION;
        }
      }

      // 4. Write positions to DOM via CSS transform
      for (const b of bodies) {
        const el = divRefs.current.get(b.id);
        if (el) {
          el.style.transform = `translate(calc(-50% + ${b.x}px), calc(-50% + ${b.y}px))`;
        }
      }

      rafRef.current = requestAnimationFrame(loop);
    };

    rafRef.current = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(rafRef.current);
  }, []);

  return (
    <div
      ref={containerRef}
      style={{
        position: 'absolute',
        inset: 0,
        pointerEvents: 'none',
        zIndex: 3,
      }}
    >
      {entities.map((entity) => {
        const iconSrc = entity.iconUrl
          ? iconMap[entity.iconUrl] || entity.iconUrl
          : iconDiet;
        const isSelected = entity.id === selectedId;
        return (
          <div
            key={entity.id}
            ref={(el) => {
              if (el) divRefs.current.set(entity.id, el);
              else divRefs.current.delete(entity.id);
            }}
            onClick={() => interactive && onSelect?.(entity.id)}
            style={{
              position: 'absolute',
              top: '50%',
              left: '50%',
              transform: 'translate(-50%, -50%)',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              cursor: interactive ? 'pointer' : 'default',
              pointerEvents: interactive ? 'auto' : 'none',
              transition: 'transform 0.25s ease',
              willChange: 'transform',
              userSelect: 'none',
            }}
          >
            <div
              style={{
                width: 52,
                height: 52,
                borderRadius: '50%',
                background: 'rgba(20,20,20,0.9)',
                border: `2px solid ${
                  isSelected ? entity.color : `${entity.color}70`
                }`,
                boxShadow: isSelected
                  ? `0 0 20px ${entity.color}70, 0 0 40px ${entity.color}40`
                  : `0 0 10px ${entity.color}30`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                overflow: 'hidden',
                transition: 'border-color 0.25s, box-shadow 0.25s, transform 0.25s',
                transform: isSelected ? 'scale(1.25)' : 'scale(1)',
              }}
            >
              <img
                src={iconSrc}
                alt={entity.label}
                style={{ width: 32, height: 32, objectFit: 'contain' }}
                draggable={false}
                onError={(e) => {
                  (e.target as HTMLImageElement).style.display = 'none';
                }}
              />
            </div>
            <div
              style={{
                marginTop: 5,
                fontSize: '11px',
                fontWeight: 600,
                fontFamily: 'Inter, sans-serif',
                color: entity.color,
                textShadow: `0 0 6px ${entity.color}44`,
                opacity: 0.9,
                letterSpacing: '0.03em',
                textAlign: 'center',
                whiteSpace: 'nowrap',
              }}
            >
              {entity.label}
            </div>
          </div>
        );
      })}
    </div>
  );
}
