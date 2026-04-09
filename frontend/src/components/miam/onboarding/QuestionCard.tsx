import { useState, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { MessageSquare } from 'lucide-react';
import type { OnboardingQuestion } from '../../../data/onboardingQuestions';

/* ------------------------------------------------------------------ */
/*  Chip                                                                */
/* ------------------------------------------------------------------ */
function Chip({
  label,
  selected,
  onToggle,
}: {
  label: string;
  selected: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      onClick={onToggle}
      className="px-4 py-2.5 rounded-xl text-[14px] font-medium transition-all duration-200"
      style={{
        background: selected ? 'rgba(212, 168, 85, 0.15)' : '#1E1E1E',
        border: `1px solid ${selected ? 'rgba(212, 168, 85, 0.3)' : '#2A2A2A'}`,
        color: selected ? '#D4A855' : '#A5A29A',
      }}
      data-testid={`chip-${label.replace(/\s+/g, '-').toLowerCase()}`}
    >
      {label}
    </button>
  );
}

/* ------------------------------------------------------------------ */
/*  Slider                                                               */
/* ------------------------------------------------------------------ */
function SliderInput({
  label,
  min,
  max,
  leftLabel,
  rightLabel,
  value,
  onChange,
}: {
  label: string;
  min: number;
  max: number;
  leftLabel: string;
  rightLabel: string;
  value: number;
  onChange: (v: number) => void;
}) {
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <div className="mb-5">
      <div className="flex justify-between items-center mb-2">
        <span className="text-[15px] font-medium" style={{ color: '#F0EDE8' }}>{label}</span>
        <span className="text-xs tabular-nums" style={{ color: '#706D65' }}>{value}</span>
      </div>
      <div className="relative">
        <input
          type="range"
          min={min}
          max={max}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="w-full h-1.5 rounded-full appearance-none cursor-pointer"
          style={{
            background: `linear-gradient(to right, #D4A855 0%, #D4A855 ${pct}%, #2A2A2A ${pct}%, #2A2A2A 100%)`,
          }}
          data-testid={`slider-${label.replace(/\s+/g, '-').toLowerCase()}`}
        />
      </div>
      <div className="flex justify-between mt-1.5">
        <span className="text-[13px]" style={{ color: '#9A8E78' }}>{leftLabel}</span>
        <span className="text-[13px]" style={{ color: '#9A8E78' }}>{rightLabel}</span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Ranked Sort (tiered chips)                                           */
/* ------------------------------------------------------------------ */
function RankedSort({
  chipOptions,
  value,
  onChange,
}: {
  chipOptions: string[];
  value: Record<string, string>; // chip → tier
  onChange: (v: Record<string, string>) => void;
}) {
  const tiers = ['Love', 'Like', 'Meh', 'Skip'];
  const tierColors: Record<string, string> = {
    Love: '#D4A855',
    Like: '#B89A50',
    Meh: '#706D65',
    Skip: '#4A4740',
  };

  const cycleTier = (chip: string) => {
    const currentTier = value[chip];
    if (!currentTier) {
      onChange({ ...value, [chip]: 'Love' });
    } else {
      const idx = tiers.indexOf(currentTier);
      if (idx === tiers.length - 1) {
        const newVal = { ...value };
        delete newVal[chip];
        onChange(newVal);
      } else {
        const next = tiers[(idx + 1) % tiers.length];
        onChange({ ...value, [chip]: next });
      }
    }
  };

  return (
    <div>
      <div className="flex gap-2 mb-3 flex-wrap">
        {tiers.map((tier) => (
          <span
            key={tier}
            className="text-xs px-2 py-0.5 rounded-full"
            style={{
              background: `${tierColors[tier]}20`,
              color: tierColors[tier],
              border: `1px solid ${tierColors[tier]}30`,
            }}
          >
            {tier}
          </span>
        ))}
        <span className="text-xs px-2 py-0.5 rounded-full" style={{ color: '#A5A29A' }}>
          Tap to cycle
        </span>
      </div>
      <div className="flex flex-wrap gap-2">
        {chipOptions.map((chip) => {
          const tier = value[chip];
          const color = tier ? tierColors[tier] : undefined;
          return (
            <button
              key={chip}
              onClick={() => cycleTier(chip)}
              className="px-4 py-2.5 rounded-xl text-[14px] font-medium transition-all duration-200"
              style={{
                background: color ? `${color}20` : '#1E1E1E',
                border: `1px solid ${color ? `${color}40` : '#2A2A2A'}`,
                color: color || '#A5A29A',
              }}
              data-testid={`ranked-${chip.replace(/\s+/g, '-').toLowerCase()}`}
            >
              {chip}
              {tier && (
                <span className="ml-1.5 text-xs opacity-60">{tier}</span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  FreeText Collapsible                                                 */
/* ------------------------------------------------------------------ */
function FreeTextSection({
  placeholder,
  value,
  onChange,
}: {
  placeholder?: string;
  value: string;
  onChange: (v: string) => void;
}) {
  const [isOpen, setIsOpen] = useState(!!value);

  return (
    <div className="mt-5 pt-4 border-t" style={{ borderColor: '#2A2A2A' }}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2.5 w-full text-left transition-colors duration-200"
        data-testid="freetext-toggle"
      >
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
          style={{ background: isOpen ? 'rgba(212,168,85,0.15)' : '#1E1E1E' }}
        >
          <MessageSquare size={16} style={{ color: isOpen ? '#D4A855' : '#9A8E78' }} />
        </div>
        <span
          className="text-[15px] font-medium"
          style={{ color: isOpen ? '#D4A855' : '#9A8E78' }}
        >
          Or tell me in your own words...
        </span>
      </button>
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.25, 0.1, 0.25, 1] }}
            className="overflow-hidden"
          >
            <textarea
              value={value}
              onChange={(e) => onChange(e.target.value)}
              placeholder={placeholder || 'Type anything...'}
              rows={3}
              autoFocus
              className="w-full mt-3 px-4 py-3 rounded-xl text-[15px] outline-none resize-none"
              style={{
                background: '#1E1E1E',
                border: '1px solid rgba(212,168,85,0.2)',
                color: '#F0EDE8',
              }}
              data-testid="freetext-input"
            />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  QuestionCard (main export)                                           */
/* ------------------------------------------------------------------ */
export default function QuestionCard({
  question,
  value,
  onChange,
  onContinue,
  canContinue,
}: {
  question: OnboardingQuestion;
  value: any;
  onChange: (v: any) => void;
  onContinue: (answerAreaRect: DOMRect | null) => void;
  canContinue: boolean;
}) {
  const answerAreaRef = useRef<HTMLDivElement>(null);

  // We store { selection: ..., freetext: '...' } for questions that have both
  const getSelection = () => {
    if (value && typeof value === 'object' && 'selection' in value) return value.selection;
    return value;
  };
  const getFreetext = () => {
    if (value && typeof value === 'object' && 'freetext' in value) return value.freetext || '';
    return '';
  };
  const updateSelection = (sel: any) => {
    onChange({ selection: sel, freetext: getFreetext() });
  };
  const updateFreetext = (ft: string) => {
    onChange({ selection: getSelection(), freetext: ft });
  };
  
  const handleContinue = useCallback(() => {
    const rect = answerAreaRef.current?.getBoundingClientRect() ?? null;
    onContinue(rect);
  }, [onContinue]);

  // Multi-chips
  const renderMultiChips = () => {
    const selected: string[] = getSelection() || [];
    const opts = question.options || [];
    
    // Check if options are grouped
    if (opts.length > 0 && typeof opts[0] === 'object' && 'group' in (opts[0] as any)) {
      const groups = opts as { group: string; items: string[] }[];
      return (
        <div>
          {groups.map((group) => (
            <div key={group.group} className="mb-4">
              <h3 className="text-sm font-medium uppercase tracking-wider mb-2" style={{ color: '#A5A29A' }}>
                {group.group}
              </h3>
              <div className="flex flex-wrap gap-2">
                {group.items.map((item) => (
                  <Chip
                    key={item}
                    label={item}
                    selected={selected.includes(item)}
                    onToggle={() => {
                      const newVal = selected.includes(item)
                        ? selected.filter((s) => s !== item)
                        : [...selected, item];
                      updateSelection(newVal);
                    }}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      );
    }

    // Flat chips
    const flatOpts = opts as string[];
    return (
      <div className="flex flex-wrap gap-2">
        {flatOpts.map((opt) => (
          <Chip
            key={opt}
            label={opt}
            selected={selected.includes(opt)}
            onToggle={() => {
              const newVal = selected.includes(opt)
                ? selected.filter((s) => s !== opt)
                : [...selected, opt];
              updateSelection(newVal);
            }}
          />
        ))}
      </div>
    );
  };

  // Single chip
  const renderSingleChip = () => {
    const selected: string = getSelection() || '';
    const opts = (question.options || []) as string[];
    return (
      <div className="flex flex-wrap gap-2">
        {opts.map((opt) => (
          <Chip
            key={opt}
            label={opt}
            selected={selected === opt}
            onToggle={() => updateSelection(opt === selected ? '' : opt)}
          />
        ))}
      </div>
    );
  };

  // Sliders
  const renderSliders = () => {
    const sliderValues: Record<string, number> = getSelection() || {};
    return (
      <div>
        {(question.sliders || []).map((s) => (
          <SliderInput
            key={s.label}
            {...s}
            value={sliderValues[s.label] ?? s.defaultValue ?? Math.round((s.min + s.max) / 2)}
            onChange={(v) => updateSelection({ ...sliderValues, [s.label]: v })}
          />
        ))}
      </div>
    );
  };

  // Text input
  const renderTextInput = () => {
    return (
      <textarea
        value={getSelection() || ''}
        onChange={(e) => updateSelection(e.target.value)}
        placeholder={question.freeTextPlaceholder || 'Type anything...'}
        rows={4}
        className="w-full px-4 py-3 rounded-xl text-sm outline-none resize-none"
        style={{
          background: '#1E1E1E',
          border: '1px solid #2A2A2A',
          color: '#F0EDE8',
        }}
        data-testid="text-input"
      />
    );
  };

  // Ranked sort
  const renderRankedSort = () => {
    return (
      <RankedSort
        chipOptions={question.chipOptions || []}
        value={getSelection() || {}}
        onChange={updateSelection}
      />
    );
  };

  // Combined: chips + sliders (or sliders + chips)
  const renderCombined = () => {
    const combinedValue = getSelection() || { chips: question.inputType === 'combined' && question.options ? '' : [], sliders: {}, extraChips: [] };
    
    return (
      <div>
        {/* Single/multi select chips from options */}
        {question.options && (
          <div className="mb-5">
            <div className="flex flex-wrap gap-2">
              {(question.options as string[]).map((opt) => {
                const isSingleSelect = question.id === 'q6' || question.id === 'q12';
                const isSelected = isSingleSelect
                  ? combinedValue.chips === opt
                  : (combinedValue.chips || []).includes?.(opt);
                return (
                  <Chip
                    key={opt}
                    label={opt}
                    selected={isSelected}
                    onToggle={() => {
                      if (isSingleSelect) {
                        updateSelection({ ...combinedValue, chips: combinedValue.chips === opt ? '' : opt });
                      } else {
                        const arr = combinedValue.chips || [];
                        const newChips = arr.includes(opt) ? arr.filter((s: string) => s !== opt) : [...arr, opt];
                        updateSelection({ ...combinedValue, chips: newChips });
                      }
                    }}
                  />
                );
              })}
            </div>
          </div>
        )}

        {/* Sliders */}
        {question.sliders && question.sliders.length > 0 && (
          <div className="mb-4">
            {question.sliders.map((s) => (
              <SliderInput
                key={s.label}
                {...s}
                value={combinedValue.sliders?.[s.label] ?? s.defaultValue ?? Math.round((s.min + s.max) / 2)}
                onChange={(v) =>
                  updateSelection({
                    ...combinedValue,
                    sliders: { ...combinedValue.sliders, [s.label]: v },
                  })
                }
              />
            ))}
          </div>
        )}

        {/* Extra chipOptions */}
        {question.chipOptions && (
          <div>
            <div className="flex flex-wrap gap-2">
              {question.chipOptions.map((opt) => {
                const extraChips: string[] = combinedValue.extraChips || [];
                return (
                  <Chip
                    key={opt}
                    label={opt}
                    selected={extraChips.includes(opt)}
                    onToggle={() => {
                      const newArr = extraChips.includes(opt)
                        ? extraChips.filter((s) => s !== opt)
                        : [...extraChips, opt];
                      updateSelection({ ...combinedValue, extraChips: newArr });
                    }}
                  />
                );
              })}
            </div>
          </div>
        )}
      </div>
    );
  };

  const renderInput = () => {
    switch (question.inputType) {
      case 'multi-chips': return renderMultiChips();
      case 'single-chip': return renderSingleChip();
      case 'sliders': return renderSliders();
      case 'text-input': return renderTextInput();
      case 'ranked-sort': return renderRankedSort();
      case 'combined': return renderCombined();
      default: return null;
    }
  };

  // For text-input questions, we don't show a separate freetext section
  const showFreeText = question.inputType !== 'text-input';

  return (
    <motion.div
      initial={{ opacity: 0, y: 40 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 30 }}
      transition={{ duration: 0.35, ease: [0.25, 0.1, 0.25, 1] }}
      className="flex flex-col min-h-0" style={{ flex: '1 1 0' }}
    >
      {/* Header */}
      <div className="pt-2 pb-1 px-1 flex-shrink-0">
        <span className="text-sm font-medium uppercase tracking-wider" style={{ color: '#9A8E78' }}>
          {question.screenTitle}
        </span>
        <h2 className="text-xl font-semibold mt-1.5" style={{ color: '#F0EDE8' }}>
          {question.questionText}
        </h2>
        <p className="text-[15px] mt-1.5 leading-relaxed" style={{ color: '#9A8E78' }}>
          {question.helperText}
        </p>
      </div>

      {/* Answer area — scrollable */}
      <div ref={answerAreaRef} className="flex-1 overflow-y-auto hide-scrollbar pt-3 pb-2 px-1 min-h-0">
        {renderInput()}
        
        {/* Free text section */}
        {showFreeText && (
          <FreeTextSection
            placeholder={question.freeTextPlaceholder}
            value={getFreetext()}
            onChange={updateFreetext}
          />
        )}
      </div>

      {/* Continue button — always visible, never clipped */}
      <div className="flex-shrink-0 pt-3 pb-2 px-1">
        <button
          onClick={handleContinue}
          disabled={!canContinue}
          className="w-full h-12 rounded-xl text-sm font-semibold flex items-center justify-center gap-2 transition-all duration-200 active:scale-[0.98]"
          style={{
            background: '#D4A855',
            color: '#141414',
            opacity: canContinue ? 1 : 0.6,
          }}
          data-testid="onboarding-continue"
        >
          Continue
        </button>
      </div>
    </motion.div>
  );
}
