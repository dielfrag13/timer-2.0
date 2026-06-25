import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../context/AuthContext'
import Modal from '../components/Modal'
import client from '../api/client'

function errorMessage(err) {
  const data = err.response?.data
  return data && typeof data === 'object'
    ? Object.values(data).flat().join(' ')
    : 'An error occurred. Please try again.'
}

// Generic table section used for both Operation Types and Steps.
function ReferenceTable({ label, columns, rows, isAdmin, onAdd, onEdit, onDelete, isPendingDelete }) {
  return (
    <section className="mb-5">
      <div className="d-flex justify-content-between align-items-center mb-3">
        <h2 className="mb-0">{label}</h2>
        {isAdmin && (
          <button className="btn btn-primary" onClick={onAdd}>
            Add {label.replace(/s$/, '')}
          </button>
        )}
      </div>
      <table className="table table-hover align-middle">
        <thead className="table-light">
          <tr>
            {columns.map(c => <th key={c}>{c}</th>)}
            {isAdmin && <th />}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td
                colSpan={isAdmin ? columns.length + 1 : columns.length}
                className="text-center text-muted py-4"
              >
                No {label.toLowerCase()} yet.
              </td>
            </tr>
          ) : (
            rows.map(row => (
              <tr key={row.id}>
                {row.cells.map((cell, i) => <td key={i}>{cell}</td>)}
                {isAdmin && (
                  <td className="text-end">
                    <button
                      className="btn btn-sm btn-outline-secondary me-2"
                      onClick={() => onEdit(row)}
                    >
                      Edit
                    </button>
                    <button
                      className="btn btn-sm btn-outline-danger"
                      disabled={isPendingDelete}
                      onClick={() => {
                        if (window.confirm(`Delete "${row.label}"?`)) {
                          onDelete(row.id)
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
    </section>
  )
}

export default function OperationTypes() {
  const { user } = useAuth()
  const isAdmin = user?.is_staff
  const queryClient = useQueryClient()

  // --- Operation Type modal state ---
  const [opModal, setOpModal] = useState(false)
  const [editOp, setEditOp] = useState(null)
  const [opForm, setOpForm] = useState({ operation_type: '' })
  const [opError, setOpError] = useState(null)

  // --- Step modal state ---
  const [stepModal, setStepModal] = useState(false)
  const [editStep, setEditStep] = useState(null)
  const [stepForm, setStepForm] = useState({ title: '' })
  const [stepError, setStepError] = useState(null)

  // --- Queries ---
  const { data: opTypes, isLoading: opLoading } = useQuery({
    queryKey: ['operation-types'],
    queryFn: () => client.get('/operation-types/').then(r => r.data.results),
  })

  const { data: steps, isLoading: stepsLoading } = useQuery({
    queryKey: ['steps'],
    queryFn: () => client.get('/steps/').then(r => r.data.results),
  })

  // --- Operation Type mutations ---
  const saveOpMutation = useMutation({
    mutationFn: data =>
      editOp
        ? client.patch(`/operation-types/${editOp.id}/`, data)
        : client.post('/operation-types/', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['operation-types'] })
      setOpModal(false)
    },
    onError: err => setOpError(errorMessage(err)),
  })

  const deleteOpMutation = useMutation({
    mutationFn: id => client.delete(`/operation-types/${id}/`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['operation-types'] }),
  })

  // --- Step mutations ---
  const saveStepMutation = useMutation({
    mutationFn: data =>
      editStep
        ? client.patch(`/steps/${editStep.id}/`, data)
        : client.post('/steps/', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['steps'] })
      setStepModal(false)
    },
    onError: err => setStepError(errorMessage(err)),
  })

  const deleteStepMutation = useMutation({
    mutationFn: id => client.delete(`/steps/${id}/`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['steps'] }),
  })

  // --- Modal openers ---
  const openCreateOp = () => {
    setEditOp(null); setOpForm({ operation_type: '' }); setOpError(null); setOpModal(true)
  }
  const openEditOp = op => {
    setEditOp(op); setOpForm({ operation_type: op.operation_type }); setOpError(null); setOpModal(true)
  }

  const openCreateStep = () => {
    setEditStep(null); setStepForm({ title: '' }); setStepError(null); setStepModal(true)
  }
  const openEditStep = step => {
    setEditStep(step); setStepForm({ title: step.title }); setStepError(null); setStepModal(true)
  }

  if (opLoading || stepsLoading) {
    return <div className="container mt-4 text-muted">Loading…</div>
  }

  return (
    <div className="container mt-4">

      <ReferenceTable
        label="Operation Types"
        columns={['Name']}
        rows={(opTypes ?? []).map(op => ({
          id: op.id,
          label: op.operation_type,
          cells: [op.operation_type],
          raw: op,
        }))}
        isAdmin={isAdmin}
        onAdd={openCreateOp}
        onEdit={row => openEditOp(row.raw)}
        onDelete={id => deleteOpMutation.mutate(id)}
        isPendingDelete={deleteOpMutation.isPending}
      />

      <p className="text-muted small mb-2">
        Steps are globally defined procedure milestones shared across all
        operation types. The system suggests relevant steps based on what has
        been used historically for each operation type.
      </p>

      <ReferenceTable
        label="Steps"
        columns={['Title']}
        rows={(steps ?? []).map(s => ({
          id: s.id,
          label: s.title,
          cells: [s.title],
          raw: s,
        }))}
        isAdmin={isAdmin}
        onAdd={openCreateStep}
        onEdit={row => openEditStep(row.raw)}
        onDelete={id => deleteStepMutation.mutate(id)}
        isPendingDelete={deleteStepMutation.isPending}
      />

      {opModal && (
        <Modal
          title={editOp ? 'Edit Operation Type' : 'Add Operation Type'}
          onClose={() => setOpModal(false)}
          onSubmit={e => { e.preventDefault(); saveOpMutation.mutate(opForm) }}
          isPending={saveOpMutation.isPending}
        >
          {opError && <div className="alert alert-danger">{opError}</div>}
          <div className="mb-3">
            <label className="form-label">Name</label>
            <input
              className="form-control"
              value={opForm.operation_type}
              onChange={e => setOpForm({ operation_type: e.target.value })}
              required
            />
          </div>
        </Modal>
      )}

      {stepModal && (
        <Modal
          title={editStep ? 'Edit Step' : 'Add Step'}
          onClose={() => setStepModal(false)}
          onSubmit={e => { e.preventDefault(); saveStepMutation.mutate(stepForm) }}
          isPending={saveStepMutation.isPending}
        >
          {stepError && <div className="alert alert-danger">{stepError}</div>}
          <div className="mb-3">
            <label className="form-label">Title</label>
            <input
              className="form-control"
              value={stepForm.title}
              onChange={e => setStepForm({ title: e.target.value })}
              required
            />
          </div>
        </Modal>
      )}

    </div>
  )
}
