import { useRef, useState, useEffect } from 'react';
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

interface OrbitIconProps {
  entity: OrbitEntity;
  isNew?: boolean;
  isSelected?: boolean;
  onSelect?: (id: string) => void;
  interactive?: boolean;
}

function OrbitIcon({ entity, isNew, isSelected, onSelect, interactive }: OrbitIconProps) {
  const groupRef = useRef<THREE.Group>(null!);
  const angleRef = useRef(entity.orbitPhase);
  const yOffset = useRef((Math.random() - 0.5) * 0.2);
  const [entered, setEntered] = useState(false);
  const entryProgress = useRef(0);

  useEffect(() => {
    if (isNew) {
      // Start entrance animation
      const timer = setTimeout(() => setEntered(true), 50);
      return () => clearTimeout(timer);
    } else {
      setEntered(true);
      entryProgress.current = 1;
    }
  }, [isNew]);

  useFrame((_, delta) => {
    // Update orbit angle
    angleRef.current += entity.orbitSpeed * delta;

    // Entrance animation
    if (entered && entryProgress.current < 1) {
      entryProgress.current = Math.min(entryProgress.current + delta * 1.8, 1);
    }

    const progress = entryProgress.current;
    // Spring-like ease
    const eased = 1 - Math.pow(1 - progress, 3);

    if (groupRef.current) {
      const targetX = Math.cos(angleRef.current) * entity.orbitRadius;
      const targetZ = Math.sin(angleRef.current) * entity.orbitRadius;
      const targetY = yOffset.current;

      // During entrance: start from top, animate to orbit
      const startY = 3.0;
      const startX = 0;
      const startZ = 0;

      groupRef.current.position.x = startX + (targetX - startX) * eased;
      groupRef.current.position.y = startY + (targetY - startY) * eased;
      groupRef.current.position.z = startZ + (targetZ - startZ) * eased;
    }
  });

  const scale = isSelected ? 1.5 : 1;
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
            transition: 'transform 0.3s ease',
            transform: `scale(${scale})`,
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
                ? `0 0 20px ${entity.color}60, 0 0 40px ${entity.color}30`
                : `0 0 10px ${entity.color}30`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              overflow: 'hidden',
              transition: 'border-color 0.3s, box-shadow 0.3s',
            }}
          >
            <img
              src={iconSrc}
              alt={entity.label}
              style={{
                width: 32,
                height: 32,
                objectFit: 'contain',
              }}
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
        />
      ))}
    </group>
  );
}
