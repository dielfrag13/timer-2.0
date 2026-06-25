import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../context/AuthContext'
import Modal from '../components/Modal'
import client from '../api/client'

const EMPTY_FORM = { first_name: '', last_name: '', email: '' }

export default function Surgeons() {
  const { user } = useAuth()
  const isAdmin = user?.is_staff
  const queryClient = useQueryClient()

  const [showModal, setShowModal] = useState(false)
  const [editTarget, setEditTarget] = useState(null) // null = create mode, object = edit mode
  const [form, setForm] = useState(EMPTY_FORM)
  const [formError, setFormError] = useState(null)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['surgeons'],
    queryFn: () => client.get('/surgeons/').then(r => r.data.results),
  })

  // --- Modal helpers ---

  const openCreate = () => {
    setEditTarget(null)
    setForm(EMPTY_FORM)
    setFormError(null)
    setShowModal(true)
  }

  const openEdit = surgeon => {
    setEditTarget(surgeon)
    setForm({ first_name: surgeon.first_name, last_name: surgeon.last_name, email: surgeon.email })
    setFormError(null)
    setShowModal(true)
  }

  const closeModal = () => {
    setShowModal(false)
    setEditTarget(null)
    setFormError(null)
  }

  const setField = e =>
    setForm(prev => ({ ...prev, [e.target.name]: e.target.value }))

  // --- Mutations ---

  const saveMutation = useMutation({
    mutationFn: formData =>
      editTarget
        ? client.patch(`/surgeons/${editTarget.id}/`, formData)
        : client.post('/surgeons/', formData),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['surgeons'] })
      closeModal()
    },
    onError: err => {
      const data = err.response?.data
      if (data && typeof data === 'object') {
        setFormError(Object.values(data).flat().join(' '))
      } else {
        setFormError('An error occurred. Please try again.')
      }
    },
  })

  const deleteMutation = useMutation({
    mutationFn: id => client.delete(`/surgeons/${id}/`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['surgeons'] }),
  })

  const handleSubmit = e => {
    e.preventDefault()
    setFormError(null)
    saveMutation.mutate(form)
  }

  // --- Render ---

  if (isLoading) return <div className="container mt-4 text-muted">Loading…</div>
  if (isError) return <div className="container mt-4 text-danger">Failed to load surgeons.</div>

  const surgeons = data ?? []

  return (
    <div className="container mt-4">
      <div className="d-flex justify-content-between align-items-center mb-3">
        <h2 className="mb-0">Surgeons</h2>
        {isAdmin && (
          <button className="btn btn-primary" onClick={openCreate}>
            Add Surgeon
          </button>
        )}
      </div>

      <table className="table table-hover align-middle">
        <thead className="table-light">
          <tr>
            <th>Name</th>
            <th>Email</th>
            <th>Username</th>
            {isAdmin && <th />}
          </tr>
        </thead>
        <tbody>
          {surgeons.length === 0 ? (
            <tr>
              <td colSpan={isAdmin ? 4 : 3} className="text-center text-muted py-4">
                No surgeons yet.
              </td>
            </tr>
          ) : (
            surgeons.map(s => (
              <tr key={s.id}>
                <td>{s.full_name}</td>
                <td>{s.email}</td>
                <td className="text-muted">{s.username ?? '—'}</td>
                {isAdmin && (
                  <td className="text-end">
                    <button
                      className="btn btn-sm btn-outline-secondary me-2"
                      onClick={() => openEdit(s)}
                    >
                      Edit
                    </button>
                    <button
                      className="btn btn-sm btn-outline-danger"
                      disabled={deleteMutation.isPending}
                      onClick={() => {
                        if (window.confirm(`Delete ${s.full_name}?`)) {
                          deleteMutation.mutate(s.id)
                        }
                      }}
                    >
                      Delete
                    </button>
                  </td>
                )}
              </tr>
            ))
          )}
        </tbody>
      </table>

      {showModal && (
        <Modal
          title={editTarget ? 'Edit Surgeon' : 'Add Surgeon'}
          onClose={closeModal}
          onSubmit={handleSubmit}
          isPending={saveMutation.isPending}
        >
          {formError && <div className="alert alert-danger">{formError}</div>}
          <div className="mb-3">
            <label className="form-label">First name</label>
            <input
              name="first_name"
              className="form-control"
              value={form.first_name}
              onChange={setField}
              required
            />
          </div>
          <div className="mb-3">
            <label className="form-label">Last name</label>
            <input
              name="last_name"
              className="form-control"
              value={form.last_name}
              onChange={setField}
              required
            />
          </div>
          <div className="mb-3">
            <label className="form-label">Email</label>
            <input
              name="email"
              type="email"
              className="form-control"
              value={form.email}
              onChange={setField}
              required
            />
          </div>
        </Modal>
      )}
    </div>
  )
}
