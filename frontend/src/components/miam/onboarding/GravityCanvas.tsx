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
    <div
      style={{
        position: 'absolute',
        inset: 0,
        zIndex: 1,
        pointerEvents: 'none',
        overflow: 'hidden',
      }}
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
    </div>
  );
}

export type { OrbitEntity, PendingBurst };
