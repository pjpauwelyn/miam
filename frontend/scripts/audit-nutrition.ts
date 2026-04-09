/**
 * audit-nutrition.ts
 *
 * Standalone dev-only script — NOT imported by app code.
 * Run: tsx frontend/scripts/audit-nutrition.ts
 *
 * Fetches all recipes from recipes_open and produces a JSON report
 * at frontend/scripts/nutrition-audit-report.json plus a stdout summary.
 */

import * as fs from 'fs';
import * as path from 'path';
import * as url from 'url';
import { config } from 'dotenv';

// Load .env from the repo root (or frontend/.env if it exists)
const __dirname = path.dirname(url.fileURLToPath(import.meta.url));
config({ path: path.resolve(__dirname, '../../.env') });
config({ path: path.resolve(__dirname, '../.env') }); // fallback

const SUPABASE_URL = process.env.VITE_SUPABASE_URL;
const SUPABASE_KEY = process.env.VITE_SUPABASE_KEY;

if (!SUPABASE_URL || !SUPABASE_KEY) {
  console.error('ERROR: VITE_SUPABASE_URL and VITE_SUPABASE_KEY must be set in .env');
  process.exit(1);
}

const SUPABASE_REST = `${SUPABASE_URL}/rest/v1`;

const headers = {
  apikey: SUPABASE_KEY,
  Authorization: `Bearer ${SUPABASE_KEY}`,
  'Content-Type': 'application/json',
};

interface NutritionPerServing {
  kcal?: number;
  protein_g?: number;
  fat_g?: number;
  saturated_fat_g?: number;
  carbs_g?: number;
  fiber_g?: number;
  sugar_g?: number;
  salt_g?: number;
}

const NUTRITION_FIELDS: (keyof NutritionPerServing)[] = [
  'kcal', 'protein_g', 'fat_g', 'saturated_fat_g',
  'carbs_g', 'fiber_g', 'sugar_g', 'salt_g',
];

interface RecipeRow {
  recipe_id: string;
  data: any;
}

async function fetchAllRecipes(): Promise<RecipeRow[]> {
  const PAGE_SIZE = 1000;
  const all: RecipeRow[] = [];
  let offset = 0;

  while (true) {
    const url = `${SUPABASE_REST}/recipes_open?select=recipe_id,data&limit=${PAGE_SIZE}&offset=${offset}&order=recipe_id`;
    const resp = await fetch(url, { headers });
    if (!resp.ok) throw new Error(`Supabase error ${resp.status}: ${await resp.text()}`);
    const rows: RecipeRow[] = await resp.json();
    all.push(...rows);
    if (rows.length < PAGE_SIZE) break;
    offset += PAGE_SIZE;
  }

  return all;
}

function getNutrition(data: any): NutritionPerServing | null {
  const d = typeof data === 'string' ? JSON.parse(data) : data;
  const nps = d?.nutrition_per_serving;
  if (!nps || typeof nps !== 'object') return null;
  if (Object.keys(nps).length === 0) return null;
  return nps as NutritionPerServing;
}

function stats(values: number[]) {
  if (values.length === 0) return { min: null, max: null, mean: null, count: 0 };
  const min = Math.min(...values);
  const max = Math.max(...values);
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  return { min, max, mean: +mean.toFixed(2), count: values.length };
}

