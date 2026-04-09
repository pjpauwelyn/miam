/**
 * miam API service layer
 *
 * Talks to:
 *  - FastAPI backend for pipeline queries (POST /api/eat-in/query)
 *  - Supabase REST API for direct data reads/writes
 *
 * Tables used:
 *  - recipes_open     — enriched recipe documents (read)
 *  - recipes          — mock recipes fallback (read)
 *  - user_profiles    — user taste profiles (read/write)
 *  - user_saved_recipes — bookmarked recipes (read/write)
 *  - sessions         — conversation sessions (read)
 *  - messages         — conversation messages (read)
 *  - activity_events  — user activity log (write)
 */

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL || 'https://rscviujiflpsujukwgts.supabase.co';
const SUPABASE_KEY = import.meta.env.VITE_SUPABASE_KEY || '';

const SUPABASE_REST = `${SUPABASE_URL}/rest/v1`;

const supaHeaders = (extra?: Record<string, string>): Record<string, string> => ({
  apikey: SUPABASE_KEY,
  Authorization: `Bearer ${SUPABASE_KEY}`,
  'Content-Type': 'application/json',
  Prefer: 'return=representation',
  ...extra,
});

// Auth-aware user ID — falls back to Lena for unauthenticated access
import { supabase } from './supabase';

export function getCurrentUserId(): string {
  const session = (supabase as any).auth?.session?.();
  // supabase-js v2 stores session in memory; use synchronous access
  const stored = localStorage.getItem('sb-rscviujiflpsujukwgts-auth-token');
  if (stored) {
    try {
      const parsed = JSON.parse(stored);
      if (parsed?.user?.id) return parsed.user.id;
    } catch { /* ignore */ }
  }
  return '050d1112-d2bd-4672-8058-0c10ab75a907'; // Lena fallback
}

/** @deprecated Use getCurrentUserId() instead */
export const DEFAULT_USER_ID = '050d1112-d2bd-4672-8058-0c10ab75a907';

// ---------------------------------------------------------------------------
// Types matching backend RecipeDocument + pipeline response
// ---------------------------------------------------------------------------

export interface RecipeIngredient {
  name: string;
  amount?: string;
  unit?: string;
  notes?: string;
  is_optional?: boolean;
  substitutions?: string[];
}

export interface RecipeStep {
  step_number: number;
  instruction: string;
  duration_min?: number;
  technique_tags?: string[];
}

export interface NutritionPerServing {
  kcal?: number;
  protein_g?: number;
  fat_g?: number;
  saturated_fat_g?: number;
  carbs_g?: number;
  fiber_g?: number;
  sugar_g?: number;
  salt_g?: number;
}

export interface DietaryFlags {
  is_vegan?: boolean;
  is_vegetarian?: boolean;
  is_pescatarian_ok?: boolean;
  is_dairy_free?: boolean;
  is_gluten_free?: boolean;
  is_nut_free?: boolean;
  is_halal_ok?: boolean;
  contains_pork?: boolean;
  contains_shellfish?: boolean;
  contains_alcohol?: boolean;
  vegan_if_substituted?: boolean;
  gluten_free_if_substituted?: boolean;
}

export interface RecipeDocument {
  recipe_id: string;
  title: string;
  title_en?: string;
  cuisine_tags: string[];
  region_tag?: string;
  description: string;
  ingredients: RecipeIngredient[];
  steps: RecipeStep[];
  time_prep_min?: number;
  time_cook_min?: number;
  time_total_min?: number;
  serves?: number;
  difficulty?: number;
  flavor_tags: string[];
  texture_tags: string[];
  dietary_tags: string[];
  dietary_flags: DietaryFlags;
  nutrition_per_serving: NutritionPerServing;
  season_tags?: string[];
  occasion_tags?: string[];
  course_tags?: string[];
  image_placeholder?: string;
  source_type?: string;
  wine_pairing_notes?: string;
  tips?: string[];
}

export interface PipelineResult {
  recipe_id: string;
  title: string;
  match_score: number;
  match_tier: 'full_match' | 'close_match' | 'stretch_pick';
  time_total_min?: number;
  difficulty?: number;
  serves?: number;
  nutrition_summary?: string;
  key_technique?: string;
  missing_ingredients: string[];
  substitutions: string[];
  warnings: string[];
}

export interface PipelineResponse {
  session_id: string;
  message_id: string;
  response: {
    generated_text: string;
    results: PipelineResult[];
    warnings: string[];
  };
  debug: {
    latency_ms: number;
    stages_completed: string[];
    pipeline_status: string;
  };
}

