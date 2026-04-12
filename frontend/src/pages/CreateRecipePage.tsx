import { useState } from 'react';
import { useLocation } from 'wouter';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ArrowLeft, Sparkles, PenLine, Plus, X, Clock, Users,
  Globe, Lock, Loader2, Check,
} from 'lucide-react';
import {
  queryPipeline, fetchRecipeById, recipeToUiFormat,
  logActivity, getCurrentUserId,
} from '../lib/api';
import type { UiRecipe } from '../lib/api';

type Mode = 'choose' | 'ai' | 'form';

const cuisineOptions = ['Japanese', 'Italian', 'Thai', 'Mexican', 'Indian', 'French', 'Korean', 'Mediterranean', 'Middle Eastern', 'Chinese', 'Vietnamese', 'Greek', 'Spanish', 'North African', 'Caribbean', 'Dutch'];
const dietaryOptions = ['Vegan', 'Vegetarian', 'Gluten-Free', 'Dairy-Free', 'Nut-Free', 'Halal', 'Pescatarian'];

interface SimpleIngredient {
  name: string;
  amount: string;
  unit: string;
}

export default function CreateRecipePage() {
  const [, navigate] = useLocation();
  const [mode, setMode] = useState<Mode>('choose');

  // AI mode state
  const [aiPrompt, setAiPrompt] = useState('');
  const [aiGenerating, setAiGenerating] = useState(false);
  const [aiResult, setAiResult] = useState<{ text: string; recipe: UiRecipe | null } | null>(null);
  const [aiError, setAiError] = useState<string | null>(null);

  // Form mode state
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [selectedCuisines, setSelectedCuisines] = useState<string[]>([]);
  const [selectedDietary, setSelectedDietary] = useState<string[]>([]);
  const [time, setTime] = useState(30);
  const [servings, setServings] = useState(2);
  const [difficulty, setDifficulty] = useState(1);
  const [isPublic, setIsPublic] = useState(false);
  const [ingredients, setIngredients] = useState<SimpleIngredient[]>([]);
  const [newIngName, setNewIngName] = useState('');
  const [newIngAmount, setNewIngAmount] = useState('');
  const [newIngUnit, setNewIngUnit] = useState('');
  const [steps, setSteps] = useState<string[]>([]);
  const [newStep, setNewStep] = useState('');
  const [notes, setNotes] = useState('');
  const [formSaving, setFormSaving] = useState(false);
  const [formSaved, setFormSaved] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const toggleChip = (list: string[], item: string, setter: (v: string[]) => void) => {
    setter(list.includes(item) ? list.filter((i) => i !== item) : [...list, item]);
  };

  const addIngredient = () => {
    if (!newIngName.trim()) return;
    setIngredients([...ingredients, { name: newIngName.trim(), amount: newIngAmount.trim(), unit: newIngUnit.trim() }]);
    setNewIngName('');
    setNewIngAmount('');
    setNewIngUnit('');
  };

  const removeIngredient = (idx: number) => {
    setIngredients(ingredients.filter((_, i) => i !== idx));
  };

  const addStep = () => {
    if (!newStep.trim()) return;
    setSteps([...steps, newStep.trim()]);
    setNewStep('');
  };

  const removeStep = (idx: number) => {
    setSteps(steps.filter((_, i) => i !== idx));
  };

  const handleAiGenerate = async () => {
    if (!aiPrompt.trim() || aiGenerating) return;
    setAiGenerating(true);
    setAiError(null);
    setAiResult(null);

    try {
      const uid = await getCurrentUserId();
      const pipelineResp = await queryPipeline(
        `Create a recipe: ${aiPrompt}`,
        uid,
      );

      const generatedText = pipelineResp.response.generated_text;
      let recipe: UiRecipe | null = null;

      if (pipelineResp.response.results.length > 0) {
        const firstResult = pipelineResp.response.results[0];
        try {
          const fullRecipe = await fetchRecipeById(firstResult.recipe_id);
          if (fullRecipe) {
            recipe = {
              ...recipeToUiFormat(fullRecipe),
              matchScore: Math.round(firstResult.match_score * 100),
            };
          }
        } catch {
          recipe = {
            id: firstResult.recipe_id,
            title: firstResult.title,
            cuisine: [],
            dietary: [],
            time: firstResult.time_total_min || 0,
            difficulty: firstResult.difficulty || 1,
            matchScore: Math.round(firstResult.match_score * 100),
            description: '',
            servings: firstResult.serves || 2,
            ingredients: [],
            steps: [],
            nutrition: { calories: 0, protein: 0, carbs: 0, fat: 0, fibre: 0, saturatedFat: 0, sugar: 0, salt: 0 },
            flavourTags: [],
            textureTags: [],
            dietaryFlags: {},
            tips: [],
          };
        }
      }

      setAiResult({ text: generatedText, recipe });
    } catch (err: any) {
      setAiError(err.message || 'Pipeline unavailable — the backend may not be running.');
    } finally {
      setAiGenerating(false);
    }
  };

  // Save the AI-generated recipe as an activity event + navigate
  const handleSaveAiRecipe = async () => {
    if (aiResult?.recipe) {
      const uid = await getCurrentUserId();
      await logActivity(
        uid,
        'recipe_created',
        aiResult.recipe.id,
        `AI-created: ${aiResult.recipe.title}`,
      );
    }
    navigate('/library');
  };

  // Save manually-created recipe as an activity event
  const handleSaveFormRecipe = async () => {
    if (!title.trim() || formSaving) return;
    setFormSaving(true);
    try {
      const recipeId = crypto.randomUUID();
      const uid = await getCurrentUserId();
      await logActivity(
        uid,
        'recipe_created',
        recipeId,
        JSON.stringify({
          title,
          description,
          cuisine: selectedCuisines,
          dietary: selectedDietary,
          time,
          servings,
          difficulty,
          ingredients,
          steps,
          notes,
          is_public: isPublic,
        }),
      );
      setFormSaved(true);
      setTimeout(() => navigate('/library'), 800);
    } catch {
      setFormError('Failed to save recipe. Please try again.');
      setTimeout(() => navigate('/library'), 2000);
    } finally {
      setFormSaving(false);
    }
  };

  const ease = [0.25, 0.1, 0.25, 1] as const;

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 px-5 py-3">
        <motion.button
          onClick={() => mode === 'choose' ? navigate('/library') : setMode('choose')}
          whileTap={{ scale: 0.9 }}
        >
          <ArrowLeft size={22} style={{ color: '#A5A29A' }} />
        </motion.button>
        <h1 className="text-lg font-semibold" style={{ color: '#F0EDE8' }}>
          {mode === 'choose' ? 'New recipe' : mode === 'ai' ? 'Describe your recipe' : 'Create recipe'}
        </h1>
      </div>

      <div className="flex-1 overflow-y-auto hide-scrollbar px-5 pb-6">
        <AnimatePresence mode="wait">
          {/* --- Mode chooser --- */}
          {mode === 'choose' && (
            <motion.div
              key="choose"
              className="space-y-3 pt-4"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.3, ease }}
            >
              <p className="text-sm mb-4" style={{ color: '#A5A29A' }}>
                How would you like to create your recipe?
              </p>

              <motion.button
                onClick={() => setMode('ai')}
                className="w-full p-4 rounded-xl text-left"
                style={{ background: '#1E1E1E', border: '1px solid #2A2A2A' }}
                whileTap={{ scale: 0.98 }}
              >
                <div className="flex items-start gap-3">
                  <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ background: 'rgba(212,168,85,0.12)' }}>
                    <Sparkles size={20} style={{ color: '#D4A855' }} />
                  </div>
                  <div className="flex-1">
                    <h3 className="text-sm font-medium" style={{ color: '#F0EDE8' }}>
                      Describe it in plain text
                    </h3>
                    <p className="text-xs mt-1" style={{ color: '#A5A29A' }}>
                      Tell miam what you want to cook and the agent will find or build the full recipe for you
                    </p>
                  </div>
                </div>
              </motion.button>

              <motion.button
                onClick={() => setMode('form')}
                className="w-full p-4 rounded-xl text-left"
                style={{ background: '#1E1E1E', border: '1px solid #2A2A2A' }}
                whileTap={{ scale: 0.98 }}
              >
                <div className="flex items-start gap-3">
                  <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ background: 'rgba(212,168,85,0.12)' }}>
                    <PenLine size={20} style={{ color: '#D4A855' }} />
                  </div>
                  <div className="flex-1">
                    <h3 className="text-sm font-medium" style={{ color: '#F0EDE8' }}>
                      Fill in the form
                    </h3>
                    <p className="text-xs mt-1" style={{ color: '#A5A29A' }}>
                      Manually add title, ingredients, steps, and details
                    </p>
                  </div>
                </div>
              </motion.button>
            </motion.div>
          )}

          {/* --- AI mode --- */}
          {mode === 'ai' && (
            <motion.div
              key="ai"
              className="space-y-4 pt-2"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.3, ease }}
            >
              <p className="text-xs" style={{ color: '#A5A29A' }}>
                Describe the recipe you have in mind — ingredients, cuisine, style, anything. The pipeline will search 2,700+ recipes to find your best match.
              </p>

              <textarea
                value={aiPrompt}
                onChange={(e) => setAiPrompt(e.target.value)}
                placeholder="e.g. A spicy Korean fried cauliflower with gochujang glaze, served with pickled daikon and steamed rice. Make it vegan."
                rows={5}
                className="w-full rounded-xl p-4 text-sm resize-none outline-none"
                style={{
                  background: '#1E1E1E',
                  border: '1px solid #2A2A2A',
                  color: '#F0EDE8',
                }}
                data-testid="ai-prompt"
              />

              {/* Visibility toggle */}
              <div className="flex items-center justify-between py-2">
                <div className="flex items-center gap-2">
                  {isPublic ? <Globe size={16} style={{ color: '#D4A855' }} /> : <Lock size={16} style={{ color: '#A5A29A' }} />}
                  <span className="text-sm" style={{ color: '#F0EDE8' }}>
                    {isPublic ? 'Public' : 'Private'}
                  </span>
                </div>
                <motion.button
                  onClick={() => setIsPublic(!isPublic)}
                  className="w-11 h-6 rounded-full relative"
                  style={{ background: isPublic ? 'rgba(212,168,85,0.3)' : '#333333' }}
                  whileTap={{ scale: 0.95 }}
                >
                  <motion.div
                    className="absolute top-0.5 w-5 h-5 rounded-full"
                    style={{ background: isPublic ? '#D4A855' : '#706D65' }}
                    animate={{ left: isPublic ? 22 : 2 }}
                    transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                  />
                </motion.button>
              </div>

              {/* Error message */}
              {aiError && (
                <div className="p-3 rounded-xl" style={{ background: 'rgba(196,90,112,0.1)', border: '1px solid rgba(196,90,112,0.2)' }}>
                  <p className="text-xs" style={{ color: '#C45A70' }}>
                    {aiError}
                  </p>
                </div>
              )}

              {/* Generate button or result */}
              {!aiResult ? (
                <motion.button
                  onClick={handleAiGenerate}
                  disabled={!aiPrompt.trim() || aiGenerating}
                  className="w-full h-12 rounded-xl text-sm font-semibold flex items-center justify-center gap-2"
                  style={{
                    background: aiPrompt.trim() ? '#D4A855' : '#333333',
                    color: aiPrompt.trim() ? '#141414' : '#706D65',
                  }}
                  whileTap={aiPrompt.trim() ? { scale: 0.97 } : {}}
                  data-testid="ai-generate-btn"
                >
                  {aiGenerating ? (
                    <Loader2 size={18} className="animate-spin" style={{ color: '#141414' }} />
                  ) : (
                    <>
                      <Sparkles size={16} />
                      Generate recipe
                    </>
                  )}
                </motion.button>
              ) : (
                <motion.div
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="space-y-3"
                >
                  {/* Pipeline response text */}
                  <div className="p-4 rounded-xl" style={{ background: '#1E1E1E', border: '1px solid rgba(212,168,85,0.2)' }}>
                    <div className="flex items-center gap-2 mb-2">
                      <Sparkles size={14} style={{ color: '#D4A855' }} />
                      <span className="text-xs font-medium" style={{ color: '#D4A855' }}>Pipeline response</span>
                    </div>
                    <p className="text-sm leading-relaxed whitespace-pre-wrap" style={{ color: '#D8D6D0' }}>
                      {aiResult.text}
                    </p>
                  </div>

                  {/* Matched recipe card */}
                  {aiResult.recipe && (
                    <div className="p-4 rounded-xl" style={{ background: '#1E1E1E', border: '1px solid #2A2A2A' }}>
                      <h3 className="text-sm font-medium mb-1" style={{ color: '#F0EDE8' }}>
                        {aiResult.recipe.title}
                      </h3>
                      {aiResult.recipe.description && (
                        <p className="text-xs mb-2" style={{ color: '#A5A29A' }}>
                          {aiResult.recipe.description.slice(0, 150)}...
                        </p>
                      )}
                      <div className="flex gap-1.5">
                        {aiResult.recipe.cuisine.slice(0, 2).map((c) => (
                          <span key={c} className="text-[10px] font-medium uppercase px-1.5 py-0.5 rounded" style={{ background: 'rgba(139,58,74,0.2)', color: '#C45A70' }}>{c}</span>
                        ))}
                        {aiResult.recipe.dietary.slice(0, 2).map((d) => (
                          <span key={d} className="text-[10px] font-medium uppercase px-1.5 py-0.5 rounded" style={{ background: 'rgba(74,139,92,0.2)', color: '#62AD76' }}>{d}</span>
                        ))}
                      </div>
                    </div>
                  )}

                  <motion.button
                    onClick={handleSaveAiRecipe}
                    className="w-full h-12 rounded-xl text-sm font-semibold flex items-center justify-center gap-2"
                    style={{ background: '#D4A855', color: '#141414' }}
                    whileTap={{ scale: 0.97 }}
                  >
                    Save to my recipes
                  </motion.button>

                  <motion.button
                    onClick={() => { setAiResult(null); setAiError(null); }}
                    className="w-full h-10 rounded-xl text-sm font-medium flex items-center justify-center"
                    style={{ color: '#A5A29A' }}
                    whileTap={{ scale: 0.97 }}
                  >
                    Try again
                  </motion.button>
                </motion.div>
              )}
            </motion.div>
          )}

          {/* --- Form mode --- */}
          {mode === 'form' && (
            <motion.div
              key="form"
              className="space-y-5 pt-2 pb-4"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.3, ease }}
            >
              {/* Title */}
              <div>
                <label className="text-xs font-medium block mb-1.5" style={{ color: '#A5A29A' }}>Title</label>
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="e.g. Harissa-Roasted Cauliflower"
                  className="w-full rounded-lg px-3 py-2.5 text-sm outline-none"
                  style={{ background: '#1E1E1E', border: '1px solid #2A2A2A', color: '#F0EDE8' }}
                  data-testid="form-title"
                />
              </div>

              {/* Description */}
              <div>
                <label className="text-xs font-medium block mb-1.5" style={{ color: '#A5A29A' }}>Description</label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="A short description of the dish..."
                  rows={3}
                  className="w-full rounded-lg px-3 py-2.5 text-sm outline-none resize-none"
                  style={{ background: '#1E1E1E', border: '1px solid #2A2A2A', color: '#F0EDE8' }}
                />
              </div>

              {/* Cuisine */}
              <div>
                <label className="text-xs font-medium block mb-1.5" style={{ color: '#A5A29A' }}>Cuisine</label>
                <div className="flex flex-wrap gap-1.5">
                  {cuisineOptions.map((c) => (
                    <motion.button
                      key={c}
                      onClick={() => toggleChip(selectedCuisines, c, setSelectedCuisines)}
                      className="px-2.5 py-1 rounded-full text-[11px] font-medium"
                      style={{
                        background: selectedCuisines.includes(c) ? 'rgba(212,168,85,0.15)' : '#1E1E1E',
                        border: `1px solid ${selectedCuisines.includes(c) ? 'rgba(212,168,85,0.3)' : '#2A2A2A'}`,
                        color: selectedCuisines.includes(c) ? '#D4A855' : '#A5A29A',
                      }}
                      whileTap={{ scale: 0.94 }}
                    >
                      {c}
                    </motion.button>
                  ))}
                </div>
              </div>

              {/* Dietary */}
              <div>
                <label className="text-xs font-medium block mb-1.5" style={{ color: '#A5A29A' }}>Dietary</label>
                <div className="flex flex-wrap gap-1.5">
                  {dietaryOptions.map((d) => (
                    <motion.button
                      key={d}
                      onClick={() => toggleChip(selectedDietary, d, setSelectedDietary)}
                      className="px-2.5 py-1 rounded-full text-[11px] font-medium"
                      style={{
                        background: selectedDietary.includes(d) ? 'rgba(74,139,92,0.15)' : '#1E1E1E',
                        border: `1px solid ${selectedDietary.includes(d) ? 'rgba(74,139,92,0.3)' : '#2A2A2A'}`,
                        color: selectedDietary.includes(d) ? '#62AD76' : '#A5A29A',
                      }}
                      whileTap={{ scale: 0.94 }}
                    >
                      {d}
                    </motion.button>
                  ))}
                </div>
              </div>

              {/* Time / Servings / Difficulty row */}
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="text-xs font-medium block mb-1.5" style={{ color: '#A5A29A' }}>
                    <Clock size={11} className="inline mr-1" />Time (min)
                  </label>
                  <input
                    type="number"
                    value={time}
                    onChange={(e) => setTime(Number(e.target.value))}
                    className="w-full rounded-lg px-3 py-2 text-sm outline-none text-center"
                    style={{ background: '#1E1E1E', border: '1px solid #2A2A2A', color: '#F0EDE8' }}
                  />
                </div>
                <div>
                  <label className="text-xs font-medium block mb-1.5" style={{ color: '#A5A29A' }}>
                    <Users size={11} className="inline mr-1" />Serves
                  </label>
                  <input
                    type="number"
                    value={servings}
                    onChange={(e) => setServings(Number(e.target.value))}
                    className="w-full rounded-lg px-3 py-2 text-sm outline-none text-center"
                    style={{ background: '#1E1E1E', border: '1px solid #2A2A2A', color: '#F0EDE8' }}
                  />
                </div>
                <div>
                  <label className="text-xs font-medium block mb-1.5" style={{ color: '#A5A29A' }}>Difficulty</label>
                  <div className="flex gap-1.5 justify-center py-2">
                    {[1, 2, 3].map((d) => (
                      <motion.button
                        key={d}
                        onClick={() => setDifficulty(d)}
                        className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-semibold"
                        style={{
                          background: d <= difficulty ? 'rgba(212,168,85,0.2)' : '#1E1E1E',
                          border: `1px solid ${d <= difficulty ? 'rgba(212,168,85,0.4)' : '#2A2A2A'}`,
                          color: d <= difficulty ? '#D4A855' : '#706D65',
                        }}
                        whileTap={{ scale: 0.9 }}
                      >
                        {d}
                      </motion.button>
                    ))}
                  </div>
                </div>
              </div>

              {/* Ingredients */}
              <div>
                <label className="text-xs font-medium block mb-1.5" style={{ color: '#A5A29A' }}>Ingredients</label>
                {ingredients.map((ing, i) => (
                  <motion.div
                    key={i}
                    className="flex items-center gap-2 mb-1.5 py-1.5 px-3 rounded-lg"
                    style={{ background: '#1E1E1E' }}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.2 }}
                  >
                    <div className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: '#D4A855' }} />
                    <span className="text-sm flex-1" style={{ color: '#F0EDE8' }}>{ing.name}</span>
                    <span className="text-xs" style={{ color: '#A5A29A' }}>{ing.amount} {ing.unit}</span>
                    <button onClick={() => removeIngredient(i)}>
                      <X size={14} style={{ color: '#706D65' }} />
                    </button>
                  </motion.div>
                ))}
                <div className="flex gap-2 mt-1">
                  <input
                    value={newIngName}
                    onChange={(e) => setNewIngName(e.target.value)}
                    placeholder="Ingredient"
                    className="flex-1 rounded-lg px-3 py-2 text-xs outline-none"
                    style={{ background: '#1E1E1E', border: '1px solid #2A2A2A', color: '#F0EDE8' }}
                    onKeyDown={(e) => e.key === 'Enter' && addIngredient()}
                  />
                  <input
                    value={newIngAmount}
                    onChange={(e) => setNewIngAmount(e.target.value)}
                    placeholder="Amt"
                    className="w-14 rounded-lg px-2 py-2 text-xs outline-none text-center"
                    style={{ background: '#1E1E1E', border: '1px solid #2A2A2A', color: '#F0EDE8' }}
                  />
                  <input
                    value={newIngUnit}
                    onChange={(e) => setNewIngUnit(e.target.value)}
                    placeholder="Unit"
                    className="w-14 rounded-lg px-2 py-2 text-xs outline-none text-center"
                    style={{ background: '#1E1E1E', border: '1px solid #2A2A2A', color: '#F0EDE8' }}
                  />
                  <motion.button
                    onClick={addIngredient}
                    className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
                    style={{ background: 'rgba(212,168,85,0.15)', border: '1px solid rgba(212,168,85,0.3)' }}
                    whileTap={{ scale: 0.9 }}
                  >
                    <Plus size={14} style={{ color: '#D4A855' }} />
                  </motion.button>
                </div>
              </div>

              {/* Steps */}
              <div>
                <label className="text-xs font-medium block mb-1.5" style={{ color: '#A5A29A' }}>Steps</label>
                {steps.map((step, i) => (
                  <motion.div
                    key={i}
                    className="flex gap-2 mb-1.5 py-2 px-3 rounded-lg"
                    style={{ background: '#1E1E1E' }}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                  >
                    <div className="w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 text-[10px] font-semibold" style={{ background: 'rgba(212,168,85,0.12)', color: '#D4A855' }}>
                      {i + 1}
                    </div>
                    <p className="text-xs flex-1 leading-relaxed" style={{ color: '#F0EDE8' }}>{step}</p>
                    <button onClick={() => removeStep(i)} className="flex-shrink-0">
                      <X size={14} style={{ color: '#706D65' }} />
                    </button>
                  </motion.div>
                ))}
                <div className="flex gap-2 mt-1">
                  <input
                    value={newStep}
                    onChange={(e) => setNewStep(e.target.value)}
                    placeholder="Add a step..."
                    className="flex-1 rounded-lg px-3 py-2 text-xs outline-none"
                    style={{ background: '#1E1E1E', border: '1px solid #2A2A2A', color: '#F0EDE8' }}
                    onKeyDown={(e) => e.key === 'Enter' && addStep()}
                  />
                  <motion.button
                    onClick={addStep}
                    className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
                    style={{ background: 'rgba(212,168,85,0.15)', border: '1px solid rgba(212,168,85,0.3)' }}
                    whileTap={{ scale: 0.9 }}
                  >
                    <Plus size={14} style={{ color: '#D4A855' }} />
                  </motion.button>
                </div>
              </div>

              {/* Notes */}
              <div>
                <label className="text-xs font-medium block mb-1.5" style={{ color: '#A5A29A' }}>Notes (optional)</label>
                <textarea
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Any personal notes about this recipe..."
                  rows={2}
                  className="w-full rounded-lg px-3 py-2.5 text-sm outline-none resize-none"
                  style={{ background: '#1E1E1E', border: '1px solid #2A2A2A', color: '#F0EDE8' }}
                />
              </div>

              {/* Visibility */}
              <div className="flex items-center justify-between py-2">
                <div className="flex items-center gap-2">
                  {isPublic ? <Globe size={16} style={{ color: '#D4A855' }} /> : <Lock size={16} style={{ color: '#A5A29A' }} />}
                  <span className="text-sm" style={{ color: '#F0EDE8' }}>
                    {isPublic ? 'Public — visible to others' : 'Private — only you can see this'}
                  </span>
                </div>
                <motion.button
                  onClick={() => setIsPublic(!isPublic)}
                  className="w-11 h-6 rounded-full relative"
                  style={{ background: isPublic ? 'rgba(212,168,85,0.3)' : '#333333' }}
                  whileTap={{ scale: 0.95 }}
                >
                  <motion.div
                    className="absolute top-0.5 w-5 h-5 rounded-full"
                    style={{ background: isPublic ? '#D4A855' : '#706D65' }}
                    animate={{ left: isPublic ? 22 : 2 }}
                    transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                  />
                </motion.button>
              </div>

              {/* Form error */}
              {formError && (
                <p className="text-xs text-center" style={{ color: '#C45A70' }}>{formError}</p>
              )}

              {/* Save button */}
              <motion.button
                onClick={handleSaveFormRecipe}
                disabled={!title.trim() || formSaving}
                className="w-full h-12 rounded-xl text-sm font-semibold flex items-center justify-center gap-2"
                style={{
                  background: title.trim() ? (formSaved ? '#62AD76' : '#D4A855') : '#333333',
                  color: title.trim() ? '#141414' : '#706D65',
                  opacity: formSaving ? 0.7 : 1,
                }}
                whileTap={title.trim() ? { scale: 0.97 } : {}}
                data-testid="form-save-btn"
              >
                {formSaving ? (
                  <Loader2 size={18} className="animate-spin" />
                ) : formSaved ? (
                  <>
                    <Check size={16} />
                    Saved
                  </>
                ) : (
                  'Save recipe'
                )}
              </motion.button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
