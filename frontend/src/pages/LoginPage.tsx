import { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { motion } from 'framer-motion';
import { Loader2, Eye, EyeOff } from 'lucide-react';

export default function LoginPage() {
  const { signIn, signUp } = useAuth();
  const [mode, setMode] = useState<'login' | 'signup'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

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

  return (
    <div
      className="phone-frame flex flex-col items-center justify-center px-8"
      style={{ background: '#0A0A0A' }}
    >
      {/* Logo */}
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
        className="mb-10 text-center"
      >
        <h1
          className="text-5xl font-bold tracking-tight"
          style={{ color: '#F0EDE8', fontFamily: "'Inter', sans-serif" }}
        >
          miam
        </h1>
        <p className="text-sm mt-2" style={{ color: '#706D65' }}>
          your personal food intelligence
        </p>
      </motion.div>

      {/* Form */}
      <motion.form
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.15 }}
        onSubmit={handleSubmit}
        className="w-full max-w-sm space-y-4"
      >
        {mode === 'signup' && (
          <div>
            <label className="block text-xs mb-1.5" style={{ color: '#A5A29A' }}>
              Display name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="What should we call you?"
              className="w-full px-4 py-3 rounded-xl text-sm outline-none transition-colors"
              style={{
                background: '#1A1A1A',
                color: '#F0EDE8',
                border: '1px solid #2A2A2A',
              }}
              onFocus={(e) => (e.target.style.borderColor = '#C8956C')}
              onBlur={(e) => (e.target.style.borderColor = '#2A2A2A')}
            />
          </div>
        )}

        <div>
          <label className="block text-xs mb-1.5" style={{ color: '#A5A29A' }}>
            Email
          </label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            required
            autoComplete="email"
            className="w-full px-4 py-3 rounded-xl text-sm outline-none transition-colors"
            style={{
              background: '#1A1A1A',
              color: '#F0EDE8',
              border: '1px solid #2A2A2A',
            }}
            onFocus={(e) => (e.target.style.borderColor = '#C8956C')}
            onBlur={(e) => (e.target.style.borderColor = '#2A2A2A')}
          />
        </div>

        <div>
          <label className="block text-xs mb-1.5" style={{ color: '#A5A29A' }}>
            Password
          </label>
          <div className="relative">
            <input
              type={showPw ? 'text' : 'password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={mode === 'signup' ? 'Min 6 characters' : 'Enter password'}
              required
              autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
              className="w-full px-4 py-3 rounded-xl text-sm outline-none transition-colors pr-12"
              style={{
                background: '#1A1A1A',
                color: '#F0EDE8',
                border: '1px solid #2A2A2A',
              }}
              onFocus={(e) => (e.target.style.borderColor = '#C8956C')}
              onBlur={(e) => (e.target.style.borderColor = '#2A2A2A')}
            />
            <button
              type="button"
              onClick={() => setShowPw(!showPw)}
              className="absolute right-3 top-1/2 -translate-y-1/2"
              style={{ color: '#706D65' }}
            >
              {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
        </div>

        {error && (
          <motion.p
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            className="text-xs px-1"
            style={{ color: '#E06B6B' }}
          >
            {error}
          </motion.p>
        )}

        <button
          type="submit"
          disabled={loading}
          className="w-full py-3 rounded-xl text-sm font-medium flex items-center justify-center gap-2 transition-all active:scale-[0.98]"
          style={{
            background: loading ? '#3A2A1A' : 'linear-gradient(135deg, #C8956C 0%, #8B4A5E 100%)',
            color: '#F0EDE8',
            opacity: loading ? 0.7 : 1,
          }}
        >
          {loading ? (
            <>
              <Loader2 size={16} className="animate-spin" />
              {mode === 'signup' ? 'Creating account...' : 'Signing in...'}
            </>
          ) : mode === 'signup' ? (
            'Create account'
          ) : (
            'Sign in'
          )}
        </button>

        <div className="text-center pt-2">
          <button
            type="button"
            onClick={() => {
              setMode(mode === 'login' ? 'signup' : 'login');
              setError('');
            }}
            className="text-xs transition-colors"
            style={{ color: '#C8956C' }}
          >
            {mode === 'login'
              ? "Don't have an account? Sign up"
              : 'Already have an account? Sign in'}
          </button>
        </div>
      </motion.form>

      {/* Footer */}
      <p className="text-xs mt-12" style={{ color: '#3A3830' }}>
        Early access — invite only
      </p>
    </div>
  );
}