// ---------------------------------------------------------------------------
// User profile types (from user_profiles.profile_data)
// ---------------------------------------------------------------------------

export interface UserProfile {
  user_id: string;
  profile_status: string;
  display_name: string;
  dietary_spectrum: string;
  summary: string;
  cuisine_affinities: { cuisine: string; level: string }[];
  restrictions: string[];
  flavor_prefs: Record<string, number>;
  texture_prefs: Record<string, number>;
  cooking_skill: string;
  location_city: string;
}

// ---------------------------------------------------------------------------
// Session / history types
// ---------------------------------------------------------------------------

export interface SessionSummary {
  session_id: string;
  mode: string;
  started_at: string;
  ended_at?: string;
  query_count: number;
  first_user_message?: string;
}

// ---------------------------------------------------------------------------
// Supabase direct reads — Recipes
// ---------------------------------------------------------------------------

/**
 * Fetch up to `limit` recipes ordered deterministically by recipe_id.
 * Supabase REST caps a single request at 1000 rows; callers that previously
 * passed 500 are safe since 500 < 1000. The default is raised to 1000 so
 * helpers like fetchSeasonalRecipes and fetchRecipesByCuisine see the full
 * table without a separate pagination loop.
 */
export async function fetchRecipes(limit = 1000): Promise<RecipeDocument[]> {
  const url = `${SUPABASE_REST}/recipes_open?select=recipe_id,data&limit=${limit}&order=recipe_id`;
  const resp = await fetch(url, { headers: supaHeaders() });
  if (!resp.ok) throw new Error(`Failed to fetch recipes: ${resp.status}`);
  const rows: { recipe_id: string; data: any }[] = await resp.json();
  return rows.map((r) => normaliseRecipe(r));
}

export async function fetchRecipesByCuisine(cuisine: string, limit = 10): Promise<RecipeDocument[]> {
  try {
    const all = await fetchRecipes(1000);
    return all.filter(r => r.cuisine_tags.some(c => c.toLowerCase().includes(cuisine.toLowerCase()))).slice(0, limit);
  } catch {
    return [];
  }
}

export async function fetchRecipeById(recipeId: string): Promise<RecipeDocument | null> {
  const url = `${SUPABASE_REST}/recipes_open?recipe_id=eq.${recipeId}&select=recipe_id,data&limit=1`;
  const resp = await fetch(url, { headers: supaHeaders() });
  if (!resp.ok) return null;
  const rows: { recipe_id: string; data: any }[] = await resp.json();
  if (rows.length === 0) {
    // Try mock table
    const url2 = `${SUPABASE_REST}/recipes?recipe_id=eq.${recipeId}&select=recipe_id,data&limit=1`;
    const resp2 = await fetch(url2, { headers: supaHeaders() });
    if (!resp2.ok) return null;
    const rows2: { recipe_id: string; data: any }[] = await resp2.json();
    return rows2.length > 0 ? normaliseRecipe(rows2[0]) : null;
  }
  return normaliseRecipe(rows[0]);
}

/**
 * Fetch a randomised selection of recipes for the "For You" feed.
 *
 * Strategy:
 *  1. Query the table count so we know the true population size.
 *  2. Pick a random offset capped so we always get at least (limit * 10) rows
 *     back (or fall back to offset 0 for small tables).
 *  3. Fetch limit * 10 rows starting at that offset, ordered by recipe_id for
 *     deterministic paging.
 *  4. Shuffle client-side and return the first `limit` results.
 *
 * This gives every recipe in the table a fair chance of appearing over time
 * without fetching the entire table on every load.
 */
export async function fetchForYouRecipes(limit = 8): Promise<RecipeDocument[]> {
  const sampleSize = limit * 10;

  // Step 1: get total count via Prefer: count=exact
  let totalCount = sampleSize; // safe fallback
  try {
    const countResp = await fetch(
      `${SUPABASE_REST}/recipes_open?select=count`,
      { headers: supaHeaders({ Prefer: 'count=exact' }) },
    );
    if (countResp.ok) {
      const contentRange = countResp.headers.get('content-range'); // e.g. "0-0/342"
      const match = contentRange?.match(/\/(\d+)$/);
      if (match) totalCount = parseInt(match[1], 10);
    }
  } catch { /* use fallback */ }

  // Step 2: random offset — ensure we can still retrieve sampleSize rows
  const maxOffset = Math.max(0, totalCount - sampleSize);
  const offset = Math.floor(Math.random() * (maxOffset + 1));

  // Step 3: fetch the window
  const url = `${SUPABASE_REST}/recipes_open?select=recipe_id,data&order=recipe_id&limit=${sampleSize}&offset=${offset}`;
  const resp = await fetch(url, { headers: supaHeaders() });
  if (!resp.ok) return [];
  const rows: { recipe_id: string; data: any }[] = await resp.json();

  // Step 4: client-side shuffle, then slice
  const recipes = rows.map(normaliseRecipe);
  const shuffled = recipes.sort(() => Math.random() - 0.5);
  return shuffled.slice(0, limit);
}

