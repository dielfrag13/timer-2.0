import { Routes, Route } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import PrivateRoute from './components/PrivateRoute'
import Layout from './components/Layout'
import Login from './pages/Login'
import Surgeons from './pages/Surgeons'
import OperationTypes from './pages/OperationTypes'
import Dashboard from './pages/Dashboard'
import BeginOperation from './pages/BeginOperation'
import OCS1 from './pages/OCS1'
import OCS2 from './pages/OCS2'
import PostOpStats from './pages/PostOpStats'

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        {/* Public */}
        <Route path="/login" element={<Login />} />

        {/* All authenticated routes live inside PrivateRoute → Layout.
            PrivateRoute checks auth and renders <Outlet />.
            Layout renders the navbar and then its own <Outlet /> for the page. */}
        <Route element={<PrivateRoute />}>
          <Route element={<Layout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/surgeons" element={<Surgeons />} />
            <Route path="/operation-types" element={<OperationTypes />} />
            <Route path="/operations/new" element={<BeginOperation />} />
            <Route path="/operations/:id/ocs1" element={<OCS1 />} />
            <Route path="/operations/:id/ocs2" element={<OCS2 />} />
            <Route path="/operations/:id/stats" element={<PostOpStats />} />
          </Route>
        </Route>
      </Routes>
    </AuthProvider>
  )
}
