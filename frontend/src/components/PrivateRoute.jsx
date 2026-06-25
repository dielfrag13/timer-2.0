import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

// Guards a group of routes: unauthenticated users are sent to /login.
// Renders <Outlet /> so that React Router renders the matched child route
// inside this component once auth is confirmed.
export default function PrivateRoute() {
  const { user, isLoading } = useAuth()

  if (isLoading) {
    return (
      <div className="container mt-5 text-center text-muted">
        Loading&hellip;
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  return <Outlet />
}
