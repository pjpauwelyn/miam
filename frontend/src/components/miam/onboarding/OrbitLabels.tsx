import { useRef, useEffect } from 'react';
import { useFrame } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import * as THREE from 'three';

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

// Physics constants
const GRAVITY = 0.18;        // attraction force toward centre
const DAMPING = 0.97;        // velocity damping per frame
const RESTITUTION = 0.5;     // bounce restitution coefficient
const ENTITY_RADIUS = 0.52;  // collision radius in world units (~30px at fov 45 z=6)
const NOISE_FORCE = 0.003;   // subtle random drift to keep cluster alive
const REPULSE_CENTRE = 0.30; // radius around centre where entities are gently repelled

interface PhysicsBody {
  id: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
}

// Shared mutable physics state — lives outside React to avoid re-render overhead
const physicsMap: Map<string, PhysicsBody> = new Map();

interface OrbitIconProps {
  entity: OrbitEntity;
  isNew?: boolean;
  isSelected?: boolean;
  onSelect?: (id: string) => void;
  interactive?: boolean;
  allEntities: OrbitEntity[];
}

function OrbitIcon({ entity, isNew, isSelected, onSelect, interactive, allEntities }: OrbitIconProps) {
  const groupRef = useRef<THREE.Group>(null!);

  // Initialise or re-use physics body
  useEffect(() => {
    if (!physicsMap.has(entity.id)) {
      // New entities enter from a random edge
      const angle = Math.random() * Math.PI * 2;
      const edgeDist = 3.5;
      physicsMap.set(entity.id, {
        id: entity.id,
        x: isNew ? Math.cos(angle) * edgeDist : (Math.random() - 0.5) * 2,
        y: isNew ? Math.sin(angle) * edgeDist : (Math.random() - 0.5) * 2,
        vx: 0,
        vy: 0,
      });
    }
    return () => {
      // Leave body in map — it may be re-used if component remounts
    };
  }, [entity.id, isNew]);

  useFrame((_, delta) => {
    const body = physicsMap.get(entity.id);
    if (!body || !groupRef.current) return;

    const dt = Math.min(delta, 0.05); // clamp delta to avoid large jumps

    // 1. Gravity toward centre (with soft repulsion near centre)
    const dist = Math.sqrt(body.x * body.x + body.y * body.y);
    if (dist > 0.01) {
      const dirX = -body.x / dist;
      const dirY = -body.y / dist;
      if (dist > REPULSE_CENTRE) {
        body.vx += dirX * GRAVITY * dt;
        body.vy += dirY * GRAVITY * dt;
      } else {
        // gentle push away from very centre so entities ring it rather than stack
        body.vx -= dirX * GRAVITY * 0.5 * dt;
        body.vy -= dirY * GRAVITY * 0.5 * dt;
      }
    }

    // 2. Circle-circle collision resolution against all other entities
    for (const other of allEntities) {
      if (other.id === entity.id) continue;
      const ob = physicsMap.get(other.id);
      if (!ob) continue;
      const dx = body.x - ob.x;
      const dy = body.y - ob.y;
      const d = Math.sqrt(dx * dx + dy * dy);
      const minDist = ENTITY_RADIUS * 2;
      if (d < minDist && d > 0.001) {
        // Separate
        const overlap = minDist - d;
        const nx = dx / d;
        const ny = dy / d;
        body.x += nx * overlap * 0.5;
        body.y += ny * overlap * 0.5;
        ob.x  -= nx * overlap * 0.5;
        ob.y  -= ny * overlap * 0.5;
        // Exchange velocity along collision normal with restitution
        const relVx = body.vx - ob.vx;
        const relVy = body.vy - ob.vy;
        const dot = relVx * nx + relVy * ny;
        if (dot < 0) {
          const impulse = dot * (1 + RESTITUTION);
          body.vx -= impulse * nx * 0.5;
          body.vy -= impulse * ny * 0.5;
          ob.vx   += impulse * nx * 0.5;
          ob.vy   += impulse * ny * 0.5;
        }
      }
    }

    // 3. Damping
    body.vx *= DAMPING;
    body.vy *= DAMPING;

    // 4. Tiny random perturbation (keeps cluster alive)
    body.vx += (Math.random() - 0.5) * NOISE_FORCE;
    body.vy += (Math.random() - 0.5) * NOISE_FORCE;

    // 5. Integrate position
    body.x += body.vx;
    body.y += body.vy;

    // 6. Apply to Three.js group (flat 2D at Z=0)
    groupRef.current.position.set(body.x, body.y, 0);
  });

  const iconSrc = entity.iconUrl || iconDiet;

  return (
    <group ref={groupRef}>
      <Html
        center
        style={{
          pointerEvents: interactive ? 'auto' : 'none',
          userSelect: 'none',
          whiteSpace: 'nowrap',
        }}
      >
        <div
          onClick={() => interactive && onSelect?.(entity.id)}
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            cursor: interactive ? 'pointer' : 'default',
            transition: 'transform 0.25s ease',
            transform: isSelected ? 'scale(1.25)' : 'scale(1)',
          }}
        >
          {/* Icon circle */}
          <div
            style={{
              width: 52,
              height: 52,
              borderRadius: '50%',
              background: 'rgba(20, 20, 20, 0.9)',
              border: `2px solid ${isSelected ? entity.color : `${entity.color}70`}`,
              boxShadow: isSelected
                ? `0 0 20px ${entity.color}70, 0 0 40px ${entity.color}40`
                : `0 0 10px ${entity.color}30`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              overflow: 'hidden',
              transition: 'border-color 0.25s, box-shadow 0.25s',
            }}
          >
            <img
              src={iconSrc}
              alt={entity.label}
              style={{ width: 32, height: 32, objectFit: 'contain' }}
              draggable={false}
              onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
            />
          </div>
          {/* Label */}
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
            }}
          >
            {entity.label}
          </div>
        </div>
      </Html>
    </group>
  );
}

interface OrbitLabelsProps {
  entities: OrbitEntity[];
  newEntityId?: string | null;
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  interactive?: boolean;
}

export default function OrbitLabels({ entities, newEntityId, selectedId, onSelect, interactive }: OrbitLabelsProps) {
  return (
    <group>
      {entities.map((entity) => (
        <OrbitIcon
          key={entity.id}
          entity={entity}
          isNew={entity.id === newEntityId}
          isSelected={entity.id === selectedId}
          onSelect={onSelect}
          interactive={interactive}
          allEntities={entities}
        />
      ))}
    </group>
  );
}
