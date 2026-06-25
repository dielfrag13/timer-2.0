import axios from 'axios'

const client = axios.create({
  baseURL: '/api/v1/',
  withCredentials: true,
})

// Track whether a refresh is already in flight so concurrent 401s don't
// each trigger their own refresh call.
let isRefreshing = false

client.interceptors.response.use(
  response => response,
  async error => {
    const original = error.config

    // Only attempt refresh for 401s on non-auth endpoints that haven't
    // already been retried.
    if (
      error.response?.status === 401 &&
      !original._retry &&
      !original.url.includes('/auth/')
    ) {
      if (isRefreshing) {
        // A refresh is already in flight; reject so the caller sees the 401
        // rather than sending a second refresh request.
        return Promise.reject(error)
      }

      original._retry = true
      isRefreshing = true

      try {
        await client.post('/auth/refresh/')
        isRefreshing = false
        // Retry the original request — the server will see the new access cookie.
        return client(original)
      } catch {
        isRefreshing = false
        // Refresh failed (expired or blacklisted); hard-redirect to login so
        // React state is fully cleared.
        window.location.href = '/login'
      }
    }

    return Promise.reject(error)
  },
)

export default client