export async function fetchSeasonalRecipes(limit = 8): Promise<RecipeDocument[]> {
  const month = new Date().getMonth();
  const season = month >= 2 && month <= 4 ? 'spring' : month >= 5 && month <= 7 ? 'summer' : month >= 8 && month <= 10 ? 'autumn' : 'winter';
  const all = await fetchRecipes(1000);
  const seasonal = all.filter(r =>
    r.season_tags?.some(t => t.toLowerCase().includes(season))
  );
  if (seasonal.length >= limit) return seasonal.sort(() => Math.random() - 0.5).slice(0, limit);
  return [...seasonal, ...all.filter(r => !seasonal.includes(r)).sort(() => Math.random() - 0.5)].slice(0, limit);
}

// ---------------------------------------------------------------------------
// Supabase — User Profile
// ---------------------------------------------------------------------------

export async function fetchUserProfile(userId: string = DEFAULT_USER_ID): Promise<UserProfile | null> {
  const url = `${SUPABASE_REST}/user_profiles?user_id=eq.${userId}&select=*&limit=1`;
  const resp = await fetch(url, { headers: supaHeaders() });
  if (!resp.ok) return null;
  const rows: any[] = await resp.json();
  if (rows.length === 0) return null;
  const row = rows[0];
  const pd = row.profile_data || {};
  return {
    user_id: row.user_id,
    profile_status: row.profile_status,
    display_name: pd.profile_summary_text?.match(/^(\w+)/)?.[1] || 'User',
    dietary_spectrum: pd.dietary?.spectrum_label || '',
    summary: pd.profile_summary_text || '',
    cuisine_affinities: (pd.cuisine_affinities?.affinities || []).map((a: any) => ({
      cuisine: a.cuisine,
      level: a.level,
    })),
    restrictions: [
      ...(pd.dietary?.hard_stops || []).map((s: any) => s.label),
      ...(pd.dietary?.soft_stops || []).map((s: any) => s.label),
    ],
    flavor_prefs: pd.flavor || {},
    texture_prefs: pd.texture || {},
    cooking_skill: pd.cooking?.skill || '',
    location_city: pd.location?.city || '',
  };
}

export async function saveOnboardingProfile(
  userId: string,
  answers: Record<string, any>,
  onProgress?: (phase: string) => void,
): Promise<boolean> {
  try {
    // Import profile compiler (async to keep bundle split)
    const { compileFullProfile } = await import('./profile-compiler');

    // Phase 1 + 2 + 3: compile full personal ontology
    onProgress?.('Compiling your taste profile...');
    const profileData = await compileFullProfile(userId, answers);

    // Upsert to Supabase
    onProgress?.('Saving to your profile...');
    const resp = await fetch(`${SUPABASE_REST}/user_profiles`, {
      method: 'POST',
      headers: supaHeaders({ Prefer: 'resolution=merge-duplicates,return=representation' }),
      body: JSON.stringify({
        user_id: userId,
        profile_status: 'complete',
        profile_data: profileData,
      }),
    });
    return resp.ok;
  } catch (err) {
    console.error('Profile compilation/save failed:', err);
    return false;
  }
}

// ---------------------------------------------------------------------------
// Supabase — Saved recipes (bookmarks)
// ---------------------------------------------------------------------------

export async function fetchSavedRecipeIds(userId: string = DEFAULT_USER_ID): Promise<string[]> {
  const url = `${SUPABASE_REST}/user_saved_recipes?user_id=eq.${userId}&select=recipe_id&order=saved_at.desc`;
  const resp = await fetch(url, { headers: supaHeaders() });
  if (!resp.ok) return [];
  const rows: { recipe_id: string }[] = await resp.json();
  return rows.map(r => r.recipe_id);
}

