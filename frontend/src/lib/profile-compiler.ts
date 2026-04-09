/**
 * miam Personal Ontology Compiler
 *
 * Converts 17 onboarding answers (structured + free-text) into a
 * fully populated profile_data JSON matching the backend UserProfile
 * Pydantic schema.
 *
 * Two-phase process:
 *   Phase 1 — Deterministic mapping of chips/sliders/rankings to schema fields
 *   Phase 2 — Mistral Small agent compiles all free-text answers into
 *             standardised enrichments that merge with Phase 1 output
 *
 * The result is upserted to Supabase `user_profiles.profile_data` as JSONB.
 */

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const MISTRAL_API_URL = 'https://api.mistral.ai/v1/chat/completions';
const MISTRAL_API_KEY = import.meta.env.VITE_MISTRAL_API_KEY || '';
const MISTRAL_MODEL = 'mistral-small-latest'; // never hardcode elsewhere

// ---------------------------------------------------------------------------
// Types matching backend personal_ontology.py
// ---------------------------------------------------------------------------

interface DimensionMeta {
  weight: 'core' | 'important' | 'optional' | 'contextual';
  confidence: number;
  last_updated: string;
  update_source: 'onboarding';
}

interface DietaryRestriction {
  label: string;
  is_hard_stop: boolean;
  reason: string | null;
  confidence: number;
}

interface CuisineAffinity {
  cuisine: string;
  level: 'love' | 'like' | 'neutral' | 'dislike' | 'never';
  sub_nuances: string[];
  confidence: number;
}

export interface ProfileData {
  user_id: string;
  schema_version: string;
  onboarding_complete: boolean;
  onboarding_version: string;
  created_at: string;
  last_updated: string;

  dietary: {
    spectrum_label: string | null;
    hard_stops: DietaryRestriction[];
    soft_stops: DietaryRestriction[];
    nuance_notes: string | null;
    meta: DimensionMeta;
  };

  cuisine_affinities: {
    affinities: CuisineAffinity[];
    meta: DimensionMeta;
  };

  flavor: {
    spicy: number | null;
    sweet: number | null;
    sour: number | null;
    umami: number | null;
    bitter: number | null;
    fatty: number | null;
    fermented: number | null;
    smoky: number | null;
    salty: number | null;
    meta: DimensionMeta;
  };

  texture: {
    crunchy: number | null;
    creamy: number | null;
    soft: number | null;
    chewy: number | null;
    crispy: number | null;
    silky: number | null;
    chunky: number | null;
    meta: DimensionMeta;
  };

  cooking: {
    skill: string;
    kitchen_setup: string;
    specific_equipment: Record<string, boolean>;
    weeknight_minutes: number;
    weekend_minutes: number;
    meta: DimensionMeta;
  };

  budget: {
    home_per_meal_eur: number | null;
    out_per_meal_eur: number | null;
    meta: DimensionMeta;
  };

  dining_vibe: {
    vibes: { vibe: string; score: number; confidence: number }[];
    meta: DimensionMeta;
  };

  adventurousness: {
    cooking_score: number;
    dining_score: number;
    meta: DimensionMeta;
  };

  nutrition: {
    level: string;
    tracked_dimensions: string[];
    meta: DimensionMeta;
  };

  social: {
    default_social_context: string;
    meals_out_per_week: number;
    home_cooked_per_week: number;
    meta: DimensionMeta;
  };

  lifestyle: {
    seasonal_preference_score: number;
    sustainability_priority_score: number;
    special_interests: string[];
    inspiration_style: string;
    meal_priorities: string[];
    favorite_ingredients: string[];
    meta: DimensionMeta;
  };

  location: {
    city: string | null;
    country: string | null;
    radius_km: number;
    meta: DimensionMeta;
  };

  tensions: any[];
  profile_summary_text: string | null;
}

// ---------------------------------------------------------------------------
// Helper: extract answer values from onboarding answer objects
// ---------------------------------------------------------------------------

function getSelection(answer: any): any {
  if (!answer) return null;
  if (answer.selection !== undefined) return answer.selection;
  return answer;
}

function getFreetext(answer: any): string {
  if (!answer) return '';
  if (typeof answer.freetext === 'string') return answer.freetext.trim();
  return '';
}

function getSliders(answer: any): Record<string, number> {
  if (!answer) return {};
  // Direct sliders prop
  if (answer.sliders && typeof answer.sliders === 'object') return answer.sliders;
  const sel = getSelection(answer);
  if (sel && typeof sel === 'object' && !Array.isArray(sel)) {
    // Combined format: { chips, sliders, extraChips }
    if (sel.sliders && typeof sel.sliders === 'object') return sel.sliders;
    // Plain slider format: all values are numbers
    const entries = Object.entries(sel).filter(([k]) => k !== 'chips' && k !== 'extraChips' && k !== 'sliders');
    const allNumeric = entries.length > 0 && entries.every(([_, v]) => typeof v === 'number');
    if (allNumeric) return Object.fromEntries(entries);
  }
  return {};
}

function getChips(answer: any): string[] {
  if (!answer) return [];
  // Direct chips prop
  if (answer.chips && Array.isArray(answer.chips)) return answer.chips;
  const sel = getSelection(answer);
  if (Array.isArray(sel)) return sel;
  // Combined format: { chips, sliders, extraChips }
  if (sel && typeof sel === 'object' && !Array.isArray(sel)) {
    const result: string[] = [];
    // Single-select chip stored as string
    if (typeof sel.chips === 'string' && sel.chips) result.push(sel.chips);
    // Multi-select chips stored as array
    if (Array.isArray(sel.chips)) result.push(...sel.chips);
    // Extra chips (e.g. equipment in q7, venue types in q12)
    if (Array.isArray(sel.extraChips)) result.push(...sel.extraChips);
    if (result.length > 0) return result;
  }
  return [];
}

