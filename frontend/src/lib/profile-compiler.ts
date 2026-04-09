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
  if (Array.isArray(q1Sel) && q1Sel.length > 0) {
    const spectrumMap: Record<string, string> = {
      'I eat everything': 'omnivore',
      'No meat, but I eat fish': 'pescatarian',
      'Vegetarian': 'vegetarian',
      'Vegan': 'vegan',
      'Mostly plant-based, sometimes meat': 'flexitarian',
      'Halal': 'halal',
      'Kosher': 'kosher',
    };
    // If multiple, combine (e.g. "flexitarian" + "halal" → "flexitarian-halal")
    const mapped = q1Sel.map((s: string) => spectrumMap[s] || s.toLowerCase()).filter(Boolean);
    spectrumLabel = mapped.length === 1 ? mapped[0] : mapped.join('-');
  } else if (typeof q1Sel === 'string') {
    spectrumLabel = q1Sel.toLowerCase();
  }

  // --- q2: Restrictions ---
  const q2Sel = getChips(answers.q2);
  const hardStops: DietaryRestriction[] = [];
  const reasonMap: Record<string, string> = {
    'No pork': 'ethical', 'No beef': 'ethical', 'No red meat': 'preference',
    'No nuts': 'allergy', 'No shellfish': 'allergy', 'No eggs': 'allergy',
    'No soy': 'allergy', 'No fish': 'allergy',
    'No gluten (coeliac)': 'intolerance', 'No dairy (lactose)': 'intolerance',
    'No fructose': 'intolerance',
    'No MSG': 'preference', 'No nightshades': 'intolerance', 'No corn': 'allergy',
  };
  for (const item of q2Sel) {
    const label = item.replace(/^No /, '').replace(/ \(.*\)/, '').toLowerCase();
    hardStops.push({
      label,
      is_hard_stop: true,
      reason: reasonMap[item] || 'preference',
      confidence: 1.0,
    });
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
  const sweetSavoryRaw = q4Sliders['Sweet vs Savory'] ?? null;
  const lightRichRaw = q4Sliders['Light vs Rich'] ?? null;
  const simpleComplexRaw = q4Sliders['Simple vs Complex'] ?? null;

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

  // --- q5: Favourite ingredients → flavor/texture boosts ---
  const q5Chips = getChips(answers.q5);
  const favoriteIngredients: string[] = [...q5Chips];

  // Ingredient → dimension boosts
  const umamiIngredients = ['Garlic', 'Miso', 'Truffle', 'Mushrooms', 'Sesame'];
  const fattyIngredients = ['Butter', 'Cheese', 'Avocado', 'Olive oil', 'Coconut'];
  const spicyIngredients = ['Chili', 'Ginger'];
  const sweetIngredients = ['Honey', 'Chocolate'];
  const sourIngredients = ['Lemon'];

  for (const ing of q5Chips) {
    if (umamiIngredients.includes(ing) && (flavor.umami === null || flavor.umami < 7)) {
      flavor.umami = Math.min(10, (flavor.umami ?? 5) + 1.5);
    }
    if (fattyIngredients.includes(ing) && (flavor.fatty === null || flavor.fatty < 7)) {
      flavor.fatty = Math.min(10, (flavor.fatty ?? 5) + 1.0);
    }
    if (spicyIngredients.includes(ing) && (flavor.spicy === null || flavor.spicy < 7)) {
      flavor.spicy = Math.min(10, (flavor.spicy ?? 5) + 1.0);
    }
    if (sweetIngredients.includes(ing) && (flavor.sweet === null || flavor.sweet < 7)) {
      flavor.sweet = Math.min(10, (flavor.sweet ?? 5) + 1.0);
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

  // Texture defaults from ingredient choices
  const texture: ProfileData['texture'] = {
    crunchy: q5Chips.includes('Bacon') || q5Chips.includes('Sesame') ? 6.5 : null,
    creamy: fattyIngredients.some(i => q5Chips.includes(i)) ? 6.5 : null,
    soft: null,
    chewy: null,
    crispy: q5Chips.includes('Bacon') ? 7.0 : null,
    silky: q5Chips.includes('Avocado') || q5Chips.includes('Miso') ? 6.0 : null,
    chunky: null,
    meta: meta('optional', 0.4),
  };

  // --- q6: Cooking skill ---
  const q6Chips = getChips(answers.q6);
  const q6Sliders = getSliders(answers.q6);
  const skillMap: Record<string, string> = {
    'Just starting out': 'beginner',
    'I get by': 'home_cook',
    'Pretty confident': 'confident',
    'I know my way around': 'advanced',
    'Semi-pro level': 'professional',
  };
  let cookingSkill = 'home_cook';
  if (q6Chips.length > 0) {
    cookingSkill = skillMap[q6Chips[0]] || 'home_cook';
  }
  const weeknightMin = q6Sliders['Time on a weeknight'] ?? 30;

  // --- q7: Kitchen equipment ---
  const q7Chips = getChips(answers.q7);
  const q7Sliders = getSliders(answers.q7);
  const equipmentMap: Record<string, string> = {
    'Air fryer': 'air_fryer',
    'Instant Pot': 'pressure_cooker',
    'Slow cooker': 'pressure_cooker', // similar category
    'Wok': 'wok',
    'Grill': 'outdoor_grill',
    'Sous vide': 'sous_vide',
    'Blender': 'stand_mixer', // approximate
    'Food processor': 'food_processor',
    'Dutch oven': 'cast_iron',
    'Cast iron': 'cast_iron',
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
    'Quick & easy': ['efficient'],
    'Slow & mindful': ['cozy', 'classic'],
    'Social — cooking with friends': ['lively'],
    'Solo comfort meals': ['cozy'],
    'Meal prep warrior': [],
    'Fancy plating': ['trendy'],
    'Rustic & homey': ['classic', 'cozy'],
    'Street food energy': ['trendy', 'lively'],
  };
  const mealPrepInterest = q9Chips.includes('Meal prep warrior');
  const specialInterests: string[] = [];
  if (mealPrepInterest) specialInterests.push('meal_prep');
  if (q9Chips.includes('Fancy plating')) specialInterests.push('food_photography');

  for (const chip of q9Chips) {
    const boosts = vibeBoosts[chip] || [];
    for (const vibeLabel of boosts) {
      const v = defaultVibes.find(x => x.vibe === vibeLabel);
      if (v) { v.score = Math.min(10, v.score + 2.0); v.confidence = 0.7; }
    }
  }

  // --- q10: Adventurousness ---
  const q10Chips = getChips(answers.q10);
  let cookingAdventure = 5.0;
  let diningAdventure = 5.0;
  const adventureMap: Record<string, [number, number]> = {
    'I eat the same 10 things': [1.0, 1.0],
    'I like what I like': [3.0, 3.0],
    'Open to suggestions': [5.0, 5.0],
    'Love trying new stuff': [7.0, 7.0],
    'Will eat anything once': [6.0, 9.0],
    'Fermented foods? Yes': [7.0, 7.0],
    'The weirder the better': [9.0, 9.0],
  };
  for (const chip of q10Chips) {
    const [c, d] = adventureMap[chip] || [5, 5];
    cookingAdventure = Math.max(cookingAdventure, c);
    diningAdventure = Math.max(diningAdventure, d);
  }
  if (q10Chips.includes('Fermented foods? Yes')) {
    specialInterests.push('fermentation');
  }

  // --- q11: Nutrition ---
  const q11Sliders = getSliders(answers.q11);
  const calorieAwareness = q11Sliders['Calorie awareness'] ?? 30;
  const proteinFocus = q11Sliders['Protein focus'] ?? 40;
  const sugarIntake = q11Sliders['Sugar intake'] ?? 30;

  let nutritionLevel = 'none';
  if (calorieAwareness > 75) nutritionLevel = 'strict';
  else if (calorieAwareness > 50) nutritionLevel = 'moderate';
  else if (calorieAwareness > 25) nutritionLevel = 'light';

  const trackedDimensions: string[] = [];
  if (calorieAwareness > 50) trackedDimensions.push('calories');
  if (proteinFocus > 50) trackedDimensions.push('protein');
  if (sugarIntake > 50) trackedDimensions.push('sugar');

  // --- q12: Social eating ---
  // q12 is combined: chips = social context (single-select), extraChips = venue types
  const q12AllChips = getChips(answers.q12);
  const q12Sel = getSelection(answers.q12);
  // Extract the social context chip (from options, single-select)
  const socialOptions = ['Mostly alone', 'With my partner', '2-3 times a week with friends', 'I host often', 'Big family meals'];
  const venueOptions = ['Fine dining', 'Casual bistro', 'Street food', 'Fast casual', 'Food trucks', 'Cafés', 'Brunch spots', 'Late night'];
  const socialChip = q12AllChips.find(c => socialOptions.includes(c)) ||
    (q12Sel && typeof q12Sel === 'object' && typeof q12Sel.chips === 'string' ? q12Sel.chips : null);
  const venueChips = q12AllChips.filter(c => venueOptions.includes(c));
  let mealsOutPerWeek = 2.0;
  const socialOverrides: Record<string, [string, number]> = {
    'Mostly alone': ['solo', 0.5],
    'With my partner': ['couple', 1.5],
    '2-3 times a week with friends': ['group', 2.5],
    'I host often': ['group', 1.0],
    'Big family meals': ['family', 1.0],
  };
  if (socialChip && socialOverrides[socialChip]) {
    const [ctx, meals] = socialOverrides[socialChip];
    socialContext = ctx;
    mealsOutPerWeek = meals;
  }

  // Venue chips → vibe boosts
  const venueVibeMap: Record<string, string> = {
    'Fine dining': 'romantic', 'Casual bistro': 'classic',
    'Street food': 'trendy', 'Fast casual': 'efficient',
    'Food trucks': 'trendy', 'Cafés': 'cozy',
    'Brunch spots': 'lively', 'Late night': 'hidden_gem',
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
  const mealPriorities = q13Chips.map((c: string) => c.toLowerCase().replace(/ /g, '_'));
  if (q13Chips.includes('Meal prep') && !specialInterests.includes('meal_prep')) {
    specialInterests.push('meal_prep');
  }
  if (q13Chips.includes('Weekend feasts')) {
    cookingAdventure = Math.max(cookingAdventure, 6.0);
  }

  // --- q14: Values (sliders) ---
  const q14Sliders = getSliders(answers.q14);
  const budgetPriority = q14Sliders['Budget priority'] ?? 40;
  const organicPref = q14Sliders['Organic preference'] ?? 30;
  const localSourcing = q14Sliders['Local sourcing'] ?? 40;

  // Map budget slider to approximate EUR/meal
  let homePerMealEur: number | null = null;
  if (budgetPriority <= 25) homePerMealEur = 4.0;
  else if (budgetPriority <= 50) homePerMealEur = 7.0;
  else if (budgetPriority <= 75) homePerMealEur = 12.0;
  else homePerMealEur = 18.0;

  const sustainabilityScore = Math.round(((organicPref + localSourcing) / 200) * 10 * 10) / 10;
  const seasonalScore = Math.round((localSourcing / 100) * 10 * 10) / 10;

  // --- q15: Food interests ---
  const q15Chips = getChips(answers.q15);
  const interestNormalise: Record<string, string> = {
    'Fermentation': 'fermentation', 'Baking & pastry': 'baking',
    'BBQ & grilling': 'bbq', 'Food science': 'food_science',
    'Food photography': 'food_photography', 'Foraging': 'foraging',
    'Wine pairing': 'wine_pairing', 'Coffee & tea': 'coffee_tea',
    'Cocktails': 'cocktails', 'Meal planning': 'meal_prep',
    'Zero waste cooking': 'zero_waste', 'Cultural food history': 'food_history',
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
    'Home cook': { style: 'short_list' },
    'Foodie explorer': { style: 'wide_selection', adventureBoost: 8.0 },
    'Health optimizer': { style: 'short_list', nutritionBoost: 'moderate' },
    'Busy parent': { style: 'short_list', socialOverride: 'family' },
    'Student on a budget': { style: 'short_list', budgetOverride: 3.5 },
    'Aspiring chef': { style: 'wide_selection', adventureBoost: 8.0 },
    'Picky eater': { style: 'one_best' },
    'Social entertainer': { style: 'wide_selection', socialOverride: 'group' },
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
      soft_stops: [],
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
      weekend_minutes: 90,
      meta: meta('core', 0.8),
    },

    budget: {
      home_per_meal_eur: homePerMealEur,
      out_per_meal_eur: null,
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
