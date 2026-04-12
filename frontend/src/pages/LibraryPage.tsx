import { useState, useEffect } from 'react';
import { useLocation } from 'wouter';
import { Bookmark, Clock, ChefHat, Plus, Sparkles, PenLine, Loader2 } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useRecipeDetail } from '../App';
import {
  fetchSavedRecipes,
  fetchSessionHistory,
  recipeToUiFormat,
  logActivity,
  getCurrentUserId,
} from '../lib/api';
import type { UiRecipe, SessionSummary } from '../lib/api';

type Tab = 'saved' | 'my-recipes' | 'history';

function RecipeListCard({ recipe, index, onClick }: { recipe: UiRecipe; index: number; onClick: () => void }) {
  return (
    <motion.button
      onClick={onClick}
      className="w-full text-left rounded-xl p-3"
      style={{ background: '#1E1E1E', border: '1px solid #2A2A2A' }}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.06, duration: 0.3, ease: [0.25, 0.1, 0.25, 1] }}
      whileTap={{ scale: 0.98 }}
      data-testid={`library-recipe-${recipe.id}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <h4 className="text-[13px] font-medium leading-tight" style={{ color: '#F0EDE8' }}>
            {recipe.title}
          </h4>
          <div className="flex flex-wrap gap-1 mt-1.5">
            {recipe.cuisine.map((c) => (
              <span key={c} className="text-[10px] font-medium uppercase px-1.5 py-0.5 rounded" style={{ background: 'rgba(139,58,74,0.2)', color: '#C45A70' }}>
                {c}
              </span>
            ))}
            {recipe.dietary.slice(0, 2).map((d) => (
              <span key={d} className="text-[10px] font-medium uppercase px-1.5 py-0.5 rounded" style={{ background: 'rgba(74,139,92,0.2)', color: '#62AD76' }}>
                {d}
              </span>
            ))}
          </div>
          <div className="flex items-center gap-3 mt-2">
            <div className="flex items-center gap-1">
              <Clock size={11} style={{ color: '#A5A29A' }} />
              <span className="text-[11px]" style={{ color: '#A5A29A' }}>{recipe.time} min</span>
            </div>
            {recipe.sourceType && (
              <div className="flex items-center gap-1">
                {recipe.sourceType === 'curated-verified'
                  ? <Sparkles size={11} style={{ color: '#D4A855' }} />
                  : <PenLine size={11} style={{ color: '#A5A29A' }} />
                }
                <span className="text-[10px]" style={{ color: '#A5A29A' }}>
                  {recipe.sourceType === 'curated-verified' ? 'Curated' : recipe.sourceType}
                </span>
              </div>
            )}
          </div>
        </div>
      </div>
    </motion.button>
  );
}

export default function LibraryPage() {
  const [tab, setTab] = useState<Tab>('saved');
  const [, navigate] = useLocation();
  const { openRecipe } = useRecipeDetail();

  // Data state
  const [savedRecipes, setSavedRecipes] = useState<UiRecipe[]>([]);
  const [sessionHistory, setSessionHistory] = useState<SessionSummary[]>([]);
  const [loadingSaved, setLoadingSaved] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [savedLoaded, setSavedLoaded] = useState(false);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [savedError, setSavedError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);

  // Load saved recipes from user_saved_recipes join
  useEffect(() => {
    if (tab === 'saved' && !savedLoaded) {
      setLoadingSaved(true);
      getCurrentUserId().then(uid => fetchSavedRecipes(uid))
        .then((data) => {
          setSavedRecipes(data.map(recipeToUiFormat));
          setSavedLoaded(true);
        })
        .catch(() => setSavedError('Couldn\u2019t load saved recipes. Try again later.'))
        .finally(() => setLoadingSaved(false));
    }
  }, [tab, savedLoaded]);

  // Load session history from sessions table (correct started_at column)
  useEffect(() => {
    if (tab === 'history' && !historyLoaded) {
      setLoadingHistory(true);
      getCurrentUserId().then(uid => fetchSessionHistory(uid))
        .then((data) => {
          setSessionHistory(data);
          setHistoryLoaded(true);
        })
        .catch(() => setHistoryError('Couldn\u2019t load history. Try again later.'))
        .finally(() => setLoadingHistory(false));
    }
  }, [tab, historyLoaded]);

  const tabs: { key: Tab; label: string }[] = [
    { key: 'saved', label: 'Saved' },
    { key: 'my-recipes', label: 'My Recipes' },
    { key: 'history', label: 'History' },
  ];

  return (
    <div className="flex-1 flex flex-col overflow-hidden relative">
      <motion.div
        className="px-5 pt-2 pb-3"
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
      >
        <h1 className="text-xl font-semibold" style={{ color: '#F0EDE8' }}>Library</h1>
      </motion.div>

      {/* Tab bar */}
      <div className="flex px-5 gap-1 border-b relative" style={{ borderColor: '#2A2A2A' }}>
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className="pb-2.5 px-3 text-sm font-medium relative transition-colors"
            style={{ color: tab === t.key ? '#D4A855' : '#706D65' }}
            data-testid={`library-tab-${t.key}`}
          >
            {t.label}
            {tab === t.key && (
              <motion.div
                className="absolute bottom-0 left-0 right-0 h-[2px] rounded-full"
                style={{ background: '#D4A855' }}
                layoutId="library-tab-indicator"
                transition={{ type: 'spring', stiffness: 400, damping: 30 }}
              />
            )}
          </button>
        ))}
      </div>

      {/* Content */}
      <AnimatePresence mode="wait">
        <motion.div
          key={tab}
          className="flex-1 overflow-y-auto hide-scrollbar"
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -10 }}
          transition={{ duration: 0.25, ease: [0.25, 0.1, 0.25, 1] }}
        >
          {tab === 'saved' && (
            <div className="px-5 py-4 space-y-3">
              {savedError ? (
                <div className="flex items-center justify-center min-h-[300px]">
                  <p className="text-sm" style={{ color: '#A5A29A' }}>{savedError}</p>
                </div>
              ) : loadingSaved ? (
                <div className="flex items-center justify-center min-h-[300px]">
                  <Loader2 size={20} className="animate-spin" style={{ color: '#D4A855' }} />
                  <span className="ml-2 text-sm" style={{ color: '#A5A29A' }}>Loading saved recipes...</span>
                </div>
              ) : savedRecipes.length > 0 ? (
                savedRecipes.map((recipe, i) => (
                  <RecipeListCard
                    key={recipe.id}
                    recipe={recipe}
                    index={i}
                    onClick={() => openRecipe(recipe)}
                  />
                ))
              ) : (
                <div className="flex items-center justify-center min-h-[400px]">
                  <div className="text-center">
                    <motion.div
                      className="w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-3"
                      style={{ background: '#1E1E1E' }}
                      initial={{ scale: 0.8 }}
                      animate={{ scale: 1 }}
                      transition={{ type: 'spring', stiffness: 400, damping: 25, delay: 0.1 }}
                    >
                      <Bookmark size={24} style={{ color: '#706D65' }} />
                    </motion.div>
                    <p className="text-sm font-medium" style={{ color: '#A5A29A' }}>Nothing saved yet</p>
                    <p className="text-xs mt-1" style={{ color: '#706D65' }}>
                      Bookmark recipes to find them here
                    </p>
                  </div>
                </div>
              )}
            </div>
          )}

          {tab === 'my-recipes' && (
            <div className="flex items-center justify-center px-5 min-h-[300px]">
              <div className="text-center">
                <motion.div
                  className="w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-3"
                  style={{ background: '#1E1E1E' }}
                  initial={{ scale: 0.8 }}
                  animate={{ scale: 1 }}
                  transition={{ type: 'spring', stiffness: 400, damping: 25, delay: 0.1 }}
                >
                  <ChefHat size={24} style={{ color: '#706D65' }} />
                </motion.div>
                <p className="text-sm font-medium" style={{ color: '#A5A29A' }}>No custom recipes yet</p>
                <p className="text-xs mt-1" style={{ color: '#706D65' }}>
                  Create your first recipe with the + button below
                </p>
              </div>
            </div>
          )}

          {tab === 'history' && (
            <div className="px-5 py-4 space-y-3">
              {historyError ? (
                <div className="flex items-center justify-center min-h-[300px]">
                  <p className="text-sm" style={{ color: '#A5A29A' }}>{historyError}</p>
                </div>
              ) : loadingHistory ? (
                <div className="flex items-center justify-center min-h-[300px]">
                  <Loader2 size={20} className="animate-spin" style={{ color: '#D4A855' }} />
                  <span className="ml-2 text-sm" style={{ color: '#A5A29A' }}>Loading history...</span>
                </div>
              ) : sessionHistory.length > 0 ? (
                sessionHistory.map((session, i) => {
                  const date = new Date(session.started_at);
                  return (
                    <motion.div
                      key={session.session_id}
                      className="rounded-xl p-3"
                      style={{ background: '#1E1E1E', border: '1px solid #2A2A2A' }}
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: i * 0.06, duration: 0.3 }}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <Clock size={12} style={{ color: '#D4A855' }} />
                        <span className="text-[11px] font-medium" style={{ color: '#A5A29A' }}>
                          {date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })} at {date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}
                        </span>
                        {session.mode && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(212,168,85,0.1)', color: '#D4A855' }}>
                            {session.mode}
                          </span>
                        )}
                      </div>
                      <p className="text-sm truncate" style={{ color: '#F0EDE8' }}>
                        {session.first_user_message || 'Conversation'}
                      </p>
                      <p className="text-[10px] mt-1" style={{ color: '#706D65' }}>
                        {session.query_count} {session.query_count === 1 ? 'query' : 'queries'}
                      </p>
                    </motion.div>
                  );
                })
              ) : (
                <div className="flex items-center justify-center min-h-[400px]">
                  <div className="text-center">
                    <motion.div
                      className="w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-3"
                      style={{ background: '#1E1E1E' }}
                      initial={{ scale: 0.8 }}
                      animate={{ scale: 1 }}
                      transition={{ type: 'spring', stiffness: 400, damping: 25, delay: 0.1 }}
                    >
                      <Clock size={24} style={{ color: '#706D65' }} />
                    </motion.div>
                    <p className="text-sm font-medium" style={{ color: '#A5A29A' }}>No history yet</p>
                    <p className="text-xs mt-1" style={{ color: '#706D65' }}>
                      Your past conversations and discoveries will appear here
                    </p>
                  </div>
                </div>
              )}
            </div>
          )}
        </motion.div>
      </AnimatePresence>

      {/* Floating create button — visible on My Recipes tab */}
      <AnimatePresence>
        {tab === 'my-recipes' && (
          <motion.button
            onClick={() => navigate('/create')}
            className="absolute bottom-4 right-5 w-12 h-12 rounded-full flex items-center justify-center"
            style={{
              background: '#D4A855',
              boxShadow: '0 4px 20px rgba(212,168,85,0.3)',
            }}
            initial={{ scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0, opacity: 0 }}
            transition={{ type: 'spring', stiffness: 400, damping: 22 }}
            whileTap={{ scale: 0.9 }}
            whileHover={{ boxShadow: '0 4px 28px rgba(212,168,85,0.45)' }}
            data-testid="create-recipe-btn"
          >
            <Plus size={22} style={{ color: '#141414' }} />
          </motion.button>
        )}
      </AnimatePresence>
    </div>
  );
}