function meta(weight: DimensionMeta['weight'], confidence: number): DimensionMeta {
  return {
    weight,
    confidence,
    last_updated: new Date().toISOString(),
    update_source: 'onboarding',
  };
}

// ---------------------------------------------------------------------------
// Phase 1: Deterministic mapping (no LLM needed)
// ---------------------------------------------------------------------------

export function compileStructuredProfile(
  userId: string,
  answers: Record<string, any>,
): ProfileData {
  const now = new Date().toISOString();

  // --- q1: Dietary spectrum ---
  const q1Sel = getSelection(answers.q1);
  let spectrumLabel: string | null = null;
  const spectrumMap: Record<string, string> = {
    'I eat everything': 'omnivore',
    'Pescatarian — fish but no meat': 'pescatarian',
    'Vegetarian': 'vegetarian',
    'Vegan': 'vegan',
    'Flexitarian — mostly plants, sometimes meat': 'flexitarian',
    'Low carb / keto': 'low_carb',
    'Paleo / whole foods': 'paleo',
    'Gluten-free lifestyle': 'gluten_free',
    'Halal': 'halal',
    'Kosher': 'kosher',
    'Raw food': 'raw_food',
  };
  if (Array.isArray(q1Sel) && q1Sel.length > 0) {
    // If multiple, combine (e.g. "flexitarian" + "halal" → "flexitarian-halal")
    const mapped = q1Sel.map((s: string) => spectrumMap[s] || s.toLowerCase()).filter(Boolean);
    spectrumLabel = mapped.length === 1 ? mapped[0] : mapped.join('-');
  } else if (typeof q1Sel === 'string') {
    spectrumLabel = spectrumMap[q1Sel] || q1Sel.toLowerCase();
  }

  // --- q2: Restrictions ---
  const q2Sel = getChips(answers.q2);
  const reasonMap: Record<string, string> = {
    'No pork': 'ethical', 'No beef': 'ethical', 'No red meat': 'preference', 'No lamb': 'preference',
    'No nuts': 'allergy', 'No peanuts': 'allergy', 'No shellfish': 'allergy', 'No eggs': 'allergy',
    'No soy': 'allergy', 'No fish': 'allergy', 'No sesame': 'allergy', 'No celery': 'allergy',
    'No mustard': 'allergy', 'No lupin': 'allergy',
    'No gluten (coeliac)': 'intolerance', 'No dairy (lactose)': 'intolerance',
    'No fructose': 'intolerance', 'No histamine': 'intolerance',
    'No coriander': 'dislike', 'No olives': 'dislike', 'No mushrooms': 'dislike', 'No blue cheese': 'dislike',
  };

  const dislikeItems = new Set(['No coriander', 'No olives', 'No mushrooms', 'No blue cheese']);
  const hardStops: DietaryRestriction[] = [];
  const softStops: DietaryRestriction[] = [];

  for (const item of q2Sel) {
    const label = item.replace(/^No /, '').replace(/ \(.*\)/, '').toLowerCase();
    const restriction: DietaryRestriction = {
      label,
      is_hard_stop: !dislikeItems.has(item),
      reason: reasonMap[item] || 'preference',
      confidence: dislikeItems.has(item) ? 0.8 : 1.0,
    };
    if (dislikeItems.has(item)) {
      softStops.push(restriction);
    } else {
      hardStops.push(restriction);
    }
  }

  // --- q3: Cuisine affinities ---
  const q3Raw = getSelection(answers.q3);
  const affinities: CuisineAffinity[] = [];
  if (q3Raw && typeof q3Raw === 'object' && !Array.isArray(q3Raw)) {
    const confidenceMap: Record<string, number> = { love: 0.9, like: 0.8, meh: 0.7, neutral: 0.7, skip: 0.7, dislike: 0.7 };
    const levelMap: Record<string, CuisineAffinity['level']> = {
      Love: 'love', Like: 'like', Meh: 'neutral', Skip: 'dislike',
      love: 'love', like: 'like', meh: 'neutral', skip: 'dislike',
      neutral: 'neutral', dislike: 'dislike',
    };
    for (const [cuisine, rawLevel] of Object.entries(q3Raw)) {
      if (typeof rawLevel !== 'string') continue;
      const level = levelMap[rawLevel] || 'neutral';
      affinities.push({
        cuisine,
        level,
        sub_nuances: [],
        confidence: confidenceMap[level] || 0.7,
      });
    }
  }

  // --- q4: Flavor sliders ---
  const q4Sliders = getSliders(answers.q4);
  const spiceRaw = q4Sliders['Spice level'] ?? null;
  const sweetSavoryRaw = q4Sliders['Sweet vs savoury'] ?? null;
  const lightRichRaw = q4Sliders['Light vs rich'] ?? null;
  const simpleComplexRaw = q4Sliders['Simple vs complex'] ?? null;

  const flavor: ProfileData['flavor'] = {
    spicy: spiceRaw !== null ? Math.round(spiceRaw / 10 * 10) / 10 : null,
    sweet: sweetSavoryRaw !== null ? Math.round((100 - sweetSavoryRaw) / 10 * 10) / 10 : null,
    sour: null,
    umami: simpleComplexRaw !== null ? Math.round(simpleComplexRaw / 10 * 10) / 10 : null,
    bitter: null,
    fatty: lightRichRaw !== null ? Math.round(lightRichRaw / 10 * 10) / 10 : null,
    fermented: null,
    smoky: null,
    salty: sweetSavoryRaw !== null ? Math.round(sweetSavoryRaw / 10 * 10) / 10 : null,
    meta: meta('important', 0.7),
  };

  // --- q5: Favourite ingredients + textures ---
  const q5All = getChips(answers.q5);
  const q5Sel = getSelection(answers.q5);

  // Ingredient chips come from grouped options
  const allIngredients = ['Garlic', 'Lemon', 'Chilli', 'Ginger', 'Coriander', 'Basil',
    'Miso', 'Cheese', 'Butter', 'Olive oil', 'Tahini', 'Coconut',
    'Avocado', 'Mushrooms', 'Aubergine', 'Sweet potato', 'Chickpeas', 'Tofu'];
  const allTextures = ['Crunchy', 'Creamy', 'Crispy', 'Silky smooth', 'Chunky', 'Chewy', 'Tender', 'Flaky'];

  // Extract from combined answer
  let ingredientChips: string[] = [];
  let textureChips: string[] = [];

  if (q5Sel && typeof q5Sel === 'object' && !Array.isArray(q5Sel)) {
    // Combined format
    const chips = Array.isArray(q5Sel.chips) ? q5Sel.chips : [];
    const extra = Array.isArray(q5Sel.extraChips) ? q5Sel.extraChips : [];
    ingredientChips = chips.filter((c: string) => allIngredients.includes(c));
    textureChips = extra.filter((c: string) => allTextures.includes(c));
  } else {
    // Fallback: split by known sets
    ingredientChips = q5All.filter(c => allIngredients.includes(c));
    textureChips = q5All.filter(c => allTextures.includes(c));
  }

  const favoriteIngredients: string[] = [...ingredientChips];

  // Ingredient → dimension boosts
  const umamiIngredients = ['Garlic', 'Miso', 'Mushrooms', 'Tahini'];
  const fattyIngredients = ['Butter', 'Cheese', 'Avocado', 'Olive oil', 'Coconut', 'Tahini'];
  const spicyIngredients = ['Chilli', 'Ginger'];
  const sourIngredients = ['Lemon'];

  for (const ing of ingredientChips) {
    if (umamiIngredients.includes(ing) && (flavor.umami === null || flavor.umami < 7)) {
      flavor.umami = Math.min(10, (flavor.umami ?? 5) + 1.5);
    }
    if (fattyIngredients.includes(ing) && (flavor.fatty === null || flavor.fatty < 7)) {
      flavor.fatty = Math.min(10, (flavor.fatty ?? 5) + 1.0);
    }
    if (spicyIngredients.includes(ing) && (flavor.spicy === null || flavor.spicy < 7)) {
      flavor.spicy = Math.min(10, (flavor.spicy ?? 5) + 1.0);
    }
    if (sourIngredients.includes(ing) && (flavor.sour === null)) {
      flavor.sour = 6.5;
    }
  }

  // Round all flavor values
  for (const key of Object.keys(flavor) as (keyof typeof flavor)[]) {
    if (key === 'meta') continue;
    const v = flavor[key];
    if (typeof v === 'number') {
      (flavor as any)[key] = Math.round(v * 10) / 10;
    }
  }

  // Texture from explicit texture chips + ingredient-based boosts
  const textureMap: Record<string, keyof ProfileData['texture']> = {
    'Crunchy': 'crunchy',
    'Creamy': 'creamy',
    'Crispy': 'crispy',
    'Silky smooth': 'silky',
    'Chunky': 'chunky',
    'Chewy': 'chewy',
    'Tender': 'soft',
    'Flaky': 'crispy', // maps to crispy dimension
  };

  const texture: ProfileData['texture'] = {
    crunchy: null, creamy: null, soft: null, chewy: null,
    crispy: null, silky: null, chunky: null,
    meta: meta('optional', textureChips.length > 0 ? 0.7 : 0.4),
  };

  for (const chip of textureChips) {
    const key = textureMap[chip];
    if (key && key !== 'meta') {
      (texture as any)[key] = Math.min(10, ((texture as any)[key] ?? 5) + 2.5);
    }
  }

  // Also keep ingredient-based texture boosts for backwards compat
  if (ingredientChips.some(i => ['Butter', 'Cheese', 'Avocado', 'Olive oil', 'Coconut', 'Tahini'].includes(i))) {
    texture.creamy = Math.min(10, (texture.creamy ?? 5) + 1.5);
  }

  // --- q6: Cooking skill ---
  const q6Chips = getChips(answers.q6);
  const q6Sliders = getSliders(answers.q6);
  const skillMap: Record<string, string> = {
    'Just starting out': 'beginner',
    'I can follow a recipe': 'home_cook',
    'Pretty confident': 'confident',
    'I know my way around': 'advanced',
    'Semi-pro level': 'professional',
  };
  let cookingSkill = 'home_cook';
  if (q6Chips.length > 0) {
    cookingSkill = skillMap[q6Chips[0]] || 'home_cook';
  }
  const weeknightMin = q6Sliders['Time on a weeknight'] ?? 30;
  const weekendMin = q6Sliders['Time on a weekend'] ?? 60;

  // --- q7: Kitchen equipment ---
  const q7Chips = getChips(answers.q7);
  const q7Sliders = getSliders(answers.q7);
  const equipmentMap: Record<string, string> = {
    'Air fryer': 'air_fryer',
    'Instant Pot / pressure cooker': 'pressure_cooker',
    'Slow cooker': 'pressure_cooker',
    'Wok': 'wok',
    'Grill / BBQ': 'outdoor_grill',
    'Sous vide': 'sous_vide',
    'Stand mixer': 'stand_mixer',
    'Blender': 'stand_mixer',
    'Food processor': 'food_processor',
    'Dutch oven': 'cast_iron',
    'Cast iron skillet': 'cast_iron',
  };
  const specificEquipment: Record<string, boolean> = {
    stand_mixer: false, food_processor: false, sous_vide: false,
    pressure_cooker: false, air_fryer: false, wok: false,
    cast_iron: false, outdoor_grill: false, pasta_machine: false,
    dehydrator: false,
  };
  for (const chip of q7Chips) {
    const key = equipmentMap[chip];
    if (key) specificEquipment[key] = true;
  }
  const specialtyCount = Object.values(specificEquipment).filter(Boolean).length;
  const kitchenSetup = specialtyCount >= 3 ? 'fully_equipped' : specialtyCount >= 1 ? 'well_equipped' : 'basic';

  // --- q8: Budget & portions ---
  const q8Sliders = getSliders(answers.q8);
  const typicalServings = q8Sliders['Typical servings'] ?? 2;
  const mealsPerWeek = q8Sliders['Meals you cook per week'] ?? 5;
  const groceryBudget = q8Sliders['Grocery budget per week'] ?? 65;
  const diningOutPerPerson = q8Sliders['Dining out per person'] ?? 25;

  // Derive home cost from grocery budget
  let homePerMealEur: number | null = null;
  if (mealsPerWeek > 0 && typicalServings > 0) {
    homePerMealEur = Math.round((groceryBudget / mealsPerWeek / typicalServings) * 100) / 100;
  }
  const outPerMealEur: number | null = diningOutPerPerson;

  let socialContext = 'couple';
  if (typicalServings <= 1) socialContext = 'solo';
  else if (typicalServings <= 2) socialContext = 'couple';
  else if (typicalServings <= 4) socialContext = 'family';
  else socialContext = 'group';

  // --- q9: Eating experience vibe ---
  const q9Chips = getChips(answers.q9);
  const defaultVibes = [
    { vibe: 'cozy', score: 5.0, confidence: 0.4 },
    { vibe: 'lively', score: 5.0, confidence: 0.4 },
    { vibe: 'trendy', score: 5.0, confidence: 0.4 },
    { vibe: 'classic', score: 5.0, confidence: 0.4 },
    { vibe: 'hidden_gem', score: 5.0, confidence: 0.4 },
    { vibe: 'romantic', score: 5.0, confidence: 0.4 },
    { vibe: 'business', score: 5.0, confidence: 0.4 },
    { vibe: 'efficient', score: 5.0, confidence: 0.4 },
  ];
  const vibeBoosts: Record<string, string[]> = {
    'Cosy & intimate': ['cozy'],
    'Buzzy & lively': ['lively'],
    'Trendy & modern': ['trendy'],
    'Classic & traditional': ['classic'],
    'Hidden gem': ['hidden_gem'],
    'Romantic': ['romantic'],
    'Quick & efficient': ['efficient'],
    'Outdoor / terrace': ['lively', 'cozy'],
    'Late night': ['lively', 'hidden_gem'],
  };
  const specialInterests: string[] = [];

  for (const chip of q9Chips) {
    const boosts = vibeBoosts[chip] || [];
    for (const vibeLabel of boosts) {
      const v = defaultVibes.find(x => x.vibe === vibeLabel);
      if (v) { v.score = Math.min(10, v.score + 2.0); v.confidence = 0.7; }
    }
  }

  // --- q10: Adventurousness ---
  const q10Sliders = getSliders(answers.q10);
  const q10Chips = getChips(answers.q10);

  let cookingAdventure = q10Sliders['Cooking adventure'] ?? 5.0;
  let diningAdventure = q10Sliders['Dining adventure'] ?? 5.0;

  // Chip boosts
  const adventureChipBoosts: Record<string, [number, number]> = {
    'I love my rotation of favourites': [-1.0, -1.0],
    'I try a new recipe every week or two': [1.5, 0],
    'I follow food trends': [1.0, 1.0],
    'I actively seek out unfamiliar cuisines': [0, 2.0],
    'Street food markets are my happy place': [0, 1.5],
    "I'll order the thing I can't pronounce": [0, 2.0],
  };

  for (const chip of q10Chips) {
    const [c, d] = adventureChipBoosts[chip] || [0, 0];
    cookingAdventure = Math.min(10, Math.max(0, cookingAdventure + c));
    diningAdventure = Math.min(10, Math.max(0, diningAdventure + d));
  }

  // --- q11: Nutrition ---
  const q11Sliders = getSliders(answers.q11);
  const calorieAwareness = q11Sliders['Calorie tracking'] ?? 30;
  const proteinFocus = q11Sliders['Protein focus'] ?? 40;
  const sugarIntake = q11Sliders['Sugar awareness'] ?? 30;
  const fibreLevel = q11Sliders['Fibre & wholefoods'] ?? 35;

  let nutritionLevel = 'none';
  if (calorieAwareness > 75) nutritionLevel = 'strict';
  else if (calorieAwareness > 50) nutritionLevel = 'moderate';
  else if (calorieAwareness > 25) nutritionLevel = 'light';

  const trackedDimensions: string[] = [];
  if (calorieAwareness > 50) trackedDimensions.push('calories');
  if (proteinFocus > 50) trackedDimensions.push('protein');
  if (sugarIntake > 50) trackedDimensions.push('sugar');
  if (fibreLevel > 50) trackedDimensions.push('fibre');

  // --- q12: Social eating ---
  // q12 is combined: chips = social context (single-select), extraChips = venue types
  const q12AllChips = getChips(answers.q12);
  const q12Sel = getSelection(answers.q12);
  // Extract the social context chip (from options, single-select)
  const socialOptions = ['Mostly solo', 'With my partner', 'Small group', 'Family', 'Varies a lot'];
  const venueOptions = ['Fine dining', 'Casual bistro', 'Street food', 'Fast casual', 'Food trucks', 'Cafés', 'Brunch spots', 'Late night spots', 'Pub grub', 'Pop-ups'];
  const socialChip = q12AllChips.find(c => socialOptions.includes(c)) ||
    (q12Sel && typeof q12Sel === 'object' && typeof q12Sel.chips === 'string' ? q12Sel.chips : null);
  const venueChips = q12AllChips.filter(c => venueOptions.includes(c));
  let mealsOutPerWeek = 2.0;
  const socialOverrides: Record<string, [string, number]> = {
    'Mostly solo': ['solo', 0.5],
    'With my partner': ['couple', 1.5],
    'Small group': ['group', 2.5],
    'Family': ['family', 1.0],
    'Varies a lot': ['couple', 2.0],
  };
  if (socialChip && socialOverrides[socialChip]) {
    const [ctx, meals] = socialOverrides[socialChip];
    socialContext = ctx;
    mealsOutPerWeek = meals;
  }

  const q12Sliders = getSliders(answers.q12);
  const mealsOutSlider = q12Sliders['Meals out per week'];
  if (typeof mealsOutSlider === 'number') {
    mealsOutPerWeek = mealsOutSlider;
  }

  // Venue chips → vibe boosts
  const venueVibeMap: Record<string, string> = {
    'Fine dining': 'romantic', 'Casual bistro': 'classic',
    'Street food': 'trendy', 'Fast casual': 'efficient',
    'Food trucks': 'trendy', 'Cafés': 'cozy',
    'Brunch spots': 'lively', 'Late night spots': 'hidden_gem',
    'Pub grub': 'classic', 'Pop-ups': 'trendy',
  };
  for (const venue of venueChips) {
    const vibeLabel = venueVibeMap[venue];
    if (vibeLabel) {
      const v = defaultVibes.find(x => x.vibe === vibeLabel);
      if (v) { v.score = Math.min(10, v.score + 1.5); v.confidence = 0.7; }
    }
  }

  // --- q13: Meal priorities ---
  const q13Chips = getChips(answers.q13);
  const mealPriorities = q13Chips.map((c: string) => c.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, ''));
  if ((q13Chips.includes('Meal prep') || q13Chips.includes('Batch cooking')) && !specialInterests.includes('meal_prep')) {
    specialInterests.push('meal_prep');
  }
  if (q13Chips.includes('Weekend feasts')) {
    cookingAdventure = Math.max(cookingAdventure, 6.0);
  }

  // --- q14: Values (sliders) ---
  const q14Sliders = getSliders(answers.q14);
  const organicPref = q14Sliders['Organic preference'] ?? 30;
  const localSourcing = q14Sliders['Local & seasonal'] ?? 40;

  const sustainabilityScore = Math.round(((organicPref + localSourcing) / 200) * 10 * 10) / 10;
  const seasonalScore = Math.round((localSourcing / 100) * 10 * 10) / 10;

  // --- q15: Food interests ---
  const q15Chips = getChips(answers.q15);
  const interestNormalise: Record<string, string> = {
    'Fermentation & pickling': 'fermentation',
    'Baking & pastry': 'baking',
    'BBQ & grilling': 'bbq',
    'Food science': 'food_science',
    'Food photography': 'food_photography',
    'Foraging': 'foraging',
    'Wine & pairing': 'wine_pairing',
    'Coffee & tea': 'coffee_tea',
    'Cocktails & spirits': 'cocktails',
    'Meal planning': 'meal_prep',
    'Zero waste cooking': 'zero_waste',
    'Cultural food history': 'food_history',
    'Cheese & charcuterie': 'cheese_charcuterie',
    'Spice blending': 'spice_blending',
  };
  for (const chip of q15Chips) {
    const norm = interestNormalise[chip] || chip.toLowerCase().replace(/ /g, '_');
    if (!specialInterests.includes(norm)) specialInterests.push(norm);
  }

  // --- q16: Location ---
  // q16 is text-input, so the main answer is in selection; freetext has extra notes
  const q16Sel = getSelection(answers.q16);
  const q16Text = (typeof q16Sel === 'string' && q16Sel.trim()) ? q16Sel.trim() : getFreetext(answers.q16);
  let city: string | null = null;
  let country: string | null = null;
  if (q16Text) {
    // Simple parsing: "Amsterdam, Netherlands" or "Amsterdam"
    const parts = q16Text.split(/[,\-—]+/).map((s: string) => s.trim()).filter(Boolean);
    if (parts.length >= 2) {
      city = parts[0];
      country = parts[parts.length - 1];
    } else if (parts.length === 1) {
      city = parts[0];
    }
  }

  // --- q17: Identity / inspiration ---
  const q17Sel = getSelection(answers.q17);
  let inspirationStyle = 'short_list';
  const identityLabel = Array.isArray(q17Sel) ? q17Sel[0] : q17Sel;
  const identityMap: Record<string, { style: string; adventureBoost?: number; nutritionBoost?: string; socialOverride?: string; budgetOverride?: number }> = {
    'Confident home cook': { style: 'short_list' },
    'Curious food explorer': { style: 'wide_selection', adventureBoost: 8.0 },
    'Health-conscious eater': { style: 'short_list', nutritionBoost: 'moderate' },
    'Busy but into good food': { style: 'short_list' },
    'Budget-savvy eater': { style: 'short_list', budgetOverride: 3.5 },
    'Aspiring chef': { style: 'wide_selection', adventureBoost: 8.0 },
    'I know exactly what I like': { style: 'one_best' },
    'Love feeding people': { style: 'wide_selection', socialOverride: 'group' },
  };
  if (typeof identityLabel === 'string' && identityMap[identityLabel]) {
    const id = identityMap[identityLabel];
    inspirationStyle = id.style;
    if (id.adventureBoost) {
      cookingAdventure = Math.max(cookingAdventure, id.adventureBoost);
      diningAdventure = Math.max(diningAdventure, id.adventureBoost);
    }
    if (id.nutritionBoost && nutritionLevel === 'none') nutritionLevel = id.nutritionBoost;
    if (id.socialOverride) socialContext = id.socialOverride;
    if (id.budgetOverride && homePerMealEur === null) homePerMealEur = id.budgetOverride;
  }

  // --- Assemble ---
  return {
    user_id: userId,
    schema_version: '1.0.0',
    onboarding_complete: true,
    onboarding_version: '1.0.0',
    created_at: now,
    last_updated: now,

    dietary: {
      spectrum_label: spectrumLabel,
      hard_stops: hardStops,
      soft_stops: softStops,
      nuance_notes: null,
      meta: meta('core', 0.9),
    },

    cuisine_affinities: {
      affinities,
      meta: meta('important', affinities.length > 0 ? 0.8 : 0.3),
    },

    flavor,

    texture,

    cooking: {
      skill: cookingSkill,
      kitchen_setup: kitchenSetup,
      specific_equipment: specificEquipment,
      weeknight_minutes: Math.round(weeknightMin),
      weekend_minutes: Math.round(weekendMin),
      meta: meta('core', 0.8),
    },

    budget: {
      home_per_meal_eur: homePerMealEur,
      out_per_meal_eur: outPerMealEur,
      meta: meta('important', homePerMealEur !== null ? 0.6 : 0.3),
    },

    dining_vibe: {
      vibes: defaultVibes,
      meta: meta('important', q9Chips.length > 0 ? 0.7 : 0.4),
    },

    adventurousness: {
      cooking_score: Math.round(cookingAdventure * 10) / 10,
      dining_score: Math.round(diningAdventure * 10) / 10,
      meta: meta('important', q10Chips.length > 0 ? 0.7 : 0.4),
    },

    nutrition: {
      level: nutritionLevel,
      tracked_dimensions: trackedDimensions,
      meta: meta('contextual', calorieAwareness > 25 ? 0.7 : 0.4),
    },

    social: {
      default_social_context: socialContext,
      meals_out_per_week: mealsOutPerWeek,
      home_cooked_per_week: Math.min(mealsPerWeek, 14),
      meta: meta('optional', 0.6),
    },

    lifestyle: {
      seasonal_preference_score: seasonalScore,
      sustainability_priority_score: sustainabilityScore,
      special_interests: [...new Set(specialInterests)],
      inspiration_style: inspirationStyle,
      meal_priorities: mealPriorities,
      favorite_ingredients: favoriteIngredients,
      meta: meta('optional', 0.5),
    },

    location: {
      city,
      country,
      radius_km: 5.0,
      meta: meta('core', city ? 0.9 : 0.1),
    },

    tensions: [],
    profile_summary_text: null,
  };
}

