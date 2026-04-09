import { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { motion, AnimatePresence } from 'framer-motion';
import { Loader2, Eye, EyeOff, ArrowRight } from 'lucide-react';
import logoIcon from '@assets/miam-logo-icon.png';

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

  const inputClasses = (field: string) =>
    `w-full px-4 py-3.5 rounded-2xl text-sm outline-none transition-all duration-200 bg-white/[0.04] placeholder:text-white/20`;

  const inputStyle = (field: string) => ({
    color: '#F0EDE8',
    border: `1px solid ${focusedField === field ? 'rgba(200,149,108,0.4)' : 'rgba(255,255,255,0.06)'}`,
    boxShadow: focusedField === field ? '0 0 0 3px rgba(200,149,108,0.06)' : 'none',
  });

  return (
    <div
      className="phone-frame flex flex-col items-center justify-between"
      style={{ background: '#0A0A0A' }}
    >
      {/* Large logo as hero background */}
      <div className="flex-1 flex items-center justify-center w-full relative">
        {/* Big faded logo */}
        <motion.img
          src={logoIcon}
          alt=""
          initial={{ opacity: 0, scale: 0.8 }}
          animate={{ opacity: 0.08, scale: 1 }}
          transition={{ duration: 1.2, ease: [0.22, 1, 0.36, 1] }}
          className="absolute w-72 h-72 object-contain pointer-events-none select-none"
        />

        {/* Foreground branding */}
        <motion.div
          initial={{ opacity: 0, y: -12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.1, ease: [0.22, 1, 0.36, 1] }}
          className="relative z-10 flex flex-col items-center"
        >
          <img src={logoIcon} alt="miam" className="w-14 h-14 object-contain" />
          <h1
            className="text-4xl font-bold tracking-tight mt-4"
            style={{ color: '#F0EDE8' }}
          >
            miam
          </h1>
          <p className="text-sm mt-1.5 tracking-wide" style={{ color: '#706D65' }}>
            your personal food intelligence
          </p>
        </motion.div>
      </div>

      {/* Form area */}
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.25, ease: [0.22, 1, 0.36, 1] }}
        className="w-full px-7 pb-8 pt-2"
      >
        <form onSubmit={handleSubmit} className="space-y-3">
          <AnimatePresence mode="popLayout">
            {mode === 'signup' && (
              <motion.div
                key="name-field"
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.25 }}
              >
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Display name"
                  onFocus={() => setFocusedField('name')}
                  onBlur={() => setFocusedField(null)}
                  className={inputClasses('name')}
                  style={inputStyle('name')}
                />
              </motion.div>
            )}
          </AnimatePresence>

          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Email"
            required
            autoComplete="email"
            onFocus={() => setFocusedField('email')}
            onBlur={() => setFocusedField(null)}
            className={inputClasses('email')}
            style={inputStyle('email')}
          />

          <div className="relative">
            <input
              type={showPw ? 'text' : 'password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={mode === 'signup' ? 'Password (min 6 characters)' : 'Password'}
              required
              autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
              onFocus={() => setFocusedField('password')}
              onBlur={() => setFocusedField(null)}
              className={`${inputClasses('password')} pr-12`}
              style={inputStyle('password')}
            />
            <button
              type="button"
              onClick={() => setShowPw(!showPw)}
              className="absolute right-4 top-1/2 -translate-y-1/2"
              style={{ color: '#5A5750' }}
              tabIndex={-1}
            >
              {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>

          {/* Error */}
          <AnimatePresence>
            {error && (
              <motion.p
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
                className="text-xs px-1"
                style={{ color: '#D4836B' }}
              >
                {error}
              </motion.p>
            )}
          </AnimatePresence>

          {/* Submit */}
          <motion.button
            type="submit"
            disabled={loading}
            whileTap={{ scale: 0.98 }}
            className="w-full py-3.5 rounded-2xl text-sm font-medium flex items-center justify-center gap-2 transition-all"
            style={{
              background: loading
                ? 'rgba(200,149,108,0.12)'
                : 'linear-gradient(135deg, #C8956C 0%, #A06B48 50%, #8B4A5E 100%)',
              color: loading ? 'rgba(200,149,108,0.5)' : '#F0EDE8',
              boxShadow: loading ? 'none' : '0 2px 16px rgba(200,149,108,0.15)',
            }}
          >
            {loading ? (
              <>
                <Loader2 size={16} className="animate-spin" />
                {mode === 'signup' ? 'Creating account...' : 'Signing in...'}
              </>
            ) : (
              <>
                {mode === 'signup' ? 'Create account' : 'Sign in'}
                <ArrowRight size={15} style={{ opacity: 0.6 }} />
              </>
            )}
          </motion.button>
        </form>

        {/* Toggle */}
        <p className="text-center text-xs mt-5" style={{ color: '#5A5750' }}>
          {mode === 'login' ? (
            <>
              New here?{' '}
              <button
                type="button"
                onClick={() => { setMode('signup'); setError(''); }}
                style={{ color: '#C8956C' }}
              >
                Create an account
              </button>
            </>
          ) : (
            <>
              Already have an account?{' '}
              <button
                type="button"
                onClick={() => { setMode('login'); setError(''); }}
                style={{ color: '#C8956C' }}
              >
                Sign in
              </button>
            </>
          )}
        </p>

        {/* Footer */}
        <p className="text-center text-xs mt-6" style={{ color: '#2A2820' }}>
          early access — invite only
        </p>
      </motion.div>
    </div>
  );
}
