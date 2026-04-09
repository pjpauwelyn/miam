/**
 * scoring.ts — Client-side recipe match scoring from user profile.
 * Pure utility, no React, no async — runs in-memory on every recipe load.
 */

import type { RecipeDocument, UserProfile } from './api';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getCurrentSeason(): string {
  const month = new Date().getMonth();
  if (month >= 2 && month <= 4) return 'spring';
  if (month >= 5 && month <= 7) return 'summer';
  if (month >= 8 && month <= 10) return 'autumn';
  return 'winter';
}

const AFFINITY_LEVEL_MAP: Record<string, number> = {
  love: 1.0,
  like: 0.7,
  neutral: 0.4,
  dislike: 0.1,
};
const AFFINITY_DEFAULT = 0.35;

const SKILL_MAP: Record<string, number> = {
  beginner: 1,
  intermediate: 2,
  advanced: 3,
};

// ---------------------------------------------------------------------------
// A. Cuisine affinity — 35 pts max
// ---------------------------------------------------------------------------

function scoreCuisine(recipe: RecipeDocument, profile: UserProfile): number {
  if (!recipe.cuisine_tags || recipe.cuisine_tags.length === 0) return AFFINITY_DEFAULT * 35;
  let best = AFFINITY_DEFAULT;
  for (const tag of recipe.cuisine_tags) {
    const tagLower = tag.toLowerCase();
    for (const aff of profile.cuisine_affinities) {
      const affLower = aff.cuisine.toLowerCase();
      if (tagLower.includes(affLower) || affLower.includes(tagLower)) {
        const level = AFFINITY_LEVEL_MAP[aff.level] ?? AFFINITY_DEFAULT;
        if (level > best) best = level;
      }
    }
  }
  return Math.round(best * 35);
}

// ---------------------------------------------------------------------------
// B. Dietary compatibility — 25 pts max (plus restriction penalty)
// ---------------------------------------------------------------------------

function scoreDietary(recipe: RecipeDocument, profile: UserProfile): number {
  const flags = recipe.dietary_flags || {};
  let points = 0;

  switch (profile.dietary_spectrum) {
    case 'vegan':
      if (flags.is_vegan) points = 25;
      else if (flags.vegan_if_substituted) points = 12;
      else points = 0;
      break;
    case 'vegetarian':
      if (flags.is_vegetarian || flags.is_vegan) points = 25;
      else if (flags.vegan_if_substituted) points = 12;
      else points = 0;
      break;
    case 'pescatarian':
      if (flags.is_pescatarian_ok || flags.is_vegan || flags.is_vegetarian) points = 25;
      else points = 0;
      break;
    default: // omnivore or unknown
      points = 25;
      break;
  }

  // Hard-stop restriction checks
  let penalty = 0;
  for (const restriction of profile.restrictions) {
    const r = restriction.toLowerCase();
    if ((r.includes('nut') || r.includes('nut-free')) && flags.is_nut_free === false) {
      penalty += 15;
    }
    if ((r.includes('no pork') || r.includes('pork-free') || r.includes('halal')) && flags.contains_pork) {
      penalty += 15;
    }
    if ((r.includes('shellfish') || r.includes('shellfish-free')) && flags.contains_shellfish) {
      penalty += 15;
    }
    if ((r.includes('dairy') || r.includes('dairy-free')) && flags.is_dairy_free === false) {
      penalty += 15;
    }
    if ((r.includes('gluten') || r.includes('gluten-free')) && flags.is_gluten_free === false) {
      penalty += 15;
    }
  }

  return Math.max(0, points - penalty);
}

// ---------------------------------------------------------------------------
// C. Flavour overlap — 20 pts max
// ---------------------------------------------------------------------------

function scoreFlavour(recipe: RecipeDocument, profile: UserProfile): number {
  const tags = recipe.flavor_tags || [];
  if (tags.length === 0) return 0;
  let sum = 0;
  for (const tag of tags) {
    const key = Object.keys(profile.flavor_prefs).find(
      k => k.toLowerCase() === tag.toLowerCase()
    );
    if (key !== undefined) sum += profile.flavor_prefs[key];
  }
  const avg = sum / tags.length;
  return Math.round(avg * 20);
}

// ---------------------------------------------------------------------------
// D. Skill match — 10 pts max
// ---------------------------------------------------------------------------

function scoreSkill(recipe: RecipeDocument, profile: UserProfile): number {
  const difficulty = recipe.difficulty ?? 1; // 1–3
  const skill = SKILL_MAP[profile.cooking_skill] ?? 2;
  if (skill >= difficulty) return 10;
  if (skill === difficulty - 1) return 6;
  return 2;
}

// ---------------------------------------------------------------------------
// E. Season relevance — 10 pts max
// ---------------------------------------------------------------------------

function scoreSeason(recipe: RecipeDocument): number {
  const tags = recipe.season_tags;
  if (!tags || tags.length === 0) return 5; // neutral
  const season = getCurrentSeason();
  if (tags.some(t => t.toLowerCase().includes(season))) return 10;
  return 2;
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

/**
 * Score a single recipe for a given user profile.
 * Returns an integer 0–100.
 */
export function scoreRecipeForUser(
  recipe: RecipeDocument,
  profile: UserProfile,
): number {
  const cuisine = scoreCuisine(recipe, profile);
  const dietary = scoreDietary(recipe, profile);
  const flavour = scoreFlavour(recipe, profile);
  const skill = scoreSkill(recipe, profile);
  const season = scoreSeason(recipe);
  const total = cuisine + dietary + flavour + skill + season;
  return Math.min(100, Math.max(0, Math.round(total)));
}

/**
 * Score and enrich a list of recipes, returning them sorted by score descending.
 * Attaches `_matchScore` to each recipe object.
 * If profile is null, returns unsorted with `_matchScore: 0`.
 */
export function scoreAndEnrich(
  recipes: RecipeDocument[],
  profile: UserProfile | null,
): Array<RecipeDocument & { _matchScore: number }> {
  if (!profile) {
    return recipes.map(r => ({ ...r, _matchScore: 0 }));
  }
  return recipes
    .map(r => ({ ...r, _matchScore: scoreRecipeForUser(r, profile) }))
    .sort((a, b) => b._matchScore - a._matchScore);
}
