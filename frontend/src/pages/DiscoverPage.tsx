import { useState, useEffect, useRef } from 'react';
import { ChevronRight, Loader2 } from 'lucide-react';
import { motion } from 'framer-motion';
import { RecipeCard } from '../components/miam/RecipeCard';
import { useRecipeDetail } from '../App';
import {
  fetchForYouRecipes,
  fetchSeasonalRecipes,
  fetchRecipesByCuisine,
  fetchUserProfile,
  getCurrentUserId,
  recipeToUiFormat,
} from '../lib/api';
import type { UiRecipe, UserProfile } from '../lib/api';
import { scoreAndEnrich } from '../lib/scoring';

const discoverCategories = [
  'Japanese', 'Italian', 'Thai', 'Mexican', 'Indian', 'French', 'Korean', 'Mediterranean',
  'Middle Eastern', 'Chinese', 'Vietnamese', 'Greek', 'Spanish', 'Dutch',
];

export default function DiscoverPage() {
  const { openRecipe } = useRecipeDetail();
  const [forYou, setForYou] = useState<UiRecipe[]>([]);
  const [seasonal, setSeasonal] = useState<UiRecipe[]>([]);
  const [loading, setLoading] = useState(true);
  const [categoryResults, setCategoryResults] = useState<UiRecipe[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [categoryLoading, setCategoryLoading] = useState(false);

  // Cache the user profile so we don't re-fetch on every category click
  const profileRef = useRef<UserProfile | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [forYouData, seasonalData, profile] = await Promise.all([
          fetchForYouRecipes(8),
          fetchSeasonalRecipes(8),
          fetchUserProfile(getCurrentUserId()),
        ]);
        if (!cancelled) {
          profileRef.current = profile;
          const scoredForYou = scoreAndEnrich(forYouData, profile);
          const scoredSeasonal = scoreAndEnrich(seasonalData, profile);
          setForYou(scoredForYou.map(r => recipeToUiFormat(r, r._matchScore)));
          setSeasonal(scoredSeasonal.map(r => recipeToUiFormat(r, r._matchScore)));
        }
      } catch (err) {
        console.error('Failed to load discover data:', err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, []);

  const handleCategoryClick = async (category: string) => {
    if (selectedCategory === category) {
      setSelectedCategory(null);
      setCategoryResults([]);
      return;
    }
    setSelectedCategory(category);
    setCategoryLoading(true);
    try {
      const results = await fetchRecipesByCuisine(category, 8);
      const profile = profileRef.current;
      const scored = scoreAndEnrich(results, profile);
      setCategoryResults(scored.map(r => recipeToUiFormat(r, r._matchScore)));
    } catch (err) {
      console.error('Failed to fetch category:', err);
      setCategoryResults([]);
    } finally {
      setCategoryLoading(false);
    }
  };

  const sections = [
    { title: 'For You', items: forYou },
    { title: 'Seasonal Picks', items: seasonal },
  ];

  return (
    <div className="flex-1 overflow-y-auto hide-scrollbar relative">
      <motion.div
        className="px-5 pt-2 pb-4"
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35 }}
      >
        <h1 className="text-xl font-semibold" style={{ color: '#F0EDE8' }}>Discover</h1>
        <p className="text-xs mt-0.5" style={{ color: '#706D65' }}>Personalised picks from cuisines around the world</p>
      </motion.div>

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 size={24} className="animate-spin" style={{ color: '#D4A855' }} />
          <span className="ml-2 text-sm" style={{ color: '#A5A29A' }}>Loading recipes...</span>
        </div>
      ) : (
        <>
          {sections.map((section, sIdx) => (
            <motion.div
              key={section.title}
              className="mb-6"
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 + sIdx * 0.12, duration: 0.4, ease: [0.25, 0.1, 0.25, 1] }}
            >
              <div className="flex items-center justify-between px-5 mb-3">
                <h2 className="text-base font-semibold" style={{ color: '#F0EDE8' }}>{section.title}</h2>
                <motion.button
                  className="flex items-center gap-0.5 text-xs"
                  style={{ color: '#D4A855' }}
                  whileTap={{ scale: 0.95 }}
                  data-testid={`see-all-${section.title.replace(/\s/g, '-').toLowerCase()}`}
                >
                  See all <ChevronRight size={12} />
                </motion.button>
              </div>
              <div className="flex gap-3 overflow-x-auto hide-scrollbar px-5">
                {section.items.length > 0 ? section.items.map((recipe, i) => (
                  <RecipeCard
                    key={`${section.title}-${recipe.id}-${i}`}
                    recipe={recipe}
                    index={sIdx * 4 + i}
                    onClick={() => openRecipe(recipe)}
                  />
                )) : (
                  <p className="text-xs py-4" style={{ color: '#706D65' }}>No recipes found</p>
                )}
              </div>
            </motion.div>
          ))}
        </>
      )}

      {/* Try Something New — category pills */}
      <motion.div
        className="mb-6"
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.35, duration: 0.4, ease: [0.25, 0.1, 0.25, 1] }}
      >
        <div className="flex items-center justify-between px-5 mb-3">
          <h2 className="text-base font-semibold" style={{ color: '#F0EDE8' }}>Try Something New</h2>
        </div>
        <div className="flex gap-2 overflow-x-auto hide-scrollbar px-5 pb-1">
          {discoverCategories.map((cat, i) => (
            <motion.button
              key={cat}
              onClick={() => handleCategoryClick(cat)}
              className="flex-shrink-0 px-4 py-2 rounded-full text-xs font-medium"
              style={{
                background: selectedCategory === cat ? 'rgba(212,168,85,0.15)' : '#1E1E1E',
                border: `1px solid ${selectedCategory === cat ? 'rgba(212,168,85,0.3)' : '#2A2A2A'}`,
                color: selectedCategory === cat ? '#D4A855' : '#F0EDE8',
              }}
              initial={{ opacity: 0, x: 16 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.4 + i * 0.05, duration: 0.3 }}
              whileTap={{ scale: 0.94, background: 'rgba(212, 168, 85, 0.08)' }}
              data-testid={`category-${cat.toLowerCase()}`}
            >
              {cat}
            </motion.button>
          ))}
        </div>

        {/* Category results */}
        {selectedCategory && (
          <div className="px-5 mt-3">
            {categoryLoading ? (
              <div className="flex items-center gap-2 py-4">
                <Loader2 size={16} className="animate-spin" style={{ color: '#D4A855' }} />
                <span className="text-xs" style={{ color: '#A5A29A' }}>Loading {selectedCategory} recipes...</span>
              </div>
            ) : categoryResults.length > 0 ? (
              <div className="flex gap-3 overflow-x-auto hide-scrollbar pb-2">
                {categoryResults.map((recipe, i) => (
                  <RecipeCard
                    key={`cat-${recipe.id}-${i}`}
                    recipe={recipe}
                    index={i}
                    onClick={() => openRecipe(recipe)}
                  />
                ))}
              </div>
            ) : (
              <p className="text-xs py-4" style={{ color: '#706D65' }}>No {selectedCategory} recipes found</p>
            )}
          </div>
        )}
      </motion.div>
    </div>
  );
}
