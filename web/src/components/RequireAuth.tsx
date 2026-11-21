import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { useAuthStore } from '../store/auth'
import { FullScreenLoader } from './ui/spinner'

export function RequireAuth() {
  const status = useAuthStore((state) => state.status)
  const location = useLocation()

  if (status === 'unknown') return <FullScreenLoader />
  if (status === 'anonymous') {
    return (
      <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
    )
  }
  return <Outlet />
}