export async function saveRecipe(recipeId: string, userId: string = DEFAULT_USER_ID): Promise<boolean> {
  const resp = await fetch(`${SUPABASE_REST}/user_saved_recipes`, {
    method: 'POST',
    headers: supaHeaders({ Prefer: 'resolution=merge-duplicates,return=representation' }),
    body: JSON.stringify({
      user_id: userId,
      recipe_id: recipeId,
      saved_at: new Date().toISOString(),
    }),
  });
  return resp.ok;
}

export async function unsaveRecipe(recipeId: string, userId: string = DEFAULT_USER_ID): Promise<boolean> {
  const resp = await fetch(
    `${SUPABASE_REST}/user_saved_recipes?user_id=eq.${userId}&recipe_id=eq.${recipeId}`,
    { method: 'DELETE', headers: supaHeaders() },
  );
  return resp.ok;
}

export async function fetchSavedRecipes(userId: string = DEFAULT_USER_ID): Promise<RecipeDocument[]> {
  const ids = await fetchSavedRecipeIds(userId);
  if (ids.length === 0) return [];
  // Fetch full recipe data for each saved ID
  const promises = ids.slice(0, 30).map(id => fetchRecipeById(id));
  const results = await Promise.all(promises);
  return results.filter(Boolean) as RecipeDocument[];
}

// ---------------------------------------------------------------------------
// Supabase — Session history
// ---------------------------------------------------------------------------

export async function fetchSessionHistory(userId: string = DEFAULT_USER_ID): Promise<SessionSummary[]> {
  const url = `${SUPABASE_REST}/sessions?user_id=eq.${userId}&select=session_id,mode,started_at,ended_at,query_count&order=started_at.desc&limit=30`;
  const resp = await fetch(url, { headers: supaHeaders() });
  if (!resp.ok) return [];
  const sessions: any[] = await resp.json();

  // Fetch first user message for each session
  const enriched = await Promise.all(
    sessions.map(async (s) => {
      let firstMsg = '';
      try {
        const msgUrl = `${SUPABASE_REST}/messages?session_id=eq.${s.session_id}&role=eq.user&select=content&order=created_at&limit=1`;
        const msgResp = await fetch(msgUrl, { headers: supaHeaders() });
        if (msgResp.ok) {
          const msgs: any[] = await msgResp.json();
          if (msgs.length > 0) firstMsg = msgs[0].content;
        }
      } catch { /* ignore */ }
      return {
        session_id: s.session_id,
        mode: s.mode,
        started_at: s.started_at,
        ended_at: s.ended_at,
        query_count: s.query_count || 0,
        first_user_message: firstMsg,
      };
    })
  );
  return enriched;
}

// ---------------------------------------------------------------------------
// Supabase — Activity events (for My Recipes / custom recipes)
// ---------------------------------------------------------------------------

