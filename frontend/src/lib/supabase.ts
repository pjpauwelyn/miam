/**
 * Supabase client for authentication + data access.
 * Uses anon key — all data access respects Row Level Security.
 */
import { createClient } from '@supabase/supabase-js';

// Fallback for local dev — production should always set VITE_SUPABASE_URL
const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL || 'https://rscviujiflpsujukwgts.supabase.co';
const SUPABASE_KEY = import.meta.env.VITE_SUPABASE_KEY || '';

export const supabase = createClient(SUPABASE_URL, SUPABASE_KEY, {
  auth: {
    autoRefreshToken: true,
    persistSession: true,
    detectSessionInUrl: false,
  },
});

export { SUPABASE_URL, SUPABASE_KEY };
