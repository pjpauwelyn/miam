import { useState, useRef, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Send, Loader2 } from 'lucide-react';
import { ModeToggle } from '../components/miam/ModeToggle';
import { RecipeCard } from '../components/miam/RecipeCard';
import { ComingSoonToast } from '../components/miam/ComingSoon';
import { useRecipeDetail } from '../App';
import { queryPipeline, fetchRecipeById, recipeToUiFormat, getCurrentUserId } from '../lib/api';
import type { PipelineResult, UiRecipe } from '../lib/api';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  recipes?: (UiRecipe & { matchTier?: string; nutritionSummary?: string; keyTechnique?: string; missingIngredients?: string[]; warnings?: string[] })[];
  pipelineStatus?: string;
  isLoading?: boolean;
}

const suggestionChips = [
  'Quick vegetarian dinner',
  'Something Japanese',
  'Traditional Dutch comfort food',
  'Gluten-free dessert',
  'I have aubergine and feta',
  'Under 20 min',
];

export default function ChatPage() {
  const [mode, setMode] = useState<'eat-in' | 'eat-out'>('eat-in');
  const [showComingSoon, setShowComingSoon] = useState(false);
  const [inputValue, setInputValue] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [isQuerying, setIsQuerying] = useState(false);
  const { openRecipe } = useRecipeDetail();
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const sendQuery = useCallback(async (query: string) => {
    if (!query.trim() || isQuerying) return;
    setIsQuerying(true);

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: query,
    };
    const loadingMsg: ChatMessage = {
      id: `loading-${Date.now()}`,
      role: 'assistant',
      content: '',
      isLoading: true,
    };
    setMessages(prev => [...prev, userMsg, loadingMsg]);
    setInputValue('');

    try {
      const uid = await getCurrentUserId();
      const pipelineResp = await queryPipeline(query, uid, sessionId);
      setSessionId(pipelineResp.session_id);

      // Fetch full recipe documents for results
      const recipePromises = pipelineResp.response.results.map(async (result: PipelineResult) => {
        try {
          const fullRecipe = await fetchRecipeById(result.recipe_id);
          if (fullRecipe) {
            return {
              ...recipeToUiFormat(fullRecipe),
              matchScore: Math.round(result.match_score * 100),
              matchTier: result.match_tier,
              nutritionSummary: result.nutrition_summary,
              keyTechnique: result.key_technique,
              missingIngredients: result.missing_ingredients,
              warnings: result.warnings,
            };
          }
        } catch { /* skip failed fetches */ }
        // Fallback: build a minimal recipe from pipeline result
        return {
          id: result.recipe_id,
          title: result.title,
          cuisine: [],
          dietary: [],
          time: result.time_total_min || 0,
          difficulty: result.difficulty || 1,
          matchScore: Math.round(result.match_score * 100),
          description: '',
          servings: result.serves || 2,
          ingredients: [],
          steps: [],
          nutrition: { calories: 0, protein: 0, carbs: 0, fat: 0, fibre: 0, saturatedFat: 0, sugar: 0, salt: 0 },
          flavourTags: [],
          textureTags: [],
          dietaryFlags: {},
          tips: [],
          matchTier: result.match_tier,
          nutritionSummary: result.nutrition_summary,
          keyTechnique: result.key_technique,
          missingIngredients: result.missing_ingredients,
          warnings: result.warnings,
        };
      });

      const recipes = await Promise.all(recipePromises);

      const assistantMsg: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: pipelineResp.response.generated_text,
        recipes: recipes.filter(Boolean) as any[],
        pipelineStatus: pipelineResp.debug.pipeline_status,
      };

      setMessages(prev => [...prev.filter(m => !m.isLoading), assistantMsg]);
    } catch (err: any) {
      const errorMsg: ChatMessage = {
        id: `error-${Date.now()}`,
        role: 'assistant',
        content: `Something went wrong: ${err.message || 'Pipeline unavailable'}. The backend may not be running — try again in a moment.`,
        pipelineStatus: 'error',
      };
      setMessages(prev => [...prev.filter(m => !m.isLoading), errorMsg]);
    } finally {
      setIsQuerying(false);
    }
  }, [isQuerying, sessionId]);

  const handleSend = () => sendQuery(inputValue);
  const handleChipClick = (chip: string) => sendQuery(chip);
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex flex-col h-full relative">
      {/* Mode tint background */}
      <motion.div
        className="absolute inset-0 pointer-events-none z-0"
        animate={{
          background: mode === 'eat-in'
            ? 'linear-gradient(180deg, #1A2A20 0%, #141414 25%)'
            : 'linear-gradient(180deg, #1A2030 0%, #141414 25%)',
        }}
        transition={{ duration: 0.5, ease: [0.25, 0.1, 0.25, 1] }}
      />

      <div className="relative z-10 flex flex-col h-full">
        <ModeToggle mode={mode} onToggle={() => {
          if (mode === 'eat-in') {
            setShowComingSoon(true);
          } else {
            setMode('eat-in');
          }
        }} />
        <ComingSoonToast
          show={showComingSoon}
          message="Eat out mode is coming soon — restaurants, reviews, and reservations"
          onDismiss={() => setShowComingSoon(false)}
        />

        {/* Chat messages */}
        <div className="flex-1 overflow-y-auto px-4 pb-2 hide-scrollbar">
          <div className="space-y-3">
            {/* Welcome message if empty */}
            {messages.length === 0 && (
              <motion.div
                className="flex justify-start"
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, ease: [0.25, 0.1, 0.25, 1] }}
              >
                <div
                  className="max-w-[85%] px-4 py-3 rounded-2xl rounded-bl-md text-sm"
                  style={{ background: '#1E1E1E', borderLeft: '2px solid rgba(212, 168, 85, 0.3)', color: '#D8D6D0' }}
                >
                  What are you in the mood for?
                </div>
              </motion.div>
            )}

            {messages.map((msg, msgIdx) => (
              <motion.div
                key={msg.id}
                className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                initial={{ opacity: 0, y: 16, scale: 0.97 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                transition={{
                  delay: 0.05,
                  duration: 0.4,
                  ease: [0.25, 0.1, 0.25, 1],
                }}
              >
                {msg.role === 'user' ? (
                  <div
                    className="max-w-[80%] px-4 py-2.5 rounded-2xl rounded-br-md text-sm"
                    style={{ background: '#262626', color: '#F0EDE8' }}
                  >
                    {msg.content}
                  </div>
                ) : msg.isLoading ? (
                  <div
                    className="max-w-[85%] px-4 py-3 rounded-2xl rounded-bl-md text-sm flex items-center gap-2"
                    style={{ background: '#1E1E1E', borderLeft: '2px solid rgba(212, 168, 85, 0.3)' }}
                  >
                    <Loader2 size={14} className="animate-spin" style={{ color: '#D4A855' }} />
                    <span style={{ color: '#A5A29A' }}>Searching recipes...</span>
                  </div>
                ) : (
                  <div
                    className="max-w-[85%] px-4 py-3 rounded-2xl rounded-bl-md text-sm space-y-2"
                    style={{
                      background: '#1E1E1E',
                      borderLeft: `2px solid ${msg.pipelineStatus === 'error' ? 'rgba(196, 90, 112, 0.3)' : 'rgba(212, 168, 85, 0.3)'}`,
                      color: '#F0EDE8',
                    }}
                  >
                    <p style={{ color: '#D8D6D0', whiteSpace: 'pre-wrap' }}>{msg.content}</p>
                    {msg.recipes?.map((recipe, rIdx) => (
                      <div key={recipe.id} className="space-y-1">
                        <RecipeCard
                          recipe={recipe}
                          compact
                          index={rIdx}
                          onClick={() => openRecipe(recipe)}
                        />
                        {/* Match tier badge */}
                        <div className="flex flex-wrap gap-1 px-1">
                          {recipe.matchTier && (
                            <span className="text-[9px] font-medium uppercase px-1.5 py-0.5 rounded" style={{
                              background: recipe.matchTier === 'full_match' ? 'rgba(98,173,118,0.2)' : recipe.matchTier === 'close_match' ? 'rgba(212,168,85,0.15)' : 'rgba(165,162,154,0.1)',
                              color: recipe.matchTier === 'full_match' ? '#62AD76' : recipe.matchTier === 'close_match' ? '#D4A855' : '#A5A29A',
                            }}>
                              {recipe.matchTier.replace('_', ' ')}
                            </span>
                          )}
                          {recipe.nutritionSummary && (
                            <span className="text-[9px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(165,162,154,0.08)', color: '#A5A29A' }}>
                              {recipe.nutritionSummary}
                            </span>
                          )}
                        </div>
                        {recipe.warnings && recipe.warnings.length > 0 && (
                          <div className="px-1">
                            {recipe.warnings.map((w, i) => (
                              <p key={i} className="text-[10px]" style={{ color: '#C45A70' }}>⚠ {w}</p>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </motion.div>
            ))}
            <div ref={chatEndRef} />
          </div>
        </div>

        {/* Suggestion chips — only before conversation starts */}
        {messages.length <= 1 && (
        <div className="px-4 py-2">
          <div className="flex gap-2 overflow-x-auto hide-scrollbar pb-1">
            {suggestionChips.map((chip, i) => (
              <motion.button
                key={chip}
                onClick={() => handleChipClick(chip)}
                disabled={isQuerying}
                className="flex-shrink-0 px-3 py-1.5 rounded-full text-xs font-medium"
                style={{
                  background: '#1E1E1E',
                  border: '1px solid #2A2A2A',
                  color: '#A5A29A',
                  opacity: isQuerying ? 0.5 : 1,
                }}
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.3 + i * 0.06, duration: 0.3, ease: [0.25, 0.1, 0.25, 1] }}
                whileTap={{ scale: 0.94, background: 'rgba(212, 168, 85, 0.1)' }}
              >
                {chip}
              </motion.button>
            ))}
          </div>
        </div>
        )}

        {/* Input bar */}
        <motion.div
          className="px-4 pb-2"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4, duration: 0.4, ease: [0.25, 0.1, 0.25, 1] }}
        >
          <div
            className="flex items-center gap-2 rounded-xl px-4 py-2"
            style={{ background: '#2A2A2A', border: '1px solid #333333' }}
          >
            <input
              type="text"
              placeholder="What are you craving?"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isQuerying}
              className="flex-1 bg-transparent text-sm outline-none placeholder-opacity-50"
              style={{ color: '#F0EDE8' }}
              data-testid="chat-input"
            />
            <motion.button
              onClick={handleSend}
              disabled={isQuerying || !inputValue.trim()}
              className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
              style={{ background: isQuerying ? '#555' : '#D4A855' }}
              whileTap={{ scale: 0.88 }}
              whileHover={{ boxShadow: '0 0 12px rgba(212, 168, 85, 0.3)' }}
              transition={{ type: 'spring', stiffness: 500, damping: 25 }}
              data-testid="send-button"
            >
              {isQuerying ? (
                <Loader2 size={14} className="animate-spin" style={{ color: '#141414' }} />
              ) : (
                <Send size={14} style={{ color: '#141414' }} />
              )}
            </motion.button>
          </div>
        </motion.div>
      </div>
    </div>
  );
}
