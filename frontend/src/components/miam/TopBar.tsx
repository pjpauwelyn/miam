import { motion } from 'framer-motion';
import { MiamLogo, MiamWordmark } from './MiamLogo';

interface TopBarProps {
  onAvatarClick: () => void;
}

export function TopBar({ onAvatarClick }: TopBarProps) {
  return (
    <div className="flex items-center justify-between px-5 py-3" data-testid="top-bar">
      <div className="flex items-center gap-2">
        <MiamLogo size={28} />
        <MiamWordmark />
      </div>
      <motion.button
        onClick={onAvatarClick}
        className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold"
        style={{ background: '#262626', color: '#D4A855' }}
        whileTap={{ scale: 0.9 }}
        whileHover={{ boxShadow: '0 0 0 2px rgba(212, 168, 85, 0.2)' }}
        transition={{ type: 'spring', stiffness: 500, damping: 25 }}
        data-testid="avatar-button"
      >
        LP
      </motion.button>
    </div>
  );
}
