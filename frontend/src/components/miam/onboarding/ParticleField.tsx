import { useRef, useEffect, useCallback, useMemo } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import * as THREE from 'three';

export interface PendingBurst {
  id: string;
  fromX: number;
  fromY: number;
  targetOrbitRadius: number;
  color: string;
  label: string;
}

// Reduced particle count — just subtle entrance dust
const MAX_PARTICLES = 200;
const PARTICLES_PER_BURST = 12;

const vertexShader = `
  attribute float aLife;
  attribute float aSize;
  
  varying float vLife;
  
  void main() {
    vLife = aLife;
    vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = aSize * (150.0 / -mvPosition.z);
    gl_Position = projectionMatrix * mvPosition;
  }
`;

const fragmentShader = `
  varying float vLife;
  
  void main() {
    vec2 center = gl_PointCoord - vec2(0.5);
    float dist = length(center);
    if (dist > 0.5) discard;
    
    float alpha = smoothstep(0.5, 0.1, dist);
    
    // Amber color, fading based on life
    vec3 amber = vec3(0.831, 0.659, 0.333);
    alpha *= vLife * 0.18;
    
    gl_FragColor = vec4(amber, alpha);
  }
`;

interface Particle {
  active: boolean;
  posX: number;
  posY: number;
  posZ: number;
  velX: number;
  velY: number;
  velZ: number;
  life: number;
  size: number;
}

export default function ParticleField({
  pendingBurst,
  onBurstComplete,
}: {
  pendingBurst: PendingBurst | null;
  onBurstComplete?: () => void;
}) {
  const pointsRef = useRef<THREE.Points>(null!);
  const { camera } = useThree();
  
  const particles = useRef<Particle[]>(
    Array.from({ length: MAX_PARTICLES }, () => ({
      active: false,
      posX: 0, posY: 0, posZ: 0,
      velX: 0, velY: 0, velZ: 0,
      life: 0,
      size: 2,
    }))
  );

  const processedBursts = useRef(new Set<string>());

  const { positions, lifes, sizes } = useMemo(() => {
    return {
      positions: new Float32Array(MAX_PARTICLES * 3),
      lifes: new Float32Array(MAX_PARTICLES),
      sizes: new Float32Array(MAX_PARTICLES),
    };
  }, []);

  const spawnBurst = useCallback((burst: PendingBurst) => {
    const ndcX = burst.fromX * 2 - 1;
    const ndcY = -(burst.fromY * 2 - 1);
    
    const vec = new THREE.Vector3(ndcX, ndcY, 0.5);
    vec.unproject(camera);
    vec.sub(camera.position).normalize();
    const distance = -camera.position.z / vec.z;
    const worldPos = camera.position.clone().add(vec.multiplyScalar(distance));

    let spawned = 0;
    for (let i = 0; i < MAX_PARTICLES && spawned < PARTICLES_PER_BURST; i++) {
      if (!particles.current[i].active) {
        const p = particles.current[i];
        p.active = true;
        p.posX = worldPos.x + (Math.random() - 0.5) * 0.2;
        p.posY = worldPos.y + (Math.random() - 0.5) * 0.2;
        p.posZ = (Math.random() - 0.5) * 0.05;
        
        // Aim at center
        const toCenter = new THREE.Vector2(-p.posX, -p.posY).normalize();
        const speed = 0.8 + Math.random() * 1.2;
        p.velX = toCenter.x * speed + (Math.random() - 0.5) * 0.5;
        p.velY = toCenter.y * speed + (Math.random() - 0.5) * 0.5;
        p.velZ = (Math.random() - 0.5) * 0.1;
        
        p.life = 1.0;
        p.size = 2 + Math.random() * 2;
        spawned++;
      }
    }
  }, [camera]);

  useEffect(() => {
    if (pendingBurst && !processedBursts.current.has(pendingBurst.id)) {
      processedBursts.current.add(pendingBurst.id);
      spawnBurst(pendingBurst);
      if (onBurstComplete) {
        setTimeout(onBurstComplete, 600);
      }
    }
  }, [pendingBurst, spawnBurst, onBurstComplete]);

  useFrame((_, delta) => {
    const dt = Math.min(delta, 0.05);
    const damping = Math.pow(0.96, dt * 60);
    
    for (let i = 0; i < MAX_PARTICLES; i++) {
      const p = particles.current[i];
      if (!p.active) {
        positions[i * 3] = 0;
        positions[i * 3 + 1] = 0;
        positions[i * 3 + 2] = -100;
        lifes[i] = 0;
        sizes[i] = 0;
        continue;
      }

      // Quick fade and settle
      p.life -= dt * 1.2;
      if (p.life <= 0) {
        p.active = false;
        continue;
      }

      p.velX *= damping;
      p.velY *= damping;
      p.velZ *= damping;
      
      p.posX += p.velX * dt;
      p.posY += p.velY * dt;
      p.posZ += p.velZ * dt;

      positions[i * 3] = p.posX;
      positions[i * 3 + 1] = p.posY;
      positions[i * 3 + 2] = p.posZ;
      lifes[i] = p.life;
      sizes[i] = p.size;
    }

    if (pointsRef.current) {
      const geom = pointsRef.current.geometry;
      geom.attributes.position.needsUpdate = true;
      geom.attributes.aLife.needsUpdate = true;
      geom.attributes.aSize.needsUpdate = true;
    }
  });

  return (
    <points ref={pointsRef}>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          count={MAX_PARTICLES}
          array={positions}
          itemSize={3}
        />
        <bufferAttribute
          attach="attributes-aLife"
          count={MAX_PARTICLES}
          array={lifes}
          itemSize={1}
        />
        <bufferAttribute
          attach="attributes-aSize"
          count={MAX_PARTICLES}
          array={sizes}
          itemSize={1}
        />
      </bufferGeometry>
      <shaderMaterial
        vertexShader={vertexShader}
        fragmentShader={fragmentShader}
        transparent
        blending={THREE.AdditiveBlending}
        depthWrite={false}
      />
    </points>
  );
}
