/* Center ambient glow — pure-CSS amber backlight, no icon */
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
      {/* Outer ambient glow ring */}
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
      {/* Inner ambient glow ring */}
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

      <style>{`
        @keyframes glowBreathe {
          0%, 100% { opacity: 0.85; transform: translate(-50%, -50%) scale(1); }
          50%       { opacity: 1;    transform: translate(-50%, -50%) scale(1.06); }
        }
      `}</style>
    </div>
  );
}
