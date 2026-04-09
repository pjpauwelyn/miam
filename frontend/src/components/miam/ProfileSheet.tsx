import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useLocation } from 'wouter';
import { X, User, Settings, Info, Sparkles, Loader2, LogOut } from 'lucide-react';
import { fetchUserProfile, getCurrentUserId } from '../../lib/api';
import type { UserProfile } from '../../lib/api';

interface ProfileSheetProps {
  isOpen: boolean;
  onClose: () => void;
  onSignOut?: () => void;
}

export function ProfileSheet({ isOpen, onClose, onSignOut }: ProfileSheetProps) {
  const [, navigate] = useLocation();
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (isOpen && !profile) {
      setLoading(true);
      fetchUserProfile(getCurrentUserId())
        .then((p) => setProfile(p))
        .catch(() => setProfile(null))
        .finally(() => setLoading(false));
    }
  }, [isOpen]);

  const items = [
    { icon: User, label: 'Profile' },
    { icon: Settings, label: 'Settings' },
    { icon: Info, label: 'About' },
  ];

  const initials = profile?.display_name
    ? profile.display_name.slice(0, 2).toUpperCase()
    : 'LP';
  const displayName = profile?.display_name || 'User';
  const subtitle = profile?.dietary_spectrum || 'Food Explorer';

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          <motion.div
            className="absolute inset-0 z-40"
            style={{ background: 'rgba(0,0,0,0.5)' }}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.div
            className="absolute bottom-0 left-0 right-0 z-50 rounded-t-2xl px-5 pt-4 pb-8"
            style={{ background: '#1E1E1E', border: '1px solid #2A2A2A', borderBottom: 'none' }}
            initial={{ y: '100%' }}
            animate={{ y: 0 }}
            exit={{ y: '100%' }}
            transition={{ type: 'spring', damping: 28, stiffness: 300 }}
            data-testid="profile-sheet"
          >
            {loading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 size={20} className="animate-spin" style={{ color: '#D4A855' }} />
              </div>
            ) : (
              <>
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div
                      className="w-10 h-10 rounded-full flex items-center justify-center text-sm font-semibold"
                      style={{ background: '#262626', color: '#D4A855' }}
                    >
                      {initials}
                    </div>
                    <div>
                      <div className="text-sm font-medium" style={{ color: '#F0EDE8' }}>{displayName}</div>
                      <div className="text-xs" style={{ color: '#706D65' }}>{subtitle}</div>
                    </div>
                  </div>
                  <button onClick={onClose}>
                    <X size={20} style={{ color: '#706D65' }} />
                  </button>
                </div>

                {/* Profile summary */}
                {profile?.summary && (
                  <div className="mb-3 p-3 rounded-xl" style={{ background: '#262626' }}>
                    <p className="text-xs leading-relaxed" style={{ color: '#A5A29A' }}>
                      {profile.summary}
                    </p>
                  </div>
                )}

                {/* Dietary restrictions */}
                {profile && profile.restrictions.length > 0 && (
                  <div className="mb-3">
                    <p className="text-[10px] font-medium uppercase mb-1" style={{ color: '#A5A29A' }}>Restrictions</p>
                    <div className="flex flex-wrap gap-1">
                      {profile.restrictions.map((r) => (
                        <span key={r} className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(196,90,112,0.12)', color: '#C45A70' }}>
                          {r}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Cuisine affinities */}
                {profile && profile.cuisine_affinities.length > 0 && (
                  <div className="mb-3">
                    <p className="text-[10px] font-medium uppercase mb-1" style={{ color: '#A5A29A' }}>Favourite cuisines</p>
                    <div className="flex flex-wrap gap-1">
                      {profile.cuisine_affinities.map((a) => (
                        <span key={a.cuisine} className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(212,168,85,0.1)', color: '#D4A855' }}>
                          {a.cuisine} ({a.level})
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Cooking skill & location */}
                {profile && (profile.cooking_skill || profile.location_city) && (
                  <div className="flex gap-3 mb-3">
                    {profile.cooking_skill && (
                      <div className="text-[10px] px-2 py-1 rounded" style={{ background: '#262626', color: '#A5A29A' }}>
                        Skill: {profile.cooking_skill}
                      </div>
                    )}
                    {profile.location_city && (
                      <div className="text-[10px] px-2 py-1 rounded" style={{ background: '#262626', color: '#A5A29A' }}>
                        📍 {profile.location_city}
                      </div>
                    )}
                  </div>
                )}

                {/* Onboarding entry */}
                <motion.button
                  onClick={() => { onClose(); navigate('/onboarding'); }}
                  className="flex items-center gap-3 w-full px-3 py-3 rounded-xl mb-3"
                  style={{ background: 'rgba(212,168,85,0.08)', border: '1px solid rgba(212,168,85,0.2)' }}
                  whileTap={{ scale: 0.98 }}
                  data-testid="profile-onboarding"
                >
                  <Sparkles size={18} style={{ color: '#D4A855' }} />
                  <div className="text-left">
                    <span className="text-sm font-medium block" style={{ color: '#D4A855' }}>Taste interview</span>
                    <span className="text-[11px]" style={{ color: '#A5A29A' }}>Build your flavour constellation</span>
                  </div>
                </motion.button>

                <div className="space-y-1">
                  {items.map((item) => (
                    <button
                      key={item.label}
                      className="flex items-center gap-3 w-full px-3 py-3 rounded-lg transition-colors"
                      style={{ color: '#F0EDE8' }}
                      data-testid={`profile-${item.label.toLowerCase()}`}
                    >
                      <item.icon size={18} style={{ color: '#A5A29A' }} />
                      <span className="text-sm">{item.label}</span>
                    </button>
                  ))}
                </div>

                {/* Sign out */}
                {onSignOut && (
                  <button
                    onClick={() => { onClose(); onSignOut(); }}
                    className="flex items-center gap-3 w-full px-3 py-3 rounded-lg transition-colors mt-4"
                    style={{ color: '#8B4A5E', borderTop: '1px solid #1E1E1E', paddingTop: '16px' }}
                  >
                    <LogOut size={18} />
                    <span className="text-sm">Sign out</span>
                  </button>
                )}
              </>
            )}
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
