import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useAuth } from '../context/AuthContext'
import client from '../api/client'

function todayISO() {
  return new Date().toISOString().slice(0, 10) // YYYY-MM-DD
}

export default function BeginOperation() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const isAdmin = user?.is_staff

  const [form, setForm] = useState({
    operation_type: '',
    surgeon: isAdmin ? '' : String(user?.surgeon_id ?? ''),
    date: todayISO(),
    detail: '',
  })
  const [error, setError] = useState(null)

  const setField = e =>
    setForm(prev => ({ ...prev, [e.target.name]: e.target.value }))

  // Operation types for the dropdown
  const { data: opTypes } = useQuery({
    queryKey: ['operation-types'],
    queryFn: () => client.get('/operation-types/').then(r => r.data.results),
  })

  // Surgeons dropdown — fetched only for admin users
  const { data: surgeons } = useQuery({
    queryKey: ['surgeons'],
    queryFn: () => client.get('/surgeons/').then(r => r.data.results),
    enabled: isAdmin,
  })

  const createMutation = useMutation({
    mutationFn: data => client.post('/operation-instances/', data),
    onSuccess: res => navigate(`/operations/${res.data.id}/ocs1`),
    onError: err => {
      const data = err.response?.data
      setError(
        data && typeof data === 'object'
          ? Object.values(data).flat().join(' ')
          : 'An error occurred. Please try again.',
      )
    },
  })

  const handleSubmit = e => {
    e.preventDefault()
    setError(null)
    createMutation.mutate(form)
  }

  // Guard: a non-admin with no linked surgeon cannot create an operation.
  if (!isAdmin && !user?.surgeon_id) {
    return (
      <div className="container mt-4" style={{ maxWidth: 600 }}>
        <div className="alert alert-warning">
          Your account is not linked to a surgeon record. Ask an administrator
          to link your account before beginning an operation.
        </div>
      </div>
    )
  }

  return (
    <div className="container mt-4" style={{ maxWidth: 600 }}>
      <h2 className="mb-4">Begin Operation</h2>

      {error && <div className="alert alert-danger">{error}</div>}

      <form onSubmit={handleSubmit}>
        <div className="mb-3">
          <label className="form-label">Date</label>
          <input
            name="date"
            type="date"
            className="form-control"
            value={form.date}
            onChange={setField}
            required
          />
        </div>

        <div className="mb-3">
          <label className="form-label">Operation Type</label>
          <select
            name="operation_type"
            className="form-select"
            value={form.operation_type}
            onChange={setField}
            required
          >
            <option value="">— select —</option>
            {(opTypes ?? []).map(op => (
              <option key={op.id} value={op.id}>
                {op.operation_type}
              </option>
            ))}
          </select>
        </div>

        {isAdmin ? (
          <div className="mb-3">
            <label className="form-label">Surgeon</label>
            <select
              name="surgeon"
              className="form-select"
              value={form.surgeon}
              onChange={setField}
              required
            >
              <option value="">— select —</option>
              {(surgeons ?? []).map(s => (
                <option key={s.id} value={s.id}>
                  {s.full_name}
                </option>
              ))}
            </select>
          </div>
        ) : (
          // Non-admin: surgeon is fixed to their own record, not shown.
          <input type="hidden" name="surgeon" value={form.surgeon} />
        )}

        <div className="mb-4">
          <label className="form-label">
            Notes <span className="text-muted small">(optional)</span>
          </label>
          <textarea
            name="detail"
            className="form-control"
            rows={3}
            value={form.detail}
            onChange={setField}
          />
        </div>

        <div className="d-flex gap-2">
          <button
            type="submit"
            className="btn btn-primary"
            disabled={createMutation.isPending}
          >
            {createMutation.isPending ? 'Creating…' : 'Begin Operation'}
          </button>
          <button
            type="button"
            className="btn btn-outline-secondary"
            onClick={() => navigate('/')}
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  )
}
