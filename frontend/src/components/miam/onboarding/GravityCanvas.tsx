import { Canvas } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
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
        pointerEvents: interactive ? 'auto' : 'none',
      }}
      camera={{ position: [0, 0.3, 6], fov: 45 }}
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
      {interactive && (
        <OrbitControls
          enableZoom={false}
          enablePan={false}
          minPolarAngle={Math.PI / 2 - 0.26}
          maxPolarAngle={Math.PI / 2 + 0.26}
          enableDamping={true}
          dampingFactor={0.05}
        />
      )}
    </Canvas>
  );
}

export type { OrbitEntity, PendingBurst };
