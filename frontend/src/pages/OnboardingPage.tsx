import { useState, useCallback, useRef } from 'react';
import { useLocation } from 'wouter';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronRight, Sparkles, Loader2 } from 'lucide-react';
import { MiamLogo } from '../components/miam/MiamLogo';
import GravityCanvas from '../components/miam/onboarding/GravityCanvas';
import type { OrbitEntity, PendingBurst } from '../components/miam/onboarding/GravityCanvas';
import { getIconUrl } from '../components/miam/onboarding/OrbitLabels';
import QuestionCard from '../components/miam/onboarding/QuestionCard';
import { onboardingQuestions } from '../data/onboardingQuestions';
import { saveOnboardingProfile, logActivity } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import spaceBg from '@assets/space-bg.png';

const TOTAL_STEPS = onboardingQuestions.length; // 17

export default function OnboardingPage({ onComplete }: { onComplete?: () => void } = {}) {
  const { user } = useAuth();
  const [currentStep, setCurrentStep] = useState(0); // 0=intro, 1-17=questions, 18=completion, 19=review
  const [entities, setEntities] = useState<OrbitEntity[]>([]);
  const [answers, setAnswers] = useState<Record<string, any>>({});
  const [pendingBurst, setPendingBurst] = useState<PendingBurst | null>(null);
  const [transitioning, setTransitioning] = useState(false);
  const [newEntityId, setNewEntityId] = useState<string | null>(null);
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savePhase, setSavePhase] = useState('');
  const [, navigate] = useLocation();
  const containerRef = useRef<HTMLDivElement>(null);

  const progressPct = currentStep === 0 ? 0 : Math.min((currentStep / TOTAL_STEPS) * 100, 100);

  const isInteractive = currentStep === TOTAL_STEPS + 1 || currentStep === TOTAL_STEPS + 2;

  const handleContinue = useCallback(
    (answerAreaRect: DOMRect | null) => {
      if (transitioning) return;
      setTransitioning(true);

      const questionIndex = currentStep - 1;
      const question = onboardingQuestions[questionIndex];

      if (question) {
        const containerRect = containerRef.current?.getBoundingClientRect();
        let fromX = 0.5;
        let fromY = 0.6;

        if (answerAreaRect && containerRect) {
          fromX = (answerAreaRect.left + answerAreaRect.width / 2 - containerRect.left) / containerRect.width;
          fromY = (answerAreaRect.top + answerAreaRect.height / 2 - containerRect.top) / containerRect.height;
        }

        const burst: PendingBurst = {
          id: `burst-${question.id}-${Date.now()}`,
          fromX,
          fromY,
          targetOrbitRadius: question.entityMapping.orbitRadius,
          color: question.entityMapping.color,
          label: question.entityMapping.label,
        };
        setPendingBurst(burst);

        // Build answer summary for tooltip
        const answer = answers[question.id];
        let answerSummary = '';
        if (answer) {
          const sel = answer?.selection !== undefined ? answer.selection : answer;
          if (Array.isArray(sel)) {
            answerSummary = sel.slice(0, 3).join(', ');
            if (sel.length > 3) answerSummary += ` +${sel.length - 3}`;
          } else if (typeof sel === 'string' && sel.length > 0) {
            answerSummary = sel.slice(0, 60);
          } else if (typeof sel === 'object' && sel !== null) {
            if (sel.chips) {
              answerSummary = typeof sel.chips === 'string' ? sel.chips : (sel.chips as string[]).slice(0, 2).join(', ');
            }
            const keys = Object.keys(sel);
            if (keys.length > 0 && !sel.chips && !sel.sliders && !sel.extraChips) {
              const firstVal = sel[keys[0]];
              if (typeof firstVal === 'string') {
                const loves = keys.filter(k => sel[k] === 'Love');
                const likes = keys.filter(k => sel[k] === 'Like');
                if (loves.length > 0) answerSummary = `Love: ${loves.slice(0, 3).join(', ')}`;
                else if (likes.length > 0) answerSummary = `Like: ${likes.slice(0, 3).join(', ')}`;
                else answerSummary = `${keys.length} cuisines rated`;
              } else if (typeof firstVal === 'number') {
                answerSummary = keys.map(k => `${k}: ${sel[k]}`).slice(0, 2).join(', ');
              }
            }
          }
          if (answer?.freetext) {
            answerSummary = answerSummary ? `${answerSummary} — "${answer.freetext.slice(0, 40)}"` : answer.freetext.slice(0, 60);
          }
        }

        const scaledRadius = question.entityMapping.orbitRadius * 0.65;
        const newEntity: OrbitEntity = {
          id: question.id,
          label: question.entityMapping.label,
          color: question.entityMapping.color,
          orbitRadius: scaledRadius,
          orbitSpeed: 0.06 + (1 / scaledRadius) * 0.04,
          orbitPhase: Math.random() * Math.PI * 2,
          size: 1,
          iconUrl: getIconUrl(question.entityMapping.icon),
          answerSummary: answerSummary || 'No answer',
        };
        setEntities((prev) => [...prev, newEntity]);
        setNewEntityId(question.id);
      }

      setTimeout(() => {
        setCurrentStep((prev) => prev + 1);
        setTransitioning(false);
        setTimeout(() => setNewEntityId(null), 1500);
      }, 600);
    },
    [currentStep, transitioning, answers]
  );

  const handleBurstComplete = useCallback(() => {}, []);

  const handleIntroStart = () => {
    setCurrentStep(1);
  };

  // Save onboarding answers to Supabase, then navigate home
  const handleFinish = async () => {
    setSaving(true);
    setSavePhase('Compiling your taste profile...');
    try {
      const userId = user?.id || '';
      await saveOnboardingProfile(userId, answers, (phase) => setSavePhase(phase));
      await logActivity(userId, 'onboarding_complete', undefined, `Completed ${Object.keys(answers).length} questions`);
    } catch {
      // Silent fail — profile save is best-effort
    } finally {
      setSaving(false);
      setSavePhase('');
      if (onComplete) {
        onComplete();
      } else {
        navigate('/');
      }
    }
  };

  const handleEntitySelect = useCallback((id: string) => {
    setSelectedEntityId((prev) => (prev === id ? null : id));
  }, []);

  const currentQuestion = currentStep >= 1 && currentStep <= TOTAL_STEPS
    ? onboardingQuestions[currentStep - 1]
    : null;

  const selectedEntity = entities.find((e) => e.id === selectedEntityId);

  return (
    <div
      ref={containerRef}
      className="relative flex flex-col overflow-hidden"
      style={{
        height: '100dvh',
        backgroundImage: `url(${spaceBg})`,
        backgroundSize: 'cover',
        backgroundPosition: 'center top',
      }}
    >
      {/* R3F Canvas behind everything */}
      <GravityCanvas
        entities={entities}
        pendingBurst={pendingBurst}
        onBurstComplete={handleBurstComplete}
        newEntityId={newEntityId}
        interactive={isInteractive}
        selectedId={selectedEntityId}
        onSelect={handleEntitySelect}
      />

      {/* Progress bar */}
      {currentStep > 0 && currentStep <= TOTAL_STEPS && (
        <div
          className="absolute top-0 left-0 right-0 h-[2px] z-20"
          style={{ background: 'rgba(42, 42, 42, 0.5)' }}
        >
          <motion.div
            className="h-full"
            style={{ background: '#D4A855' }}
            initial={{ width: `${((currentStep - 1) / TOTAL_STEPS) * 100}%` }}
            animate={{ width: `${progressPct}%` }}
            transition={{ duration: 0.4, ease: 'easeOut' }}
          />
        </div>
      )}

      {/* Content layer */}
      <div className="relative z-10 flex flex-col h-full">
        <AnimatePresence mode="wait">
          {/* -------- INTRO SCREEN -------- */}
          {currentStep === 0 && (
            <motion.div
              key="intro"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0, y: -20 }}
              transition={{ duration: 0.4 }}
              className="flex flex-col items-center justify-center text-center px-8"
              style={{ height: '100%', paddingTop: 'env(safe-area-inset-top, 0)', paddingBottom: 'env(safe-area-inset-bottom, 0)' }}
            >
              <motion.div
                initial={{ scale: 0.8, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ delay: 0.2, duration: 0.5, ease: [0.25, 0.1, 0.25, 1] }}
                className="mb-8"
              >
                <MiamLogo size={88} />
              </motion.div>

              <motion.h1
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.4, duration: 0.5 }}
                className="text-2xl font-semibold mb-3"
                style={{ color: '#F0EDE8' }}
              >
                Let's get to know{'\n'}each other.
              </motion.h1>

              <motion.p
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.55, duration: 0.5 }}
                className="text-[15px] leading-relaxed max-w-[280px] mb-12"
                style={{ color: '#9A8E78' }}
              >
                A few quick questions so miam can learn your taste.
                Your answers become your flavor constellation.
              </motion.p>

              <motion.button
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.7, duration: 0.5 }}
                onClick={handleIntroStart}
                className="h-12 px-8 rounded-xl text-sm font-semibold flex items-center justify-center gap-2 active:scale-[0.97] transition-transform"
                style={{ background: '#D4A855', color: '#141414' }}
                data-testid="onboarding-start"
              >
                Let's go
                <ChevronRight size={16} />
              </motion.button>
            </motion.div>
          )}

          {/* -------- QUESTION SCREENS -------- */}
          {currentQuestion && (
            <motion.div
              key={`q-${currentStep}`}
              className="flex flex-col"
              style={{ height: '100%' }}
            >
              <div
                className="flex items-center justify-center flex-shrink-0"
                style={{ paddingTop: 'max(env(safe-area-inset-top, 12px), 12px)', paddingBottom: 4 }}
              >
                <MiamLogo size={28} />
              </div>

              <div className="flex-shrink-0" style={{ height: 60 }} />

              <div
                className="flex-1 flex flex-col px-5 min-h-0"
                style={{
                  background: 'linear-gradient(to bottom, rgba(14,14,14,0.1) 0%, rgba(14,14,14,0.45) 6%, rgba(14,14,14,0.7) 18%)',
                  borderRadius: '20px 20px 0 0',
                }}
              >
                <div className="pt-4 pb-1 flex items-center justify-between flex-shrink-0">
                  <span className="text-sm tabular-nums" style={{ color: '#9A8E78' }}>
                    {currentStep} / {TOTAL_STEPS}
                  </span>
                  {currentStep > 1 && (
                    <button
                      onClick={() => {
                        if (!transitioning) {
                          setCurrentStep((prev) => prev - 1);
                        }
                      }}
                      className="text-sm font-medium"
                      style={{ color: '#9A8E78' }}
                      data-testid="onboarding-back"
                    >
                      Back
                    </button>
                  )}
                </div>

                <QuestionCard
                  question={currentQuestion}
                  value={answers[currentQuestion.id]}
                  onChange={(v) => setAnswers((prev) => ({ ...prev, [currentQuestion.id]: v }))}
                  onContinue={handleContinue}
                  canContinue={!transitioning}
                />
              </div>

              <div className="flex-shrink-0" style={{ height: 'env(safe-area-inset-bottom, 0)', background: 'rgba(14,14,14,0.7)' }} />
            </motion.div>
          )}

          {/* -------- COMPLETION SCREEN -------- */}
          {currentStep === TOTAL_STEPS + 1 && (
            <motion.div
              key="completion"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.5 }}
              className="flex flex-col h-full"
            >
              <div className="flex-1 relative" />

              <div
                className="px-8 pb-8 pt-12"
                style={{
                  background: 'linear-gradient(to bottom, transparent, rgba(10,10,10,0.85) 30%)',
                }}
              >
                <div className="flex flex-col items-center text-center">
                  <motion.div
                    initial={{ scale: 0.5, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    transition={{ delay: 0.2, type: 'spring', stiffness: 200, damping: 20 }}
                    className="mb-4"
                  >
                    <div
                      className="w-14 h-14 rounded-full flex items-center justify-center"
                      style={{ background: 'rgba(212, 168, 85, 0.15)', border: '1px solid rgba(212, 168, 85, 0.3)' }}
                    >
                      <Sparkles size={24} style={{ color: '#D4A855' }} />
                    </div>
                  </motion.div>

                  <motion.h1
                    initial={{ opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.4, duration: 0.5 }}
                    className="text-xl font-semibold mb-2"
                    style={{ color: '#F0EDE8' }}
                  >
                    Your constellation is ready.
                  </motion.h1>

                  <motion.p
                    initial={{ opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.6, duration: 0.5 }}
                    className="text-[15px] leading-relaxed max-w-[260px] mb-3"
                    style={{ color: '#9A8E78' }}
                  >
                    Drag to explore your taste identity.
                    Tap any icon to see what you told us.
                  </motion.p>

                  {/* Tooltip for selected entity */}
                  <AnimatePresence>
                    {selectedEntity && (
                      <motion.div
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: 8 }}
                        className="mb-3 px-4 py-2.5 rounded-xl max-w-[280px]"
                        style={{
                          background: 'rgba(30, 30, 30, 0.95)',
                          border: `1px solid ${selectedEntity.color}40`,
                        }}
                      >
                        <div className="text-xs font-semibold mb-0.5" style={{ color: selectedEntity.color }}>
                          {selectedEntity.label}
                        </div>
                        <div className="text-xs" style={{ color: '#A5A29A' }}>
                          {selectedEntity.answerSummary || 'No answer given'}
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>

                  <motion.button
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: 1.0 }}
                    onClick={() => {
                      setSelectedEntityId(null);
                      setCurrentStep(TOTAL_STEPS + 2);
                    }}
                    className="h-12 px-8 rounded-xl text-sm font-semibold flex items-center justify-center gap-2 active:scale-[0.97] transition-transform"
                    style={{ background: '#D4A855', color: '#141414' }}
                    data-testid="onboarding-review"
                  >
                    See my profile
                    <ChevronRight size={16} />
                  </motion.button>
                </div>
              </div>
            </motion.div>
          )}

          {/* -------- PROFILE REVIEW SCREEN -------- */}
          {currentStep === TOTAL_STEPS + 2 && (
            <motion.div
              key="review"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.5 }}
              className="flex flex-col h-full"
            >
              <div className="flex-1 relative" />

              <div className="px-5 pb-6">
                <motion.div
                  initial={{ opacity: 0, y: 30 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.3, duration: 0.6 }}
                  className="rounded-2xl p-5"
                  style={{
                    background: 'rgba(20, 20, 20, 0.92)',
                    backdropFilter: 'blur(20px)',
                    WebkitBackdropFilter: 'blur(20px)',
                    border: '1px solid rgba(42, 42, 42, 0.5)',
                  }}
                >
                  <h2 className="text-lg font-semibold mb-1" style={{ color: '#F0EDE8' }}>
                    Here's how we see you
                  </h2>
                  <p className="text-[15px] mb-4" style={{ color: '#9A8E78' }}>
                    Your flavor constellation — {entities.length} dimensions mapped
                  </p>

                  <div className="flex flex-wrap gap-1.5 mb-5">
                    {entities.map((entity) => (
                      <span
                        key={entity.id}
                        className="px-3 py-1.5 rounded-lg text-[13px] font-medium"
                        style={{
                          background: `${entity.color}15`,
                          border: `1px solid ${entity.color}30`,
                          color: entity.color,
                        }}
                      >
                        {entity.label}
                      </span>
                    ))}
                  </div>

                  {/* Tooltip for selected entity on review */}
                  <AnimatePresence>
                    {selectedEntity && (
                      <motion.div
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: 'auto' }}
                        exit={{ opacity: 0, height: 0 }}
                        className="mb-4 px-3 py-2.5 rounded-xl overflow-hidden"
                        style={{
                          background: 'rgba(40, 40, 40, 0.8)',
                          border: `1px solid ${selectedEntity.color}40`,
                        }}
                      >
                        <div className="text-xs font-semibold mb-0.5" style={{ color: selectedEntity.color }}>
                          {selectedEntity.label}
                        </div>
                        <div className="text-xs" style={{ color: '#A5A29A' }}>
                          {selectedEntity.answerSummary || 'No answer given'}
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>

                  {/* Quick stats */}
                  <div className="grid grid-cols-3 gap-3 mb-5">
                    {[
                      { label: 'Questions', value: TOTAL_STEPS },
                      { label: 'Dimensions', value: entities.length },
                      { label: 'Unique to you', value: '100%' },
                    ].map((stat) => (
                      <div key={stat.label} className="text-center">
                        <div className="text-lg font-semibold" style={{ color: '#D4A855' }}>
                          {stat.value}
                        </div>
                        <div className="text-xs" style={{ color: '#706D65' }}>
                          {stat.label}
                        </div>
                      </div>
                    ))}
                  </div>

                  <button
                    onClick={handleFinish}
                    disabled={saving}
                    className="w-full h-12 rounded-xl text-sm font-semibold flex items-center justify-center gap-2 active:scale-[0.97] transition-transform"
                    style={{ background: '#D4A855', color: '#141414', opacity: saving ? 0.7 : 1 }}
                    data-testid="onboarding-finish"
                  >
                    {saving ? (
                      <>
                        <Loader2 size={16} className="animate-spin" />
                        {savePhase || 'Saving your taste profile...'}
                      </>
                    ) : (
                      <>
                        Looks good — let's eat
                        <ChevronRight size={16} />
                      </>
                    )}
                  </button>
                </motion.div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
