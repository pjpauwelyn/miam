import { motion } from 'framer-motion';
import cookIconUrl from '@assets/cook-icon.png';
import dinerIconUrl from '@assets/diner-icon.png';

interface ModeToggleProps {
  mode: 'eat-in' | 'eat-out';
  onToggle: () => void;
}

export function ModeToggle({ mode, onToggle }: ModeToggleProps) {
  const isEatIn = mode === 'eat-in';

  return (
    <div className="flex justify-center py-3" data-testid="mode-toggle">
      <motion.button
        onClick={onToggle}
        className="relative flex items-center rounded-full overflow-hidden"
        style={{
          width: 260,
          height: 56,
          background: '#1E1E1E',
          border: '1px solid #333333',
        }}
        whileTap={{ scale: 0.97 }}
        transition={{ type: 'spring', stiffness: 500, damping: 30 }}
      >
        {/* Sliding amber pill with glow */}
        <motion.div
          className="absolute top-[2px] rounded-full"
          style={{
            width: 126,
            height: 50,
            background: 'rgba(212, 168, 85, 0.15)',
            border: '1px solid rgba(212, 168, 85, 0.35)',
            boxShadow: '0 0 16px rgba(212, 168, 85, 0.12), inset 0 0 8px rgba(212, 168, 85, 0.06)',
          }}
          animate={{ left: isEatIn ? 2 : 130 }}
          transition={{ type: 'spring', stiffness: 400, damping: 28 }}
        />

        {/* eat in: label then cook icon */}
        <div className="relative z-10 flex items-center justify-center gap-1.5 flex-1">
          <motion.span
            className="text-sm font-medium"
            animate={{
              color: isEatIn ? '#D4A855' : '#807D75',
              opacity: isEatIn ? 1 : 0.6,
            }}
            transition={{ duration: 0.25 }}
          >
            eat in
          </motion.span>
          <motion.img
            src={cookIconUrl}
            alt="Cook"
            style={{ width: 36, height: 36 }}
            animate={{
              opacity: isEatIn ? 1 : 0.5,
              scale: isEatIn ? 1 : 0.88,
              filter: isEatIn
                ? 'grayscale(0%) brightness(1)'
                : 'grayscale(60%) brightness(0.7)',
            }}
            transition={{ duration: 0.3, ease: [0.25, 0.1, 0.25, 1] }}
          />
        </div>

        {/* eat out: diner icon then label */}
        <div className="relative z-10 flex items-center justify-center gap-1.5 flex-1">
          <motion.img
            src={dinerIconUrl}
            alt="Dine"
            style={{ width: 36, height: 36 }}
            animate={{
              opacity: !isEatIn ? 1 : 0.5,
              scale: !isEatIn ? 1 : 0.88,
              filter: !isEatIn
                ? 'grayscale(0%) brightness(1)'
                : 'grayscale(60%) brightness(0.7)',
            }}
            transition={{ duration: 0.3, ease: [0.25, 0.1, 0.25, 1] }}
          />
          <motion.span
            className="text-sm font-medium"
            animate={{
              color: !isEatIn ? '#D4A855' : '#807D75',
              opacity: !isEatIn ? 1 : 0.6,
            }}
            transition={{ duration: 0.25 }}
          >
            eat out
          </motion.span>
        </div>
      </motion.button>
    </div>
  );
}
