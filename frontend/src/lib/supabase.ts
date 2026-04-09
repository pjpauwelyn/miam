/**
 * Supabase client for authentication + data access.
 * Uses service role key since the anon key is not configured.
 * For a 10-person testing group this is acceptable.
 * TODO: Switch to anon key + RLS when scaling beyond testers.
 */
import { createClient } from '@supabase/supabase-js';

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
