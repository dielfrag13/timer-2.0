import { Link, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  return (
    <>
      <nav className="navbar navbar-expand-lg navbar-dark bg-dark">
        <div className="container">
          <Link className="navbar-brand fw-bold" to="/">ASC Timer</Link>
          <div className="d-flex align-items-center gap-3">
            <Link className="nav-link text-light" to="/">Dashboard</Link>
            {user?.is_staff && (
              <>
                <Link className="nav-link text-light" to="/surgeons">Surgeons</Link>
                <Link className="nav-link text-light" to="/operation-types">
                  Operation Types
                </Link>
              </>
            )}
            <span className="text-secondary border-start border-secondary ps-3">
              {user?.username}
            </span>
            <button
              className="btn btn-outline-light btn-sm"
              onClick={handleLogout}
            >
              Logout
            </button>
          </div>
        </div>
      </nav>

      <main>
        <Outlet />
      </main>
    </>
  )
}
