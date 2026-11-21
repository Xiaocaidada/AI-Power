import { create } from 'zustand'

import type { User } from '../lib/types'

export type AuthStatus = 'unknown' | 'authenticated' | 'anonymous'

interface AuthState {
  status: AuthStatus
  user: User | null
  setUser: (user: User) => void
  setAnonymous: () => void
  setUnknown: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  status: 'unknown',
  user: null,
  setUser: (user) => set({ status: 'authenticated', user }),
  setAnonymous: () => set({ status: 'anonymous', user: null }),
  setUnknown: () => set({ status: 'unknown' }),
}))