async function main() {
  console.log('Fetching recipes from Supabase...');
  const rows = await fetchAllRecipes();
  console.log(`Fetched ${rows.length} recipes.\n`);

  const noNutrition: string[] = [];
  const partialNutrition: string[] = [];
  const fullNutrition: string[] = [];
  const outliers: { recipe_id: string; kcal: number; computed_kcal: number; diff_pct: number }[] = [];

  const kcalVals: number[] = [];
  const proteinVals: number[] = [];
  const carbsVals: number[] = [];
  const fatVals: number[] = [];

  for (const row of rows) {
    const nps = getNutrition(row.data);

    if (!nps) {
      noNutrition.push(row.recipe_id);
      continue;
    }

    const presentCount = NUTRITION_FIELDS.filter(f => nps[f] != null).length;

    if (presentCount === NUTRITION_FIELDS.length) {
      fullNutrition.push(row.recipe_id);
    } else {
      partialNutrition.push(row.recipe_id);
    }

    if (nps.kcal != null) kcalVals.push(nps.kcal);
    if (nps.protein_g != null) proteinVals.push(nps.protein_g);
    if (nps.carbs_g != null) carbsVals.push(nps.carbs_g);
    if (nps.fat_g != null) fatVals.push(nps.fat_g);

    // Outlier check: macro-derived kcal vs reported kcal
    if (nps.kcal != null && nps.protein_g != null && nps.carbs_g != null && nps.fat_g != null) {
      const computed = nps.protein_g * 4 + nps.carbs_g * 4 + nps.fat_g * 9;
      if (computed > 0) {
        const diffPct = Math.abs(nps.kcal - computed) / computed * 100;
        if (diffPct > 20) {
          outliers.push({
            recipe_id: row.recipe_id,
            kcal: nps.kcal,
            computed_kcal: +computed.toFixed(1),
            diff_pct: +diffPct.toFixed(1),
          });
        }
      }
    }
  }

  const report = {
    generated_at: new Date().toISOString(),
    total_recipes: rows.length,
    no_nutrition: { count: noNutrition.length, recipe_ids: noNutrition },
    partial_nutrition: { count: partialNutrition.length, recipe_ids: partialNutrition },
    full_nutrition: { count: fullNutrition.length, recipe_ids: fullNutrition },
    stats: {
      kcal: stats(kcalVals),
      protein_g: stats(proteinVals),
      carbs_g: stats(carbsVals),
      fat_g: stats(fatVals),
    },
    outliers: {
      count: outliers.length,
      threshold_pct: 20,
      items: outliers,
    },
  };

  const outPath = path.resolve(__dirname, 'nutrition-audit-report.json');
  fs.writeFileSync(outPath, JSON.stringify(report, null, 2));
  console.log(`Report written to: ${outPath}\n`);

  // Human-readable summary
  console.log('=== NUTRITION AUDIT REPORT ===');
  console.log(`Total recipes:            ${report.total_recipes}`);
  console.log(`  No nutrition data:      ${report.no_nutrition.count}`);
  console.log(`  Partial nutrition data: ${report.partial_nutrition.count}`);
  console.log(`  Full nutrition data:    ${report.full_nutrition.count}`);
  console.log('');
  console.log('Stats (for recipes with data):');
  console.log(`  kcal:      min=${report.stats.kcal.min}, max=${report.stats.kcal.max}, mean=${report.stats.kcal.mean} (n=${report.stats.kcal.count})`);
  console.log(`  protein_g: min=${report.stats.protein_g.min}, max=${report.stats.protein_g.max}, mean=${report.stats.protein_g.mean} (n=${report.stats.protein_g.count})`);
  console.log(`  carbs_g:   min=${report.stats.carbs_g.min}, max=${report.stats.carbs_g.max}, mean=${report.stats.carbs_g.mean} (n=${report.stats.carbs_g.count})`);
  console.log(`  fat_g:     min=${report.stats.fat_g.min}, max=${report.stats.fat_g.max}, mean=${report.stats.fat_g.mean} (n=${report.stats.fat_g.count})`);
  console.log('');
  console.log(`Outliers (macro kcal vs reported >20% off): ${report.outliers.count}`);
  if (report.outliers.items.length > 0) {
    for (const o of report.outliers.items) {
      console.log(`  ${o.recipe_id}: reported=${o.kcal} kcal, macro-derived=${o.computed_kcal} kcal, diff=${o.diff_pct}%`);
    }
  }
  console.log('==============================');
}

main().catch((err) => {
  console.error('Audit failed:', err);
  process.exit(1);
});
