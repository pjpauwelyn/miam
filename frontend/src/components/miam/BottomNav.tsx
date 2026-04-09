import { MessageCircle, Compass, Bookmark } from 'lucide-react';
import { useLocation } from 'wouter';
import { motion, AnimatePresence } from 'framer-motion';

const tabs = [
  { path: '/', label: 'Chat', icon: MessageCircle },
  { path: '/discover', label: 'Discover', icon: Compass },
  { path: '/library', label: 'Library', icon: Bookmark },
];

export function BottomNav() {
  const [location, navigate] = useLocation();
  const current = location === '' ? '/' : location;

  return (
    <nav
      className="flex items-center justify-around border-t relative"
      style={{
        height: 60,
        borderColor: '#2A2A2A',
        background: '#141414',
        paddingBottom: 'env(safe-area-inset-bottom, 0)',
      }}
      data-testid="bottom-nav"
    >
      {tabs.map((tab) => {
        const isActive = current === tab.path;
        const Icon = tab.icon;
        return (
          <button
            key={tab.path}
            onClick={() => navigate(tab.path)}
            className="flex flex-col items-center justify-center gap-0.5 flex-1 h-full relative"
            data-testid={`nav-${tab.label.toLowerCase()}`}
          >
            {/* Active glow dot behind icon */}
            <AnimatePresence>
              {isActive && (
                <motion.div
                  className="absolute rounded-full"
                  style={{
                    width: 36,
                    height: 36,
                    top: 6,
                    background: 'rgba(212, 168, 85, 0.08)',
                  }}
                  initial={{ scale: 0, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  exit={{ scale: 0, opacity: 0 }}
                  transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                />
              )}
            </AnimatePresence>

            <motion.div
              animate={{
                y: isActive ? -1 : 0,
                scale: isActive ? 1.05 : 1,
              }}
              transition={{ type: 'spring', stiffness: 500, damping: 30 }}
            >
              <Icon
                size={22}
                strokeWidth={isActive ? 2.2 : 1.6}
                style={{ color: isActive ? '#D4A855' : '#706D65' }}
              />
            </motion.div>

            <AnimatePresence>
              {isActive && (
                <motion.span
                  className="text-[10px] font-medium"
                  style={{ color: '#D4A855' }}
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: 4 }}
                  transition={{ duration: 0.2, delay: 0.05 }}
                >
                  {tab.label}
                </motion.span>
              )}
            </AnimatePresence>
          </button>
        );
      })}
    </nav>
  );
}