export async function logActivity(
  userId: string,
  type: string,
  referenceId?: string,
  note?: string,
): Promise<boolean> {
  try {
    const resp = await fetch(`${SUPABASE_REST}/activity_events`, {
      method: 'POST',
      headers: supaHeaders(),
      body: JSON.stringify({
        activity_id: crypto.randomUUID(),
        user_id: userId,
        activity_type: type,
        reference_id: referenceId || null,
        note: note || null,
        is_public: false,
        created_at: new Date().toISOString(),
      }),
    });
    return resp.ok;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Pipeline query (calls FastAPI backend)
// ---------------------------------------------------------------------------

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || '';

export async function queryPipeline(
  query: string,
  userId: string = getCurrentUserId(),
  sessionId?: string,
): Promise<PipelineResponse> {
  if (!BACKEND_URL) {
    throw new Error('BACKEND_NOT_CONFIGURED');
  }
  const url = `${BACKEND_URL}/api/eat-in/query`;
  try {
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: userId,
        query,
        session_id: sessionId || null,
      }),
    });
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`Pipeline error ${resp.status}: ${text}`);
    }
    return resp.json();
  } catch (err: any) {
    if (err.message === 'BACKEND_NOT_CONFIGURED') throw err;
    throw new Error('BACKEND_UNAVAILABLE');
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Parse a plain ingredient string such as "200g flour", "1 tbsp olive oil",
 * "1/2 cup sugar", "1 1/2 tsp vanilla", or "salt to taste" into a structured
 * RecipeIngredient object.
 *
 * Regex groups:
 *  [1] quantity  — digits, fractions, mixed numbers   (optional)
 *  [2] unit      — g | kg | ml | l | tsp | tbsp | … (optional)
 *  [3] name      — everything that follows
 *
 * Fractions ("1/2", "1 1/2") are kept as-is in the amount string so the UI
 * can display them verbatim; no decimal conversion is applied.
 */
function parseIngredientString(raw: string): RecipeIngredient {
  const trimmed = raw.trim();

  const INGREDIENT_RE =
    /^(\d[\d./\s]*)?\s*(g|kg|ml|l|tsp|tbsp|cups?|oz|lb|cloves?|slices?|handful|pinch|bunch|sprigs?|pieces?)?\s+(.+)$/i;

  const match = trimmed.match(INGREDIENT_RE);

  if (!match) {
    // No quantity or unit detected — treat the whole string as the name
    return { name: trimmed, amount: '', unit: '' };
  }

  const rawAmount = (match[1] ?? '').trim();
  const rawUnit   = (match[2] ?? '').trim();
  const name      = (match[3] ?? '').trim();

  // If neither quantity nor unit was captured, the regex matched only because
  // of the trailing name group — fall back to name-only.
  if (!rawAmount && !rawUnit) {
    return { name: trimmed, amount: '', unit: '' };
  }

  return {
    name,
    amount: rawAmount || '',
    unit:   rawUnit   || '',
  };
}

function normaliseRecipe(row: { recipe_id: string; data: any }): RecipeDocument {
  const d = typeof row.data === 'string' ? JSON.parse(row.data) : row.data;
  return {
    recipe_id: row.recipe_id,
    title: d.title_en || d.title || 'Untitled',
    title_en: d.title_en,
    cuisine_tags: d.cuisine_tags || [],
    region_tag: d.region_tag,
    description: d.description || '',
    ingredients: (d.ingredients || []).map((i: any) =>
      typeof i === 'string' ? parseIngredientString(i) : i
    ),
    steps: (d.steps || []).map((s: any, idx: number) =>
      typeof s === 'string'
        ? { step_number: idx + 1, instruction: s, technique_tags: [] }
        : { ...s, step_number: s.step_number || idx + 1 }
    ),
    time_prep_min: d.time_prep_min,
    time_cook_min: d.time_cook_min,
    time_total_min: d.time_total_min,
    serves: d.serves,
    difficulty: d.difficulty,
    flavor_tags: d.flavor_tags || [],
    texture_tags: d.texture_tags || [],
    dietary_tags: d.dietary_tags || [],
    dietary_flags: d.dietary_flags || {},
    nutrition_per_serving: d.nutrition_per_serving || {},
    season_tags: d.season_tags || [],
    occasion_tags: d.occasion_tags || [],
    course_tags: d.course_tags || [],
    image_placeholder: d.image_placeholder,
    source_type: d.source_type,
    wine_pairing_notes: d.wine_pairing_notes,
    tips: d.tips || [],
  };
}

// Helper: convert RecipeDocument to the shape the existing UI components expect
export function recipeToUiFormat(r: RecipeDocument) {
  return {
    id: r.recipe_id,
    title: r.title,
    cuisine: r.cuisine_tags,
    dietary: r.dietary_tags,
    time: r.time_total_min || 0,
    difficulty: r.difficulty || 1,
    matchScore: 0,
    description: r.description,
    servings: r.serves || 2,
    ingredients: r.ingredients.map(i => ({
      name: i.name,
      amount: i.amount ?? '',
      unit: i.unit || '',
      substitution: i.substitutions?.[0],
    })),
    steps: r.steps.map(s => ({
      number: s.step_number,
      instruction: s.instruction,
      techniqueTags: s.technique_tags || [],
    })),
    nutrition: {
      calories: r.nutrition_per_serving.kcal || 0,
      protein: r.nutrition_per_serving.protein_g || 0,
      carbs: r.nutrition_per_serving.carbs_g || 0,
      fat: r.nutrition_per_serving.fat_g || 0,
      fibre: r.nutrition_per_serving.fiber_g || 0,
      saturatedFat: r.nutrition_per_serving.saturated_fat_g || 0,
      sugar: r.nutrition_per_serving.sugar_g || 0,
      salt: r.nutrition_per_serving.salt_g || 0,
    },
    flavourTags: r.flavor_tags,
    textureTags: r.texture_tags,
    dietaryFlags: r.dietary_flags,
    winePairingNotes: r.wine_pairing_notes,
    tips: r.tips,
    regionTag: r.region_tag,
    seasonTags: r.season_tags,
    occasionTags: r.occasion_tags,
    courseTags: r.course_tags,
    sourceType: r.source_type,
  };
}

export type UiRecipe = ReturnType<typeof recipeToUiFormat>;
