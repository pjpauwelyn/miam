import logoUrl from '@assets/miam-logo-icon.png';

/* Center logo with pure-CSS amber backlight glow — no Three.js */
export default function CenterGlow() {
  return (
    <div
      style={{
        position: 'absolute',
        top: '50%',
        left: '50%',
        transform: 'translate(-50%, -50%)',
        zIndex: 2,
        pointerEvents: 'none',
        userSelect: 'none',
      }}
    >
      {/* Outer ambient glow rings — pure CSS */}
      <div
        style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          width: 120,
          height: 120,
          borderRadius: '50%',
          transform: 'translate(-50%, -50%)',
          background:
            'radial-gradient(circle, rgba(212,168,85,0.10) 0%, rgba(212,168,85,0.04) 50%, transparent 70%)',
          animation: 'glowBreathe 3.2s ease-in-out infinite',
        }}
      />
      <div
        style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          width: 80,
          height: 80,
          borderRadius: '50%',
          transform: 'translate(-50%, -50%)',
          background:
            'radial-gradient(circle, rgba(212,168,85,0.08) 0%, transparent 65%)',
          animation: 'glowBreathe 3.2s ease-in-out infinite 0.4s',
        }}
      />

      {/* Logo circle */}
      <div
        style={{
          width: 56,
          height: 56,
          borderRadius: '50%',
          background: 'rgba(14, 14, 14, 0.92)',
          border: '1.5px solid rgba(212, 168, 85, 0.25)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          boxShadow:
            '0 0 24px rgba(212,168,85,0.15), 0 0 48px rgba(212,168,85,0.06)',
          position: 'relative',
          zIndex: 3,
          animation: 'glowBreathe 3.2s ease-in-out infinite 0.8s',
        }}
      >
        <img
          src={logoUrl}
          alt="miam"
          style={{ width: 38, height: 38, objectFit: 'contain' }}
          draggable={false}
        />
      </div>

      <style>{`
        @keyframes glowBreathe {
          0%, 100% { opacity: 0.85; transform: translate(-50%, -50%) scale(1); }
          50%       { opacity: 1;    transform: translate(-50%, -50%) scale(1.06); }
        }
      `}</style>
    </div>
  );
}
