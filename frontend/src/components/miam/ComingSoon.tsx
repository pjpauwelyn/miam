import { motion, AnimatePresence } from 'framer-motion';
import { Construction } from 'lucide-react';
import { useEffect } from 'react';

interface ComingSoonToastProps {
  show: boolean;
  message?: string;
  onDismiss: () => void;
}

export function ComingSoonToast({ show, message, onDismiss }: ComingSoonToastProps) {
  useEffect(() => {
    if (show) {
      const t = setTimeout(onDismiss, 2500);
      return () => clearTimeout(t);
    }
  }, [show, onDismiss]);

  return (
    <AnimatePresence>
      {show && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 20 }}
          transition={{ duration: 0.25 }}
          className="fixed bottom-24 left-1/2 -translate-x-1/2 z-[100] flex items-center gap-2 px-4 py-2.5 rounded-xl"
          style={{
            background: 'rgba(30, 26, 20, 0.95)',
            border: '1px solid rgba(200, 149, 108, 0.2)',
            backdropFilter: 'blur(12px)',
          }}
        >
          <Construction size={16} style={{ color: '#C8956C' }} />
          <span className="text-xs" style={{ color: '#D8D6D0' }}>
            {message || 'This feature is being built — check back soon'}
          </span>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
