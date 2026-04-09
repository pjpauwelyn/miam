import { Canvas } from '@react-three/fiber';
import CenterGlow from './CenterGlow';
import ParticleField, { type PendingBurst } from './ParticleField';
import OrbitLabels, { type OrbitEntity } from './OrbitLabels';

interface GravityCanvasProps {
  entities: OrbitEntity[];
  pendingBurst: PendingBurst | null;
  onBurstComplete?: () => void;
  newEntityId?: string | null;
  interactive?: boolean;
  selectedId?: string | null;
  onSelect?: (id: string) => void;
}

export default function GravityCanvas({
  entities,
  pendingBurst,
  onBurstComplete,
  newEntityId,
  interactive,
  selectedId,
  onSelect,
}: GravityCanvasProps) {
  return (
    <Canvas
      style={{
        position: 'absolute',
        inset: 0,
        zIndex: 1,
        // Canvas itself never captures pointer events — the Html elements inside do
        pointerEvents: 'none',
      }}
      camera={{ position: [0, 0, 6], fov: 45 }}
      gl={{ alpha: true, antialias: true, powerPreference: 'high-performance' }}
      dpr={1}
    >
      <CenterGlow />
      <ParticleField pendingBurst={pendingBurst} onBurstComplete={onBurstComplete} />
      <OrbitLabels
        entities={entities}
        newEntityId={newEntityId}
        selectedId={selectedId}
        onSelect={onSelect}
        interactive={interactive}
      />
    </Canvas>
  );
}

export type { OrbitEntity, PendingBurst };
