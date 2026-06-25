import { createContext, useContext, useEffect, useState } from 'react'
import client from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [isLoading, setIsLoading] = useState(true)

  // On first render, ask the server who is logged in (if anyone).
  // The browser sends the timer_access cookie automatically; if it is valid
  // the server returns the user object; if not, we get a 401 and stay null.
  useEffect(() => {
    client
      .get('/auth/me/')
      .then(r => setUser(r.data))
      .catch(() => setUser(null))
      .finally(() => setIsLoading(false))
  }, [])

  const login = async (username, password) => {
    // POST credentials → server sets httpOnly cookies in the response.
    await client.post('/auth/login/', { username, password })
    // Immediately call /me/ so AuthContext knows who is now logged in.
    const { data } = await client.get('/auth/me/')
    setUser(data)
  }

  const logout = async () => {
    await client.post('/auth/logout/')
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
