import { useState, useEffect, createContext, useContext, lazy, Suspense } from 'react';
import { Switch, Route, Router, useLocation } from 'wouter';
import { useHashLocation } from 'wouter/use-hash-location';
import { queryClient } from './lib/queryClient';
import { QueryClientProvider } from '@tanstack/react-query';
import { TooltipProvider } from '@/components/ui/tooltip';
import { TopBar } from './components/miam/TopBar';
import { BottomNav } from './components/miam/BottomNav';
import { ProfileSheet } from './components/miam/ProfileSheet';
import { RecipeDetail } from './components/miam/RecipeDetail';
// Keep direct imports for critical path
import ChatPage from './pages/ChatPage';
import LoginPage from './pages/LoginPage';
// Lazy-load the rest
const DiscoverPage = lazy(() => import('./pages/DiscoverPage'));
const LibraryPage = lazy(() => import('./pages/LibraryPage'));
const OnboardingPage = lazy(() => import('./pages/OnboardingPage'));
const CreateRecipePage = lazy(() => import('./pages/CreateRecipePage'));
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { fetchUserProfile } from './lib/api';
import { AnimatePresence, motion } from 'framer-motion';
import { Loader2 } from 'lucide-react';
import type { UiRecipe } from './lib/api';

interface RecipeDetailContextType {
  openRecipe: (recipe: UiRecipe) => void;
}

export const RecipeDetailContext = createContext<RecipeDetailContextType>({
  openRecipe: () => {},
});

export const useRecipeDetail = () => useContext(RecipeDetailContext);

/* Page transition wrapper */
function PageTransition({ children, routeKey }: { children: React.ReactNode; routeKey: string }) {
  return (
    <motion.div
      key={routeKey}
      className="flex-1 flex flex-col overflow-hidden"
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -6 }}
      transition={{ duration: 0.25, ease: [0.25, 0.1, 0.25, 1] }}
    >
      {children}
    </motion.div>
  );
}

function AppShell() {
  const { user, loading: authLoading, signOut } = useAuth();
  const [profileOpen, setProfileOpen] = useState(false);
  const [selectedRecipe, setSelectedRecipe] = useState<UiRecipe | null>(null);
  const [location, navigate] = useLocation();
  const [hasProfile, setHasProfile] = useState<boolean | null>(null);
  const [checkingProfile, setCheckingProfile] = useState(false);
  const [userInitials, setUserInitials] = useState<string>('U');

  // Check if user has completed onboarding
  useEffect(() => {
    if (!user) {
      setHasProfile(null);
      return;
    }
    setCheckingProfile(true);
    fetchUserProfile(user.id)
      .then((profile) => {
        setHasProfile(profile !== null && profile.profile_status === 'complete');
        if (profile?.display_name) {
          const parts = profile.display_name.trim().split(/\s+/);
          setUserInitials(parts.length >= 2
            ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
            : parts[0][0].toUpperCase());
        } else if (user.email) {
          setUserInitials(user.email[0].toUpperCase());
        }
      })
      .catch(() => setHasProfile(false))
      .finally(() => setCheckingProfile(false));
  }, [user]);

  // Loading state
  if (authLoading) {
    return (
      <div className="phone-frame flex flex-col items-center justify-center" style={{ background: '#0A0A0A' }}>
        <Loader2 size={24} className="animate-spin" style={{ color: '#C8956C' }} />
      </div>
    );
  }

  // Not logged in → login page
  if (!user) {
    return <LoginPage />;
  }

  // Checking profile...
  if (checkingProfile || hasProfile === null) {
    return (
      <div className="phone-frame flex flex-col items-center justify-center" style={{ background: '#0A0A0A' }}>
        <Loader2 size={24} className="animate-spin" style={{ color: '#C8956C' }} />
        <p className="text-xs mt-3" style={{ color: '#706D65' }}>Loading your profile...</p>
      </div>
    );
  }

  // No profile → onboarding
  if (!hasProfile && !location.startsWith('/onboarding')) {
    // Auto-redirect to onboarding
    return (
      <div className="phone-frame flex flex-col overflow-hidden">
        <Suspense fallback={<div className="flex items-center justify-center h-full"><Loader2 className="animate-spin" style={{ color: '#D4A855' }} /></div>}>
          <OnboardingPage onComplete={() => setHasProfile(true)} />
        </Suspense>
      </div>
    );
  }

  // Onboarding page (accessed explicitly)
  if (location.startsWith('/onboarding')) {
    return (
      <div className="phone-frame flex flex-col overflow-hidden">
        <Suspense fallback={<div className="flex items-center justify-center h-full"><Loader2 className="animate-spin" style={{ color: '#D4A855' }} /></div>}>
          <OnboardingPage onComplete={() => { setHasProfile(true); navigate('/'); }} />
        </Suspense>
      </div>
    );
  }

  return (
    <RecipeDetailContext.Provider value={{ openRecipe: setSelectedRecipe }}>
      <div className="phone-frame flex flex-col overflow-hidden relative" style={{ paddingTop: 'env(safe-area-inset-top, 0)' }}>
        {/* Top bar with fade-in */}
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.05 }}
        >
          <TopBar onAvatarClick={() => setProfileOpen(true)} userInitials={userInitials} />
        </motion.div>

        {/* Page content with route transitions */}
        <Suspense fallback={<div className="flex items-center justify-center h-full"><Loader2 className="animate-spin" style={{ color: '#D4A855' }} /></div>}>
        <AnimatePresence mode="wait">
          <Switch>
            <Route path="/">
              <PageTransition routeKey="chat">
                <ChatPage />
              </PageTransition>
            </Route>
            <Route path="/discover">
              <PageTransition routeKey="discover">
                <DiscoverPage />
              </PageTransition>
            </Route>
            <Route path="/library">
              <PageTransition routeKey="library">
                <LibraryPage />
              </PageTransition>
            </Route>
            <Route path="/create">
              <PageTransition routeKey="create">
                <CreateRecipePage />
              </PageTransition>
            </Route>
            <Route>
              <PageTransition routeKey="chat-fallback">
                <ChatPage />
              </PageTransition>
            </Route>
          </Switch>
        </AnimatePresence>
        </Suspense>

        <BottomNav />
        <ProfileSheet
          isOpen={profileOpen}
          onClose={() => setProfileOpen(false)}
          onSignOut={signOut}
        />

        {/* Recipe detail overlay */}
        <AnimatePresence>
          {selectedRecipe && (
            <RecipeDetail recipe={selectedRecipe} onClose={() => setSelectedRecipe(null)} />
          )}
        </AnimatePresence>
      </div>
    </RecipeDetailContext.Provider>
  );
}

function App() {
  useEffect(() => {
    document.documentElement.classList.add('dark');
  }, []);

  return (
    <AuthProvider>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <Router hook={useHashLocation}>
            <AppShell />
          </Router>
        </TooltipProvider>
      </QueryClientProvider>
    </AuthProvider>
  );
}

export default App;
