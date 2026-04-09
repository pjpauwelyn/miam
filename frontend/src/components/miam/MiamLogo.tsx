import logoIconUrl from '@assets/miam-logo-icon.png';

export function MiamLogo({ size = 32 }: { size?: number }) {
  return (
    <img
      src={logoIconUrl}
      alt="miam logo"
      style={{
        width: size,
        height: size,
        objectFit: 'contain',
      }}
    />
  );
}

export function MiamWordmark() {
  return (
    <span className="text-lg font-semibold tracking-tight" style={{ color: '#D4A855' }}>
      miam
    </span>
  );
}
