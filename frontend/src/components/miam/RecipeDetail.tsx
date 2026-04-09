import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ChevronLeft, Clock, Users, Bookmark, Flame, Leaf,
  ChevronRight, Wine, Lightbulb, MapPin, Check,
} from 'lucide-react';
import {
  saveRecipe, unsaveRecipe, fetchSavedRecipeIds, getCurrentUserId,
} from '../../lib/api';
import type { UiRecipe } from '../../lib/api';

interface RecipeDetailProps {
  recipe: UiRecipe | null;
  onClose: () => void;
}

function DifficultyDots({ level }: { level: number }) {
  return (
    <div className="flex gap-1 items-center">
      {[1, 2, 3].map((i) => (
        <div
          key={i}
          className="w-2 h-2 rounded-full"
          style={{ background: i <= level ? '#D4A855' : '#333333' }}
        />
      ))}
    </div>
  );
}

function DietaryBadge({ label, positive }: { label: string; positive: boolean }) {
  return (
    <span
      className="text-[10px] font-medium uppercase px-2 py-0.5 rounded"
      style={{
        background: positive ? 'rgba(74,139,92,0.15)' : 'rgba(196,90,112,0.12)',
        color: positive ? '#62AD76' : '#C45A70',
      }}
    >
      {label}
    </span>
  );
}

type DetailTab = 'overview' | 'ingredients' | 'steps' | 'cooking';

