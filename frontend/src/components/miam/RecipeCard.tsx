import { useState } from 'react';
import { Clock, Flame } from 'lucide-react';
import { motion } from 'framer-motion';
import type { UiRecipe } from '../../lib/api';

interface RecipeCardProps {
  recipe: UiRecipe;
  compact?: boolean;
  onClick?: () => void;
  index?: number;
}

function DifficultyDots({ level }: { level: number }) {
  return (
    <div className="flex gap-0.5 items-center">
      {[1, 2, 3].map((i) => (
        <motion.div
          key={i}
          className="w-1.5 h-1.5 rounded-full"
          style={{ background: i <= level ? '#D4A855' : '#333333' }}
          initial={{ scale: 0 }}
          animate={{ scale: 1 }}
          transition={{ delay: i * 0.05, type: 'spring', stiffness: 500, damping: 25 }}
        />
      ))}
    </div>
  );
}

export function RecipeCard({ recipe, compact = false, onClick, index = 0 }: RecipeCardProps) {
  const [imgError, setImgError] = useState(false);

  if (compact) {
    return (
      <motion.button
        onClick={onClick}
        className="w-full text-left rounded-xl p-3"
        style={{
          background: '#1E1E1E',
          border: '1px solid #2A2A2A',
        }}
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: index * 0.08, duration: 0.3, ease: [0.25, 0.1, 0.25, 1] }}
        whileTap={{ scale: 0.98 }}
        data-testid={`recipe-card-${recipe.id}`}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            <h4 className="text-[13px] font-medium leading-tight truncate" style={{ color: '#F0EDE8' }}>
              {recipe.title}
            </h4>
            <div className="flex flex-wrap gap-1 mt-1.5">
              {recipe.cuisine.map((c) => (
                <span
                  key={c}
                  className="text-[10px] font-medium uppercase px-1.5 py-0.5 rounded"
                  style={{ background: 'rgba(139, 58, 74, 0.2)', color: '#C45A70' }}
                >
                  {c}
                </span>
              ))}
              {recipe.dietary.slice(0, 2).map((d) => (
                <span
                  key={d}
                  className="text-[10px] font-medium uppercase px-1.5 py-0.5 rounded"
                  style={{ background: 'rgba(74, 139, 92, 0.2)', color: '#62AD76' }}
                >
                  {d}
                </span>
              ))}
            </div>
            <div className="flex items-center gap-3 mt-2">
              <div className="flex items-center gap-1">
                <Clock size={11} style={{ color: '#A5A29A' }} />
                <span className="text-[11px]" style={{ color: '#A5A29A' }}>{recipe.time} min</span>
              </div>
              <DifficultyDots level={recipe.difficulty} />
            </div>
          </div>
          {/* Match score badge with pulse */}
          {recipe.matchScore > 0 && (
            <motion.div
              className="w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0"
              style={{
                background: 'rgba(212, 168, 85, 0.12)',
                border: '1.5px solid rgba(212, 168, 85, 0.3)',
              }}
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              transition={{ delay: index * 0.08 + 0.15, type: 'spring', stiffness: 400, damping: 20 }}
            >
              <span className="text-[11px] font-semibold" style={{ color: '#D4A855' }}>
                {recipe.matchScore}%
              </span>
            </motion.div>
          )}
        </div>
      </motion.button>
    );
  }

  const showImage = !!recipe.imageUrl && !imgError;

  // Full card for Discover screen
  return (
    <motion.button
      onClick={onClick}
      className="w-[180px] flex-shrink-0 text-left rounded-xl overflow-hidden"
      style={{
        background: '#1E1E1E',
        border: '1px solid #2A2A2A',
      }}
      initial={{ opacity: 0, y: 12, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ delay: index * 0.06, duration: 0.35, ease: [0.25, 0.1, 0.25, 1] }}
      whileTap={{ scale: 0.97 }}
      whileHover={{ y: -2 }}
      data-testid={`recipe-card-full-${recipe.id}`}
    >
      {showImage ? (
        <div className="h-24 relative overflow-hidden">
          <img
            src={recipe.imageUrl!}
            alt={recipe.title}
            className="absolute inset-0 w-full h-full"
            style={{ objectFit: 'cover', borderRadius: 0 }}
            loading="lazy"
            onError={() => setImgError(true)}
          />
          {recipe.regionTag && (
            <div
              className="px-1.5 py-0.5 rounded text-[10px] font-medium absolute top-2 left-2"
              style={{ background: 'rgba(0,0,0,0.45)', color: '#A5A29A' }}
            >
              {recipe.regionTag}
            </div>
          )}
          {recipe.matchScore > 0 && (
            <div
              className="px-1.5 py-0.5 rounded text-[10px] font-semibold absolute bottom-2 left-2"
              style={{ background: 'rgba(212, 168, 85, 0.85)', color: '#141414' }}
            >
              {recipe.matchScore}% match
            </div>
          )}
        </div>
      ) : (
        <div
          className="h-24 relative flex items-end p-2"
          style={{
            background: `linear-gradient(135deg, #262626 0%, #1E1E1E 100%)`,
          }}
        >
          <Flame size={40} style={{ color: 'rgba(212, 168, 85, 0.08)', position: 'absolute', top: 12, right: 12 }} />
          {recipe.regionTag && (
            <div
              className="px-1.5 py-0.5 rounded text-[10px] font-medium absolute top-2 left-2"
              style={{ background: 'rgba(165,162,154,0.1)', color: '#A5A29A' }}
            >
              {recipe.regionTag}
            </div>
          )}
          {recipe.matchScore > 0 && (
            <div
              className="px-1.5 py-0.5 rounded text-[10px] font-semibold"
              style={{ background: 'rgba(212, 168, 85, 0.15)', color: '#D4A855' }}
            >
              {recipe.matchScore}% match
            </div>
          )}
        </div>
      )}
      <div className="p-3">
        <h4 className="text-[13px] font-medium leading-tight line-clamp-2" style={{ color: '#F0EDE8' }}>
          {recipe.title}
        </h4>
        <div className="flex flex-wrap gap-1 mt-1.5">
          {recipe.cuisine.slice(0, 1).map((c) => (
            <span
              key={c}
              className="text-[10px] font-medium uppercase px-1.5 py-0.5 rounded"
              style={{ background: 'rgba(139, 58, 74, 0.2)', color: '#C45A70' }}
            >
              {c}
            </span>
          ))}
          {recipe.dietary.slice(0, 1).map((d) => (
            <span
              key={d}
              className="text-[10px] font-medium uppercase px-1.5 py-0.5 rounded"
              style={{ background: 'rgba(74, 139, 92, 0.2)', color: '#62AD76' }}
            >
              {d}
            </span>
          ))}
        </div>
        <div className="flex items-center gap-2 mt-2">
          <Clock size={11} style={{ color: '#A5A29A' }} />
          <span className="text-[11px]" style={{ color: '#A5A29A' }}>{recipe.time} min</span>
          <DifficultyDots level={recipe.difficulty} />
        </div>
      </div>
    </motion.button>
  );
}
