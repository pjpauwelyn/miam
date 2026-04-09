import { useState, useCallback, useRef } from 'react';
import { useLocation } from 'wouter';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronRight, Loader2 } from 'lucide-react';
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
  const [currentStep, setCurrentStep] = useState(0); // 0=intro, 1-17=questions, 18=completion
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

  // Entities become interactive on the single completion screen
  const isInteractive = currentStep === TOTAL_STEPS + 1;

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

        // Build answer summary for the detail panel
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
              className="flex flex-col items-center justify-between text-center px-8"
              style={{ height: '100%', paddingTop: 'max(env(safe-area-inset-top, 48px), 48px)', paddingBottom: 'max(env(safe-area-inset-bottom, 48px), 48px)' }}
            >
              <div className="flex flex-col items-center">
                <motion.div
                  initial={{ scale: 0.8, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  transition={{ delay: 0.2, duration: 0.5, ease: [0.25, 0.1, 0.25, 1] }}
                  style={{ marginBottom: '2rem' }}
                >
                  <MiamLogo size={88} />
                </motion.div>

                <motion.h1
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.4, duration: 0.5 }}
                  className="text-2xl font-semibold"
                  style={{ color: '#F0EDE8' }}
                >
                  Let's get to know{'\n'}each other.
                </motion.h1>
              </div>

              <div className="flex flex-col items-center gap-8">
                <motion.p
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.55, duration: 0.5 }}
                  className="text-[15px] leading-relaxed max-w-[280px]"
                  style={{ color: '#C4B99A' }}
                >
                  A few quick questions so miam can learn your taste.
                  Your answers become your flavour constellation.
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
              </div>
            </motion.div>
          )}

          {/* -------- QUESTION SCREENS -------- */}
          {currentQuestion && (
            <motion.div
              key={`q-${currentStep}`}
              className="flex flex-col"
              style={{ height: '100%' }}
            >
              <div className="flex-shrink-0" style={{ height: 'max(env(safe-area-inset-top, 12px), 24px)' }} />

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
              // Tapping empty space deselects entity
              onClick={() => setSelectedEntityId(null)}
            >
              {/* ── Top stats bar ── */}
              <motion.div
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.3, duration: 0.5 }}
                className="flex items-center justify-center gap-2 flex-shrink-0"
                style={{
                  paddingTop: 'max(env(safe-area-inset-top, 14px), 14px)',
                  paddingBottom: 8,
                }}
              >
                <MiamLogo size={22} />
                <span
                  className="text-xs"
                  style={{ color: '#706D65', letterSpacing: '0.02em' }}
                >
                  {TOTAL_STEPS} questions · {TOTAL_STEPS} dimensions · 100% you
                </span>
              </motion.div>

              {/* ── Physics cluster fills available space ── */}
              <div className="flex-1" />

              {/* ── Bottom panel ── */}
              <div
                className="px-6 pb-6 flex flex-col items-center"
                style={{
                  paddingBottom: 'max(env(safe-area-inset-bottom, 24px), 24px)',
                  background: 'linear-gradient(to bottom, transparent, rgba(10,10,10,0.88) 28%)',
                }}
                // Stop click propagation so tapping panel doesn't deselect
                onClick={(e) => e.stopPropagation()}
              >
                <motion.div
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.5, duration: 0.5 }}
                  className="text-center mb-3"
                >
                  <h2 className="text-lg font-semibold mb-1" style={{ color: '#F0EDE8' }}>
                    Your taste profile
                  </h2>
                  <p className="text-[13px]" style={{ color: '#706D65' }}>
                    Tap any dimension to explore
                  </p>
                </motion.div>

                {/* Entity detail panel — slides up when an entity is tapped */}
                <AnimatePresence>
                  {selectedEntity && (
                    <motion.div
                      key={selectedEntity.id}
                      initial={{ opacity: 0, y: 16, scale: 0.97 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={{ opacity: 0, y: 12, scale: 0.97 }}
                      transition={{ duration: 0.22, ease: [0.25, 0.1, 0.25, 1] }}
                      className="w-full mb-4 px-4 py-3 rounded-2xl"
                      style={{
                        background: 'rgba(22, 22, 22, 0.96)',
                        border: `1px solid ${selectedEntity.color}35`,
                        backdropFilter: 'blur(12px)',
                        WebkitBackdropFilter: 'blur(12px)',
                        maxWidth: 340,
                      }}
                    >
                      <div className="flex items-center gap-2 mb-1.5">
                        {selectedEntity.iconUrl && (
                          <img
                            src={selectedEntity.iconUrl}
                            alt=""
                            style={{ width: 18, height: 18, objectFit: 'contain', opacity: 0.85 }}
                          />
                        )}
                        <span
                          className="text-sm font-semibold"
                          style={{ color: selectedEntity.color }}
                        >
                          {selectedEntity.label}
                        </span>
                      </div>
                      <p className="text-[13px] leading-snug" style={{ color: '#A5A29A' }}>
                        {selectedEntity.answerSummary || 'No answer given'}
                      </p>
                      <p
                        className="text-[11px] mt-1.5"
                        style={{ color: '#4A4845', letterSpacing: '0.02em' }}
                      >
                        This shapes your recommendations
                      </p>
                    </motion.div>
                  )}
                </AnimatePresence>

                <motion.button
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 0.9 }}
                  onClick={handleFinish}
                  disabled={saving}
                  className="w-full max-w-[340px] h-12 rounded-xl text-sm font-semibold flex items-center justify-center gap-2 active:scale-[0.97] transition-transform"
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
                </motion.button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