export function RecipeDetail({ recipe, onClose }: RecipeDetailProps) {
  const [tab, setTab] = useState<DetailTab>('overview');
  const [saved, setSaved] = useState(false);
  const [savingBookmark, setSavingBookmark] = useState(false);
  const [cookingStep, setCookingStep] = useState(0);

  // Check if recipe is already saved on mount
  useEffect(() => {
    if (!recipe) return;
    fetchSavedRecipeIds(getCurrentUserId()).then((ids) => {
      if (ids.includes(recipe.id)) setSaved(true);
    }).catch(() => {});
  }, [recipe?.id]);

  // Reset tab when recipe changes
  useEffect(() => {
    setTab('overview');
    setCookingStep(0);
  }, [recipe?.id]);

  if (!recipe) return null;

  const handleBookmark = async () => {
    if (savingBookmark) return;
    setSavingBookmark(true);
    try {
      if (saved) {
        const ok = await unsaveRecipe(recipe.id, getCurrentUserId());
        if (ok) setSaved(false);
      } else {
        const ok = await saveRecipe(recipe.id, getCurrentUserId());
        if (ok) setSaved(true);
      }
    } catch {
      // Silent fail
    } finally {
      setSavingBookmark(false);
    }
  };

  const tabs: { key: DetailTab; label: string }[] = [
    { key: 'overview', label: 'Overview' },
    { key: 'ingredients', label: 'Ingredients' },
    { key: 'steps', label: 'Steps' },
  ];

  // Build dietary flag badges from real data
  const dietaryBadges: { label: string; positive: boolean }[] = [];
  if (recipe.dietaryFlags) {
    const f = recipe.dietaryFlags;
    if (f.is_vegan) dietaryBadges.push({ label: 'Vegan', positive: true });
    if (f.is_vegetarian) dietaryBadges.push({ label: 'Vegetarian', positive: true });
    if (f.is_pescatarian_ok) dietaryBadges.push({ label: 'Pescatarian', positive: true });
    if (f.is_dairy_free) dietaryBadges.push({ label: 'Dairy-Free', positive: true });
    if (f.is_gluten_free) dietaryBadges.push({ label: 'Gluten-Free', positive: true });
    if (f.is_nut_free) dietaryBadges.push({ label: 'Nut-Free', positive: true });
    if (f.is_halal_ok) dietaryBadges.push({ label: 'Halal', positive: true });
    if (f.contains_pork) dietaryBadges.push({ label: 'Contains Pork', positive: false });
    if (f.contains_shellfish) dietaryBadges.push({ label: 'Contains Shellfish', positive: false });
    if (f.contains_alcohol) dietaryBadges.push({ label: 'Contains Alcohol', positive: false });
    if (f.vegan_if_substituted) dietaryBadges.push({ label: 'Vegan if substituted', positive: true });
    if (f.gluten_free_if_substituted) dietaryBadges.push({ label: 'GF if substituted', positive: true });
  }

  const totalSteps = recipe.steps.length;
  const currentStepData = recipe.steps[cookingStep];

  return (
    <AnimatePresence>
      <motion.div
        className="absolute inset-0 z-50 flex flex-col"
        style={{ background: '#141414' }}
        initial={{ y: '100%' }}
        animate={{ y: 0 }}
        exit={{ y: '100%' }}
        transition={{ type: 'spring', damping: 28, stiffness: 300 }}
        data-testid="recipe-detail"
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-3"
          style={{ paddingTop: 'max(env(safe-area-inset-top, 8px), 8px)' }}
        >
          <motion.button
            onClick={() => {
              if (tab === 'cooking') {
                setTab('steps');
                setCookingStep(0);
              } else {
                onClose();
              }
            }}
            className="flex items-center gap-1 px-2 py-3 -ml-1 rounded-xl"
            style={{ minWidth: 44, minHeight: 44 }}
            whileTap={{ scale: 0.92, opacity: 0.7 }}
            data-testid="recipe-close"
          >
            <ChevronLeft size={24} style={{ color: '#A5A29A' }} />
            <span className="text-sm font-medium" style={{ color: '#A5A29A' }}>
              {tab === 'cooking' ? 'Exit cooking' : 'Back'}
            </span>
          </motion.button>
          <div className="flex items-center gap-2">
            {recipe.regionTag && (
              <div
                className="px-2 py-0.5 rounded text-[10px] font-medium flex items-center gap-1"
                style={{ background: 'rgba(165,162,154,0.08)', color: '#A5A29A' }}
              >
                <MapPin size={10} />
                {recipe.regionTag}
              </div>
            )}
            {recipe.matchScore > 0 && (
              <div
                className="px-2.5 py-1 rounded-full text-xs font-semibold"
                style={{ background: 'rgba(212, 168, 85, 0.15)', color: '#D4A855' }}
              >
                {recipe.matchScore}% match
              </div>
            )}
          </div>
        </div>

        {/* ---------- COOKING MODE ---------- */}
        {tab === 'cooking' ? (
          <div className="flex-1 flex flex-col px-5 py-4">
            {/* Progress */}
            <div className="mb-2">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-medium" style={{ color: '#D4A855' }}>
                  Step {cookingStep + 1} of {totalSteps}
                </span>
                <span className="text-xs" style={{ color: '#706D65' }}>
                  {Math.round(((cookingStep + 1) / totalSteps) * 100)}%
                </span>
              </div>
              <div className="h-1 rounded-full" style={{ background: '#2A2A2A' }}>
                <motion.div
                  className="h-full rounded-full"
                  style={{ background: '#D4A855' }}
                  animate={{ width: `${((cookingStep + 1) / totalSteps) * 100}%` }}
                  transition={{ duration: 0.3 }}
                />
              </div>
            </div>

            {/* Current step */}
            <div className="flex-1 flex flex-col justify-center">
              <AnimatePresence mode="wait">
                <motion.div
                  key={cookingStep}
                  initial={{ opacity: 0, x: 30 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -30 }}
                  transition={{ duration: 0.25 }}
                  className="text-center"
                >
                  <div
                    className="w-14 h-14 rounded-full flex items-center justify-center mx-auto mb-6 text-lg font-bold"
                    style={{ background: 'rgba(212,168,85,0.12)', color: '#D4A855' }}
                  >
                    {cookingStep + 1}
                  </div>
                  <p className="text-base leading-relaxed" style={{ color: '#F0EDE8' }}>
                    {currentStepData?.instruction}
                  </p>
                  {currentStepData?.techniqueTags && currentStepData.techniqueTags.length > 0 && (
                    <div className="flex flex-wrap justify-center gap-1.5 mt-4">
                      {currentStepData.techniqueTags.map((t) => (
                        <span key={t} className="text-[10px] px-2 py-0.5 rounded" style={{ background: '#262626', color: '#706D65' }}>
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                </motion.div>
              </AnimatePresence>
            </div>

            {/* Navigation */}
            <div className="flex gap-3">
              {cookingStep > 0 && (
                <motion.button
                  onClick={() => setCookingStep((s) => s - 1)}
                  className="flex-1 h-12 rounded-xl text-sm font-medium flex items-center justify-center"
                  style={{ background: '#1E1E1E', border: '1px solid #2A2A2A', color: '#F0EDE8' }}
                  whileTap={{ scale: 0.97 }}
                >
                  Previous
                </motion.button>
              )}
              {cookingStep < totalSteps - 1 ? (
                <motion.button
                  onClick={() => setCookingStep((s) => s + 1)}
                  className="flex-1 h-12 rounded-xl text-sm font-semibold flex items-center justify-center gap-2"
                  style={{ background: '#D4A855', color: '#141414' }}
                  whileTap={{ scale: 0.97 }}
                >
                  Next step
                  <ChevronRight size={16} />
                </motion.button>
              ) : (
                <motion.button
                  onClick={() => {
                    setTab('overview');
                    setCookingStep(0);
                  }}
                  className="flex-1 h-12 rounded-xl text-sm font-semibold flex items-center justify-center gap-2"
                  style={{ background: '#62AD76', color: '#141414' }}
                  whileTap={{ scale: 0.97 }}
                >
                  <Check size={16} />
                  Done cooking
                </motion.button>
              )}
            </div>
          </div>
        ) : (
          <>
            {/* Title & tags */}
            <div className="px-5 pb-3">
              <h1 className="text-xl font-semibold leading-tight" style={{ color: '#F0EDE8' }}>
                {recipe.title}
              </h1>
              <div className="flex flex-wrap gap-1.5 mt-2">
                {recipe.cuisine.map((c) => (
                  <span
                    key={c}
                    className="text-[10px] font-medium uppercase px-2 py-0.5 rounded"
                    style={{ background: 'rgba(139, 58, 74, 0.2)', color: '#C45A70' }}
                  >
                    {c}
                  </span>
                ))}
                {recipe.dietary.map((d) => (
                  <span
                    key={d}
                    className="text-[10px] font-medium uppercase px-2 py-0.5 rounded"
                    style={{ background: 'rgba(74, 139, 92, 0.2)', color: '#62AD76' }}
                  >
                    {d}
                  </span>
                ))}
              </div>
            </div>

            {/* Tab bar */}
            <div className="flex px-5 gap-1 border-b" style={{ borderColor: '#2A2A2A' }}>
              {tabs.map((t) => (
                <button
                  key={t.key}
                  onClick={() => setTab(t.key)}
                  className="pb-2.5 px-3 text-sm font-medium relative transition-colors"
                  style={{
                    color: tab === t.key ? '#D4A855' : '#706D65',
                  }}
                  data-testid={`tab-${t.key}`}
                >
                  {t.label}
                  {tab === t.key && (
                    <motion.div
                      className="absolute bottom-0 left-0 right-0 h-[2px] rounded-full"
                      style={{ background: '#D4A855' }}
                      layoutId="tab-indicator"
                    />
                  )}
                </button>
              ))}
            </div>

            {/* Tab content */}
            <div className="flex-1 overflow-y-auto px-5 py-4">
              {tab === 'overview' && (
                <div className="space-y-5">
                  <p className="text-sm leading-relaxed" style={{ color: '#A5A29A' }}>
                    {recipe.description}
                  </p>

                  {/* Stats row */}
                  <div className="flex gap-4">
                    <div className="flex items-center gap-2 px-3 py-2 rounded-lg" style={{ background: '#1E1E1E' }}>
                      <Clock size={14} style={{ color: '#D4A855' }} />
                      <span className="text-sm" style={{ color: '#F0EDE8' }}>{recipe.time} min</span>
                    </div>
                    <div className="flex items-center gap-2 px-3 py-2 rounded-lg" style={{ background: '#1E1E1E' }}>
                      <Flame size={14} style={{ color: '#D4A855' }} />
                      <DifficultyDots level={recipe.difficulty} />
                    </div>
                    <div className="flex items-center gap-2 px-3 py-2 rounded-lg" style={{ background: '#1E1E1E' }}>
                      <Users size={14} style={{ color: '#D4A855' }} />
                      <span className="text-sm" style={{ color: '#F0EDE8' }}>{recipe.servings}</span>
                    </div>
                  </div>

                  {/* Dietary flags */}
                  {dietaryBadges.length > 0 && (
                    <div>
                      <h3 className="text-sm font-medium mb-2" style={{ color: '#F0EDE8' }}>Dietary information</h3>
                      <div className="flex flex-wrap gap-1.5">
                        {dietaryBadges.map((b) => (
                          <DietaryBadge key={b.label} label={b.label} positive={b.positive} />
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Nutrition */}
                  <div>
                    <h3 className="text-sm font-medium mb-2" style={{ color: '#F0EDE8' }}>Nutrition per serving</h3>
                    <div className="grid grid-cols-4 gap-2">
                      {[
                        { label: 'Calories', value: recipe.nutrition.calories, unit: 'kcal' },
                        { label: 'Protein', value: recipe.nutrition.protein, unit: 'g' },
                        { label: 'Carbs', value: recipe.nutrition.carbs, unit: 'g' },
                        { label: 'Fat', value: recipe.nutrition.fat, unit: 'g' },
                        { label: 'Fibre', value: recipe.nutrition.fibre, unit: 'g' },
                        { label: 'Sat. Fat', value: recipe.nutrition.saturatedFat, unit: 'g' },
                        { label: 'Sugar', value: recipe.nutrition.sugar, unit: 'g' },
                        { label: 'Salt', value: recipe.nutrition.salt, unit: 'g' },
                      ].filter(n => n.value > 0).map((n) => (
                        <div key={n.label} className="text-center p-2 rounded-lg" style={{ background: '#1E1E1E' }}>
                          <div className="text-sm font-semibold" style={{ color: '#D4A855' }}>{n.value}{n.unit !== 'kcal' ? n.unit : ''}</div>
                          <div className="text-[10px] mt-0.5" style={{ color: '#706D65' }}>{n.label}</div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Flavour & Texture */}
                  {(recipe.flavourTags.length > 0 || recipe.textureTags.length > 0) && (
                    <div>
                      <h3 className="text-sm font-medium mb-2" style={{ color: '#F0EDE8' }}>Flavour & Texture</h3>
                      <div className="flex flex-wrap gap-1.5">
                        {recipe.flavourTags.map((t) => (
                          <span key={t} className="text-[11px] px-2 py-1 rounded-full" style={{ background: '#262626', color: '#A5A29A' }}>
                            {t}
                          </span>
                        ))}
                        {recipe.textureTags.map((t) => (
                          <span key={t} className="text-[11px] px-2 py-1 rounded-full" style={{ background: '#262626', color: '#A5A29A' }}>
                            {t}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Wine pairing */}
                  {recipe.winePairingNotes && (
                    <div className="p-3 rounded-xl" style={{ background: '#1E1E1E', border: '1px solid rgba(139,58,74,0.2)' }}>
                      <div className="flex items-center gap-2 mb-1.5">
                        <Wine size={14} style={{ color: '#C45A70' }} />
                        <h3 className="text-sm font-medium" style={{ color: '#F0EDE8' }}>Wine pairing</h3>
                      </div>
                      <p className="text-xs leading-relaxed" style={{ color: '#A5A29A' }}>{recipe.winePairingNotes}</p>
                    </div>
                  )}

                  {/* Tips */}
                  {recipe.tips && recipe.tips.length > 0 && (
                    <div>
                      <div className="flex items-center gap-2 mb-2">
                        <Lightbulb size={14} style={{ color: '#D4A855' }} />
                        <h3 className="text-sm font-medium" style={{ color: '#F0EDE8' }}>Tips</h3>
                      </div>
                      <div className="space-y-1.5">
                        {recipe.tips.map((tip, i) => (
                          <p key={i} className="text-xs leading-relaxed pl-3" style={{ color: '#A5A29A', borderLeft: '2px solid rgba(212,168,85,0.2)' }}>
                            {tip}
                          </p>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Season & occasion tags */}
                  {((recipe.seasonTags && recipe.seasonTags.length > 0) || (recipe.occasionTags && recipe.occasionTags.length > 0)) && (
                    <div className="flex flex-wrap gap-1.5">
                      {recipe.seasonTags?.map((t) => (
                        <span key={t} className="text-[10px] px-2 py-0.5 rounded-full" style={{ background: 'rgba(212,168,85,0.08)', color: '#D4A855' }}>
                          {t}
                        </span>
                      ))}
                      {recipe.occasionTags?.map((t) => (
                        <span key={t} className="text-[10px] px-2 py-0.5 rounded-full" style={{ background: 'rgba(165,162,154,0.08)', color: '#A5A29A' }}>
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {tab === 'ingredients' && (
                <div className="space-y-2">
                  {recipe.ingredients.map((ing, i) => (
                    <div
                      key={i}
                      className="flex items-center justify-between py-2.5 border-b"
                      style={{ borderColor: '#1E1E1E' }}
                    >
                      <div className="flex items-center gap-2">
                        <div className="w-1.5 h-1.5 rounded-full" style={{ background: '#D4A855' }} />
                        <span className="text-sm" style={{ color: '#F0EDE8' }}>{ing.name}</span>
                      </div>
                      <div className="text-right">
                        <span className="text-sm" style={{ color: '#A5A29A' }}>
                          {ing.amount} {ing.unit}
                        </span>
                        {ing.substitution && (
                          <div className="flex items-center gap-0.5 mt-0.5">
                            <Leaf size={9} style={{ color: '#62AD76' }} />
                            <span className="text-[10px]" style={{ color: '#62AD76' }}>
                              or {ing.substitution}
                            </span>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {tab === 'steps' && (
                <div className="space-y-4">
                  {recipe.steps.map((step) => (
                    <div key={step.number} className="flex gap-3">
                      <div
                        className="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 text-xs font-semibold"
                        style={{ background: 'rgba(212, 168, 85, 0.12)', color: '#D4A855' }}
                      >
                        {step.number}
                      </div>
                      <div className="flex-1 pt-0.5">
                        <p className="text-sm leading-relaxed" style={{ color: '#F0EDE8' }}>
                          {step.instruction}
                        </p>
                        <div className="flex flex-wrap gap-1 mt-2">
                          {step.techniqueTags.map((t) => (
                            <span key={t} className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: '#262626', color: '#706D65' }}>
                              {t}
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Bottom action bar */}
            <div
              className="flex items-center gap-3 px-5 pt-3 border-t"
              style={{ borderColor: '#2A2A2A', paddingBottom: 'max(env(safe-area-inset-bottom, 12px), 12px)' }}
            >
              <button
                onClick={handleBookmark}
                disabled={savingBookmark}
                className="w-12 h-12 rounded-xl flex items-center justify-center transition-colors"
                style={{
                  background: saved ? 'rgba(212, 168, 85, 0.15)' : '#1E1E1E',
                  border: `1px solid ${saved ? 'rgba(212, 168, 85, 0.3)' : '#333333'}`,
                  opacity: savingBookmark ? 0.6 : 1,
                }}
                data-testid="recipe-save"
              >
                <Bookmark
                  size={20}
                  fill={saved ? '#D4A855' : 'none'}
                  style={{ color: saved ? '#D4A855' : '#A5A29A' }}
                />
              </button>
              <button
                onClick={() => {
                  setTab('cooking');
                  setCookingStep(0);
                }}
                className="flex-1 h-12 rounded-xl text-sm font-semibold flex items-center justify-center gap-2 transition-colors"
                style={{ background: '#D4A855', color: '#141414' }}
                data-testid="start-cooking"
              >
                Start Cooking
                <ChevronRight size={16} />
              </button>
            </div>
          </>
        )}
      </motion.div>
    </AnimatePresence>
  );
}
