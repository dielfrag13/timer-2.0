import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../context/AuthContext'
import client from '../api/client'

function nowTimeStr() {
  return new Date().toTimeString().slice(0, 8) // HH:MM:SS
}

export default function OCS1() {
  const { id } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { user } = useAuth()

  const [selectedStep, setSelectedStep] = useState('')

  const { data: operation, isLoading: opLoading } = useQuery({
    queryKey: ['operation-instance', id],
    queryFn: () => client.get(`/operation-instances/${id}/`).then(r => r.data),
  })

  const { data: stepInstancesData } = useQuery({
    queryKey: ['step-instances', id],
    queryFn: () =>
      client.get('/step-instances/', { params: { operation_instance: id } }).then(r => r.data),
  })

  const { data: suggested = [] } = useQuery({
    queryKey: ['suggested-steps', id],
    queryFn: () =>
      client.get(`/operation-instances/${id}/suggested-steps/`).then(r => r.data),
  })

  const { data: allSteps } = useQuery({
    queryKey: ['steps'],
    queryFn: () =>
      client.get('/steps/', { params: { page_size: 100 } }).then(r => r.data.results),
  })

  // Redirect to stats if the operation is already complete.
  useEffect(() => {
    if (operation?.complete) {
      navigate(`/operations/${id}/stats`, { replace: true })
    }
  }, [operation?.complete, navigate, id])

  const instances = stepInstancesData?.results ?? []

  const addOneMutation = useMutation({
    mutationFn: ({ step, order }) =>
      client.post('/step-instances/', { operation_instance: parseInt(id), step, order }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['step-instances', id] }),
  })

  // Creates all suggested steps in sequence so ordering is preserved.
  const addAllMutation = useMutation({
    mutationFn: async steps => {
      for (const [i, step] of steps.entries()) {
        await client.post('/step-instances/', {
          operation_instance: parseInt(id),
          step: step.id,
          order: i,
        })
      }
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['step-instances', id] }),
  })

  const removeMutation = useMutation({
    mutationFn: stepInstanceId => client.delete(`/step-instances/${stepInstanceId}/`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['step-instances', id] }),
  })

  const enterRoomMutation = useMutation({
    mutationFn: () =>
      client.patch(`/operation-instances/${id}/`, { in_room_time: nowTimeStr() }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['operation-instances'] })
      navigate(`/operations/${id}/ocs2`)
    },
  })

  if (opLoading) {
    return <div className="container mt-4">Loading…</div>
  }

  if (operation?.complete) return null // useEffect handles the redirect

  if (operation?.in_room_time) {
    return (
      <div className="container mt-4" style={{ maxWidth: 700 }}>
        <div className="alert alert-info">
          This operation is already in progress.{' '}
          <Link to={`/operations/${id}/ocs2`}>Go to live timing →</Link>
        </div>
      </div>
    )
  }

  return (
    <div className="container mt-4" style={{ maxWidth: 700 }}>
      <h2 className="mb-1">OCS1 — Step Setup</h2>
      <p className="text-muted mb-4">
        {operation?.operation_type_name} &middot; {operation?.date}
        {user?.is_staff && ` · ${operation?.surgeon_name}`}
      </p>

      {/* Current step list */}
      {instances.length === 0 ? (
        <p className="text-muted fst-italic mb-3">No steps added yet.</p>
      ) : (
        <ol className="list-group list-group-numbered mb-3">
          {instances.map(si => (
            <li
              key={si.id}
              className="list-group-item d-flex justify-content-between align-items-center"
            >
              {si.step_title}
              <button
                className="btn btn-sm btn-outline-danger"
                onClick={() => removeMutation.mutate(si.id)}
                disabled={removeMutation.isPending}
              >
                Remove
              </button>
            </li>
          ))}
        </ol>
      )}

      {/* Suggested steps — shown only when the list is empty and history exists */}
      {instances.length === 0 && suggested.length > 0 && (
        <div className="card border-primary mb-4">
          <div className="card-header d-flex justify-content-between align-items-center">
            <span className="fw-semibold">Suggested from prior history</span>
            <button
              className="btn btn-sm btn-primary"
              onClick={() => addAllMutation.mutate(suggested)}
              disabled={addAllMutation.isPending}
            >
              {addAllMutation.isPending ? 'Adding…' : '+ Add All'}
            </button>
          </div>
          <ul className="list-group list-group-flush">
            {suggested.map((step, i) => (
              <li
                key={step.id}
                className="list-group-item d-flex justify-content-between align-items-center"
              >
                <span>
                  <span className="text-muted me-2">{i + 1}.</span>
                  {step.title}
                </span>
                <button
                  className="btn btn-sm btn-outline-primary"
                  onClick={() =>
                    addOneMutation.mutate({ step: step.id, order: instances.length })
                  }
                  disabled={addOneMutation.isPending}
                >
                  + Add
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Manual step picker */}
      <div className="d-flex gap-2 mb-4">
        <select
          className="form-select"
          value={selectedStep}
          onChange={e => setSelectedStep(e.target.value)}
        >
          <option value="">— add a step —</option>
          {(allSteps ?? []).map(s => (
            <option key={s.id} value={s.id}>
              {s.title}
            </option>
          ))}
        </select>
        <button
          className="btn btn-outline-primary flex-shrink-0"
          disabled={!selectedStep || addOneMutation.isPending}
          onClick={() => {
            addOneMutation.mutate({ step: parseInt(selectedStep), order: instances.length })
            setSelectedStep('')
          }}
        >
          Add
        </button>
      </div>

      <div className="d-flex gap-2">
        <button
          className="btn btn-success"
          disabled={instances.length === 0 || enterRoomMutation.isPending}
          onClick={() => enterRoomMutation.mutate()}
        >
          {enterRoomMutation.isPending ? 'Entering…' : 'Enter Room'}
        </button>
        <button className="btn btn-outline-secondary" onClick={() => navigate('/')}>
          Back to Dashboard
        </button>
      </div>
    </div>
  )
}
