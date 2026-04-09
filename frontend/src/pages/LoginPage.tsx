import { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { motion, AnimatePresence } from 'framer-motion';
import { Loader2, Eye, EyeOff, ArrowRight, User, Mail, Lock } from 'lucide-react';
import { MiamLogo } from '../components/miam/MiamLogo';
import spaceBg from '@assets/space-bg.png';

export default function LoginPage() {
  const { signIn, signUp } = useAuth();
  const [mode, setMode] = useState<'login' | 'signup'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [focusedField, setFocusedField] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    if (mode === 'signup') {
      if (password.length < 6) {
        setError('Password must be at least 6 characters');
        setLoading(false);
        return;
      }
      const { error } = await signUp(email, password, name);
      if (error) setError(error);
    } else {
      const { error } = await signIn(email, password);
      if (error) setError(error);
    }
    setLoading(false);
  };

  const switchMode = () => {
    setMode(mode === 'login' ? 'signup' : 'login');
    setError('');
  };

  return (
    <div className="phone-frame flex flex-col relative overflow-hidden">
      {/* Background — space visual like onboarding */}
      <div className="absolute inset-0">
        <img
          src={spaceBg}
          alt=""
          className="w-full h-full object-cover opacity-40"
          style={{ objectPosition: 'center 40%' }}
        />
        {/* Gradient overlay for readability */}
        <div
          className="absolute inset-0"
          style={{
            background:
              'linear-gradient(180deg, rgba(10,10,10,0.6) 0%, rgba(10,10,10,0.85) 45%, rgba(10,10,10,0.98) 70%, #0A0A0A 100%)',
          }}
        />
      </div>

      {/* Content */}
      <div className="relative z-10 flex flex-col h-full px-8 pt-16 pb-8">
        {/* Top section — Logo & branding */}
        <motion.div
          initial={{ opacity: 0, y: -16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
          className="flex flex-col items-center mb-auto pt-4"
        >
          <MiamLogo size={56} />
          <h1
            className="text-4xl font-bold tracking-tight mt-5"
            style={{ color: '#F0EDE8', fontFamily: "'Inter', sans-serif" }}
          >
            miam
          </h1>
          <p
            className="text-sm mt-2 tracking-wide"
            style={{ color: '#8A8578', letterSpacing: '0.06em' }}
          >
            your personal food intelligence
          </p>
        </motion.div>

        {/* Form section */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.2, ease: [0.22, 1, 0.36, 1] }}
          className="w-full max-w-sm mx-auto mb-auto"
        >
          <form onSubmit={handleSubmit} className="space-y-3">
            <AnimatePresence mode="popLayout">
              {mode === 'signup' && (
                <motion.div
                  key="name-field"
                  initial={{ opacity: 0, height: 0, marginBottom: 0 }}
                  animate={{ opacity: 1, height: 'auto', marginBottom: 12 }}
                  exit={{ opacity: 0, height: 0, marginBottom: 0 }}
                  transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
                >
                  <div
                    className="flex items-center gap-3 px-4 py-3.5 rounded-2xl transition-all duration-200"
                    style={{
                      background: 'rgba(255,255,255,0.04)',
                      border: `1px solid ${focusedField === 'name' ? 'rgba(200,149,108,0.5)' : 'rgba(255,255,255,0.06)'}`,
                      boxShadow: focusedField === 'name' ? '0 0 20px rgba(200,149,108,0.08)' : 'none',
                    }}
                  >
                    <User size={16} style={{ color: '#5A5750', flexShrink: 0 }} />
                    <input
                      type="text"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder="Display name"
                      onFocus={() => setFocusedField('name')}
                      onBlur={() => setFocusedField(null)}
                      className="w-full bg-transparent text-sm outline-none placeholder:text-[#4A4740]"
                      style={{ color: '#F0EDE8' }}
                    />
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Email */}
            <div
              className="flex items-center gap-3 px-4 py-3.5 rounded-2xl transition-all duration-200"
              style={{
                background: 'rgba(255,255,255,0.04)',
                border: `1px solid ${focusedField === 'email' ? 'rgba(200,149,108,0.5)' : 'rgba(255,255,255,0.06)'}`,
                boxShadow: focusedField === 'email' ? '0 0 20px rgba(200,149,108,0.08)' : 'none',
              }}
            >
              <Mail size={16} style={{ color: '#5A5750', flexShrink: 0 }} />
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Email"
                required
                autoComplete="email"
                onFocus={() => setFocusedField('email')}
                onBlur={() => setFocusedField(null)}
                className="w-full bg-transparent text-sm outline-none placeholder:text-[#4A4740]"
                style={{ color: '#F0EDE8' }}
              />
            </div>

            {/* Password */}
            <div
              className="flex items-center gap-3 px-4 py-3.5 rounded-2xl transition-all duration-200"
              style={{
                background: 'rgba(255,255,255,0.04)',
                border: `1px solid ${focusedField === 'password' ? 'rgba(200,149,108,0.5)' : 'rgba(255,255,255,0.06)'}`,
                boxShadow: focusedField === 'password' ? '0 0 20px rgba(200,149,108,0.08)' : 'none',
              }}
            >
              <Lock size={16} style={{ color: '#5A5750', flexShrink: 0 }} />
              <input
                type={showPw ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={mode === 'signup' ? 'Password (min 6 characters)' : 'Password'}
                required
                autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
                onFocus={() => setFocusedField('password')}
                onBlur={() => setFocusedField(null)}
                className="w-full bg-transparent text-sm outline-none placeholder:text-[#4A4740]"
                style={{ color: '#F0EDE8' }}
              />
              <button
                type="button"
                onClick={() => setShowPw(!showPw)}
                className="flex-shrink-0 p-0.5 transition-colors"
                style={{ color: '#5A5750' }}
                tabIndex={-1}
              >
                {showPw ? <EyeOff size={15} /> : <Eye size={15} />}
              </button>
            </div>

            {/* Error */}
            <AnimatePresence>
              {error && (
                <motion.div
                  initial={{ opacity: 0, y: -4, height: 0 }}
                  animate={{ opacity: 1, y: 0, height: 'auto' }}
                  exit={{ opacity: 0, y: -4, height: 0 }}
                  transition={{ duration: 0.2 }}
                  className="px-4 py-2.5 rounded-xl text-xs"
                  style={{
                    background: 'rgba(224,107,107,0.08)',
                    border: '1px solid rgba(224,107,107,0.15)',
                    color: '#E8A0A0',
                  }}
                >
                  {error}
                </motion.div>
              )}
            </AnimatePresence>

            {/* Submit button */}
            <motion.button
              type="submit"
              disabled={loading}
              whileTap={{ scale: 0.98 }}
              className="w-full py-3.5 rounded-2xl text-sm font-medium flex items-center justify-center gap-2.5 transition-all mt-2"
              style={{
                background: loading
                  ? 'rgba(200,149,108,0.15)'
                  : 'linear-gradient(135deg, #C8956C 0%, #A06B48 50%, #8B4A5E 100%)',
                color: loading ? '#8A7560' : '#F0EDE8',
                boxShadow: loading ? 'none' : '0 4px 24px rgba(200,149,108,0.2), inset 0 1px 0 rgba(255,255,255,0.1)',
                border: '1px solid rgba(255,255,255,0.06)',
              }}
            >
              {loading ? (
                <>
                  <Loader2 size={16} className="animate-spin" />
                  <span>{mode === 'signup' ? 'Creating account...' : 'Signing in...'}</span>
                </>
              ) : (
                <>
                  <span>{mode === 'signup' ? 'Create account' : 'Sign in'}</span>
                  <ArrowRight size={15} style={{ opacity: 0.7 }} />
                </>
              )}
            </motion.button>
          </form>

          {/* Mode switch */}
          <div className="text-center mt-5">
            <button
              type="button"
              onClick={switchMode}
              className="text-xs transition-colors"
              style={{ color: '#8A7560' }}
            >
              {mode === 'login' ? (
                <>
                  New here?{' '}
                  <span style={{ color: '#C8956C' }}>Create an account</span>
                </>
              ) : (
                <>
                  Already have an account?{' '}
                  <span style={{ color: '#C8956C' }}>Sign in</span>
                </>
              )}
            </button>
          </div>
        </motion.div>

        {/* Footer */}
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.5, duration: 0.6 }}
          className="text-center text-xs pt-4"
          style={{ color: '#2E2C28' }}
        >
          early access — invite only
        </motion.p>
      </div>
    </div>
  );
}