// ---------------------------------------------------------------------------
// Phase 2: Mistral agent compiles free-text into structured enrichments
// ---------------------------------------------------------------------------

/**
 * Collect all free-text answers from the 17 questions.
 * Returns null if no free-text was provided.
 */
function collectFreeTextAnswers(answers: Record<string, any>): Record<string, string> | null {
  const freeTexts: Record<string, string> = {};
  let hasAny = false;
  for (let i = 1; i <= 17; i++) {
    const key = `q${i}`;
    const ft = getFreetext(answers[key]);
    if (ft.length > 0) {
      freeTexts[key] = ft;
      hasAny = true;
    }
  }
  return hasAny ? freeTexts : null;
}

/**
 * Call Mistral Small to compile free-text answers into structured enrichments
 * that merge with the Phase 1 deterministic output.
 */
export async function compileFreeTextWithMistral(
  structuredProfile: ProfileData,
  freeTexts: Record<string, string>,
): Promise<Partial<ProfileData>> {
  const systemPrompt = `You are a food profile compiler for the app miam. Your job is to take a user's free-text onboarding answers and compile them into structured profile enrichments that complement their structured (chip/slider) answers.

RULES:
1. Output ONLY valid JSON — no markdown, no explanation
2. Only include fields where the free-text provides NEW or REFINED information beyond what the structured answers already capture
3. Standardise vocabulary: "more meat than fish" → dietary nuance, not raw text
4. Extract IMPLICIT information: "I cook for 2 adults and a toddler" → social_context: "family", nuance about child-friendly meals
5. For flavor/texture scores, use 0-10 scale (5 = neutral)
6. For dietary restrictions from free-text, classify as hard_stop (allergy, hate, never) or soft_stop (prefer to avoid, usually skip)
7. Detect tensions between answers and describe them
8. Generate a 2-4 sentence profile_summary_text in British English
9. Be precise — don't invent preferences the user didn't express

QUESTION CONTEXT:
q1 = Dietary identity, q2 = Restrictions/allergies, q3 = Cuisine preferences
q4 = Flavor sliders, q5 = Favourite ingredients, q6 = Cooking skill
q7 = Kitchen equipment, q8 = Budget & portions, q9 = Eating vibe
q10 = Adventurousness, q11 = Nutrition goals, q12 = Social eating
q13 = Meal priorities, q14 = Values (budget/organic/local), q15 = Food interests
q16 = Location, q17 = Identity/inspiration

OUTPUT SCHEMA (include only fields with new info):
{
  "dietary": {
    "spectrum_label": "refined label if free-text changes it",
    "soft_stops": [{"label": "...", "is_hard_stop": false, "reason": "preference", "confidence": 0.8}],
    "nuance_notes": "Any nuance that can't be captured structurally"
  },
  "cuisine_affinities": {
    "sub_nuance_updates": [{"cuisine": "Thai", "sub_nuances": ["avoid fish sauce", "prefer mild curries"]}]
  },
  "flavor": {"sour": 7.0, "smoky": 3.0, "fermented": 6.0},
  "texture": {"crunchy": 8.0, "chewy": 3.0},
  "cooking": {"weekend_minutes": 120},
  "budget": {"home_per_meal_eur": 5.0, "out_per_meal_eur": 25.0},
  "adventurousness": {"cooking_score": 7.0, "dining_score": 8.0},
  "nutrition": {"tracked_dimensions": ["fibre", "iron"]},
  "social": {"meals_out_per_week": 3.0},
  "lifestyle": {
    "special_interests": ["sourdough", "natural_wine"],
    "favorite_ingredients": ["tahini", "za'atar"]
  },
  "location": {"city": "Amsterdam", "country": "Netherlands", "secondary_cities": ["Paris"]},
  "tensions": [
    {
      "dimension_a": "dietary.spectrum_label",
      "dimension_b": "cuisine_affinities.affinities[cuisine='Japanese']",
      "description": "User says vegan but loves Japanese which typically uses dashi/fish",
      "severity": "medium"
    }
  ],
  "profile_summary_text": "2-4 sentence summary of this person's food identity in British English"
}`;

  const userPrompt = `STRUCTURED PROFILE (from chips/sliders):
${JSON.stringify({
    dietary_label: structuredProfile.dietary.spectrum_label,
    hard_stops: structuredProfile.dietary.hard_stops.map(h => h.label),
    cuisines: structuredProfile.cuisine_affinities.affinities.map(a => `${a.cuisine}: ${a.level}`),
    flavor_spicy: structuredProfile.flavor.spicy,
    flavor_sweet: structuredProfile.flavor.sweet,
    flavor_fatty: structuredProfile.flavor.fatty,
    skill: structuredProfile.cooking.skill,
    equipment: Object.entries(structuredProfile.cooking.specific_equipment).filter(([_, v]) => v).map(([k]) => k),
    adventure_cooking: structuredProfile.adventurousness.cooking_score,
    adventure_dining: structuredProfile.adventurousness.dining_score,
    interests: structuredProfile.lifestyle.special_interests,
    favorite_ingredients: structuredProfile.lifestyle.favorite_ingredients,
    identity: structuredProfile.lifestyle.inspiration_style,
    location: structuredProfile.location.city,
  }, null, 2)}

FREE-TEXT ANSWERS FROM USER:
${Object.entries(freeTexts).map(([q, text]) => `${q}: "${text}"`).join('\n')}

Compile the free-text into structured enrichments. Return ONLY JSON.`;

  try {
    const resp = await fetch(MISTRAL_API_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${MISTRAL_API_KEY}`,
      },
      body: JSON.stringify({
        model: MISTRAL_MODEL,
        messages: [
          { role: 'system', content: systemPrompt },
          { role: 'user', content: userPrompt },
        ],
        temperature: 0.3,
        max_tokens: 2000,
        response_format: { type: 'json_object' },
      }),
    });

    if (!resp.ok) {
      console.error('Mistral API error:', resp.status, await resp.text());
      return {};
    }

    const data = await resp.json();
    const content = data.choices?.[0]?.message?.content;
    if (!content) return {};

    return JSON.parse(content);
  } catch (err) {
    console.error('Mistral compilation failed:', err);
    return {};
  }
}

// ---------------------------------------------------------------------------
// Phase 3: Merge structured + LLM enrichments
// ---------------------------------------------------------------------------

export function mergeEnrichments(
  base: ProfileData,
  enrichments: Partial<ProfileData> & { cuisine_affinities?: any },
): ProfileData {
  const merged = { ...base };
  const e = enrichments as any;

  // Dietary enrichments
  if (e.dietary) {
    if (e.dietary.spectrum_label && e.dietary.spectrum_label !== base.dietary.spectrum_label) {
      merged.dietary = { ...merged.dietary, spectrum_label: e.dietary.spectrum_label };
    }
    if (e.dietary.nuance_notes) {
      merged.dietary = { ...merged.dietary, nuance_notes: e.dietary.nuance_notes };
    }
    if (Array.isArray(e.dietary.soft_stops)) {
      merged.dietary = {
        ...merged.dietary,
        soft_stops: [...merged.dietary.soft_stops, ...e.dietary.soft_stops],
      };
    }
  }

  // Cuisine sub-nuance updates
  if (e.cuisine_affinities?.sub_nuance_updates) {
    const updatedAffinities = [...merged.cuisine_affinities.affinities];
    for (const update of e.cuisine_affinities.sub_nuance_updates) {
      const existing = updatedAffinities.find(a => a.cuisine.toLowerCase() === update.cuisine.toLowerCase());
      if (existing) {
        existing.sub_nuances = [...new Set([...existing.sub_nuances, ...(update.sub_nuances || [])])];
      }
    }
    merged.cuisine_affinities = { ...merged.cuisine_affinities, affinities: updatedAffinities };
  }

  // Flavor enrichments — only override if agent provides a non-null value
  if (e.flavor) {
    const flavorKeys = ['spicy', 'sweet', 'sour', 'umami', 'bitter', 'fatty', 'fermented', 'smoky', 'salty'] as const;
    for (const key of flavorKeys) {
      if (typeof e.flavor[key] === 'number') {
        (merged.flavor as any)[key] = e.flavor[key];
      }
    }
  }

  // Texture enrichments
  if (e.texture) {
    const textureKeys = ['crunchy', 'creamy', 'soft', 'chewy', 'crispy', 'silky', 'chunky'] as const;
    for (const key of textureKeys) {
      if (typeof e.texture[key] === 'number') {
        (merged.texture as any)[key] = e.texture[key];
      }
    }
  }

  // Cooking enrichments
  if (e.cooking) {
    if (typeof e.cooking.weekend_minutes === 'number') {
      merged.cooking = { ...merged.cooking, weekend_minutes: e.cooking.weekend_minutes };
    }
    if (typeof e.cooking.weeknight_minutes === 'number') {
      merged.cooking = { ...merged.cooking, weeknight_minutes: e.cooking.weeknight_minutes };
    }
  }

  // Budget
  if (e.budget) {
    if (typeof e.budget.home_per_meal_eur === 'number') {
      merged.budget = { ...merged.budget, home_per_meal_eur: e.budget.home_per_meal_eur };
    }
    if (typeof e.budget.out_per_meal_eur === 'number') {
      merged.budget = { ...merged.budget, out_per_meal_eur: e.budget.out_per_meal_eur };
    }
  }

  // Adventurousness
  if (e.adventurousness) {
    if (typeof e.adventurousness.cooking_score === 'number') {
      merged.adventurousness = { ...merged.adventurousness, cooking_score: Math.max(merged.adventurousness.cooking_score, e.adventurousness.cooking_score) };
    }
    if (typeof e.adventurousness.dining_score === 'number') {
      merged.adventurousness = { ...merged.adventurousness, dining_score: Math.max(merged.adventurousness.dining_score, e.adventurousness.dining_score) };
    }
  }

  // Nutrition tracked dimensions
  if (e.nutrition?.tracked_dimensions) {
    const combined = [...new Set([...merged.nutrition.tracked_dimensions, ...e.nutrition.tracked_dimensions])];
    merged.nutrition = { ...merged.nutrition, tracked_dimensions: combined };
  }

  // Social
  if (e.social) {
    if (typeof e.social.meals_out_per_week === 'number') {
      merged.social = { ...merged.social, meals_out_per_week: e.social.meals_out_per_week };
    }
  }

  // Lifestyle enrichments
  if (e.lifestyle) {
    if (Array.isArray(e.lifestyle.special_interests)) {
      merged.lifestyle = {
        ...merged.lifestyle,
        special_interests: [...new Set([...merged.lifestyle.special_interests, ...e.lifestyle.special_interests])],
      };
    }
    if (Array.isArray(e.lifestyle.favorite_ingredients)) {
      merged.lifestyle = {
        ...merged.lifestyle,
        favorite_ingredients: [...new Set([...merged.lifestyle.favorite_ingredients, ...e.lifestyle.favorite_ingredients])],
      };
    }
  }

  // Location
  if (e.location) {
    if (e.location.city && !merged.location.city) {
      merged.location = { ...merged.location, city: e.location.city };
    }
    if (e.location.country && !merged.location.country) {
      merged.location = { ...merged.location, country: e.location.country };
    }
  }

  // Tensions
  if (Array.isArray(e.tensions) && e.tensions.length > 0) {
    merged.tensions = [...merged.tensions, ...e.tensions.map((t: any) => ({
      dimension_a: t.dimension_a || '',
      dimension_b: t.dimension_b || '',
      description: t.description || '',
      severity: t.severity || 'low',
      detected_at: new Date().toISOString(),
      resolved: false,
      resolution_note: null,
    }))];
  }

  // Profile summary — LLM-generated takes priority
  if (typeof e.profile_summary_text === 'string' && e.profile_summary_text.length > 20) {
    merged.profile_summary_text = e.profile_summary_text;
  }

  merged.last_updated = new Date().toISOString();
  return merged;
}

// ---------------------------------------------------------------------------
// Main entry point: compile full profile from onboarding answers
// ---------------------------------------------------------------------------

export async function compileFullProfile(
  userId: string,
  answers: Record<string, any>,
): Promise<ProfileData> {
  // Phase 1: Deterministic mapping
  const structured = compileStructuredProfile(userId, answers);

  // Phase 2: Collect free-text, call Mistral if any exist
  const freeTexts = collectFreeTextAnswers(answers);

  if (freeTexts) {
    try {
      const enrichments = await compileFreeTextWithMistral(structured, freeTexts);
      // Phase 3: Merge
      const merged = mergeEnrichments(structured, enrichments);

      // If no summary was generated, create a basic one
      if (!merged.profile_summary_text) {
        merged.profile_summary_text = generateFallbackSummary(merged);
      }

      return merged;
    } catch (err) {
      console.error('Free-text compilation failed, using structured only:', err);
      structured.profile_summary_text = generateFallbackSummary(structured);
      return structured;
    }
  }

  // No free-text — use structured profile only
  structured.profile_summary_text = generateFallbackSummary(structured);
  return structured;
}

// ---------------------------------------------------------------------------
// Fallback summary generator (no LLM needed)
// ---------------------------------------------------------------------------

function generateFallbackSummary(profile: ProfileData): string {
  const parts: string[] = [];

  // Name/identity
  const diet = profile.dietary.spectrum_label;
  if (diet) parts.push(`${diet.charAt(0).toUpperCase() + diet.slice(1)} eater`);

  // Location
  if (profile.location.city) parts.push(`based in ${profile.location.city}`);

  // Skill
  const skillLabels: Record<string, string> = {
    beginner: 'a beginning cook', home_cook: 'a capable home cook',
    confident: 'a confident cook', advanced: 'an advanced home cook',
    professional: 'a professional-level cook',
  };
  parts.push(skillLabels[profile.cooking.skill] || 'a home cook');

  // Cuisines
  const loved = profile.cuisine_affinities.affinities.filter(a => a.level === 'love').map(a => a.cuisine);
  if (loved.length > 0) {
    parts.push(`who loves ${loved.slice(0, 3).join(', ')} cuisine${loved.length > 1 ? 's' : ''}`);
  }

  // Adventurousness
  if (profile.adventurousness.dining_score >= 7) {
    parts.push('and enjoys exploring new food experiences');
  } else if (profile.adventurousness.dining_score <= 3) {
    parts.push('who prefers familiar favourites');
  }

  return parts.join(', ').replace(/^./, c => c.toUpperCase()) + '.';
}
