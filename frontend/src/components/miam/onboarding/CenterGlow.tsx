import { useRef, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import * as THREE from 'three';
import logoUrl from '@assets/miam-logo-icon.png';

/* Center: miam logo with amber backlight glow */
export default function CenterGlow() {
  const glowRef = useRef<THREE.Mesh>(null!);
  const ringRef = useRef<THREE.Mesh>(null!);

  useFrame((state) => {
    const t = state.clock.elapsedTime;
    // Gentle breathing on the glow
    if (glowRef.current) {
      const scale = 1.0 + Math.sin(t * 0.8) * 0.04;
      glowRef.current.scale.setScalar(scale);
    }
    // Slowly rotate the accent ring
    if (ringRef.current) {
      ringRef.current.rotation.z = t * 0.12;
    }
  });

  // Amber backlight glow shader — light shining from behind the logo
  const glowMaterial = useMemo(() => {
    return new THREE.ShaderMaterial({
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      uniforms: {
        uTime: { value: 0 },
      },
      vertexShader: `
        varying vec2 vUv;
        void main() {
          vUv = uv;
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }
      `,
      fragmentShader: `
        varying vec2 vUv;
        uniform float uTime;
        void main() {
          vec2 center = vec2(0.5);
          float dist = distance(vUv, center) * 2.0;
          
          vec3 amber = vec3(0.831, 0.659, 0.333);
          
          // Soft radial glow — brighter at the edge of where the logo sits, fading outward
          float innerGlow = smoothstep(0.5, 0.3, dist) * 0.08; // very faint inner fill
          float ringGlow = smoothstep(0.25, 0.45, dist) * smoothstep(0.85, 0.5, dist); // the backlight ring
          float outerFade = smoothstep(1.0, 0.7, dist) * 0.03; // faint outer haze
          
          float pulse = 1.0 + sin(uTime * 0.8) * 0.15;
          float alpha = (ringGlow * 0.12 + innerGlow + outerFade) * pulse;
          
          gl_FragColor = vec4(amber, alpha);
        }
      `,
    });
  }, []);

  useFrame((state) => {
    glowMaterial.uniforms.uTime.value = state.clock.elapsedTime;
  });

  return (
    <group>
      {/* Amber backlight glow disk — sits behind the logo */}
      <mesh ref={glowRef} position={[0, 0, -0.05]}>
        <planeGeometry args={[1.2, 1.2]} />
        <primitive object={glowMaterial} attach="material" />
      </mesh>

      {/* Very faint accent ring */}
      <mesh ref={ringRef} rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[0.22, 0.006, 16, 64]} />
        <meshBasicMaterial
          color="#D4A855"
          transparent
          opacity={0.08}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
        />
      </mesh>

      {/* miam logo as center element */}
      <Html center style={{ pointerEvents: 'none', userSelect: 'none' }}>
        <div
          style={{
            width: 56,
            height: 56,
            borderRadius: '50%',
            background: 'rgba(14, 14, 14, 0.9)',
            border: '1.5px solid rgba(212, 168, 85, 0.25)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 0 24px rgba(212, 168, 85, 0.15), 0 0 48px rgba(212, 168, 85, 0.06)',
          }}
        >
          <img
            src={logoUrl}
            alt="miam"
            style={{ width: 38, height: 38, objectFit: 'contain' }}
            draggable={false}
          />
        </div>
      </Html>
    </group>
  );
}
