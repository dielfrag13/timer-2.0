import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../context/AuthContext'
import client from '../api/client'

function nowTimeStr() {
  return new Date().toTimeString().slice(0, 8) // HH:MM:SS
}

function timeStrToSeconds(timeStr) {
  if (!timeStr) return 0
  const [h, m, s] = timeStr.split(':').map(Number)
  return h * 3600 + m * 60 + s
}

function currentSeconds() {
  const now = new Date()
  return now.getHours() * 3600 + now.getMinutes() * 60 + now.getSeconds()
}

function formatDuration(seconds) {
  if (!seconds || seconds <= 0) return '—'
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return s > 0 ? `${m}m ${s}s` : `${m}m`
}

// Returns elapsed seconds for a step, using API value when available,
// local computation otherwise (elapsed_time is null until complete_operation).
function stepElapsed(si) {
  if (si.elapsed_time !== null) return si.elapsed_time
  if (si.start_time && si.end_time) {
    return timeStrToSeconds(si.end_time) - timeStrToSeconds(si.start_time)
  }
  if (si.start_time && !si.end_time) {
    return currentSeconds() - timeStrToSeconds(si.start_time)
  }
  return null
}

export default function OCS2() {
  const { id } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { user } = useAuth()

  // Ticks every second to drive the running clock and the active step's live elapsed.
  const [elapsed, setElapsed] = useState(0)

  const { data: operation, isLoading: opLoading } = useQuery({
    queryKey: ['operation-instance', id],
    queryFn: () => client.get(`/operation-instances/${id}/`).then(r => r.data),
  })

  const { data: stepInstancesData } = useQuery({
    queryKey: ['step-instances', id],
    queryFn: () =>
      client.get('/step-instances/', { params: { operation_instance: id } }).then(r => r.data),
  })

  // Running clock since in_room_time.
  useEffect(() => {
    if (!operation?.in_room_time) return
    const base = timeStrToSeconds(operation.in_room_time)
    const update = () => setElapsed(currentSeconds() - base)
    update()
    const timerId = setInterval(update, 1000)
    return () => clearInterval(timerId)
  }, [operation?.in_room_time])

  // Redirect to stats if the operation is already complete.
  useEffect(() => {
    if (operation?.complete) {
      navigate(`/operations/${id}/stats`, { replace: true })
    }
  }, [operation?.complete, navigate, id])

  const instances = stepInstancesData?.results ?? []
  const allDone = instances.length > 0 && instances.every(si => si.end_time)

  const startMutation = useMutation({
    mutationFn: siId =>
      client.patch(`/step-instances/${siId}/`, { start_time: nowTimeStr() }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['step-instances', id] }),
  })

  const endMutation = useMutation({
    mutationFn: siId =>
      client.patch(`/step-instances/${siId}/`, { end_time: nowTimeStr() }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['step-instances', id] }),
  })

  const completeMutation = useMutation({
    mutationFn: () => client.post(`/operation-instances/${id}/complete/`),
    onSuccess: res => {
      // Seed the detail cache so PostOpStats renders without a flash.
      queryClient.setQueryData(['operation-instance', id], res.data)
      queryClient.invalidateQueries({ queryKey: ['operation-instances'] })
      navigate(`/operations/${id}/stats`)
    },
  })

  if (opLoading) {
    return <div className="container mt-4">Loading…</div>
  }

  if (operation?.complete) return null // useEffect handles the redirect

  if (!operation?.in_room_time) {
    return (
      <div className="container mt-4" style={{ maxWidth: 700 }}>
        <div className="alert alert-warning">
          This operation has not entered the room yet.{' '}
          <Link to={`/operations/${id}/ocs1`}>Go to step setup →</Link>
        </div>
      </div>
    )
  }

  return (
    <div className="container mt-4" style={{ maxWidth: 800 }}>
      <h2 className="mb-1">OCS2 — Live Timing</h2>
      <p className="text-muted mb-3">
        {operation?.operation_type_name} &middot; {operation?.date}
        {user?.is_staff && ` · ${operation?.surgeon_name}`}
      </p>

      <div className="mb-4">
        <span className="text-muted me-2">Time in room:</span>
        <span className="fs-4 fw-semibold font-monospace">{formatDuration(elapsed)}</span>
      </div>

      <table className="table table-bordered align-middle mb-4">
        <thead className="table-light">
          <tr>
            <th style={{ width: '2rem' }}>#</th>
            <th>Step</th>
            <th style={{ width: '9rem' }}>Start</th>
            <th style={{ width: '9rem' }}>End</th>
            <th style={{ width: '7rem' }}>Elapsed</th>
          </tr>
        </thead>
        <tbody>
          {instances.map((si, i) => {
            const isActive = !!si.start_time && !si.end_time
            return (
              <tr key={si.id} className={isActive ? 'table-primary' : ''}>
                <td className="text-muted">{i + 1}</td>
                <td>{si.step_title}</td>

                {/* Start cell */}
                <td>
                  {si.start_time ?? (
                    <button
                      className="btn btn-sm btn-outline-primary"
                      disabled={startMutation.isPending}
                      onClick={() => startMutation.mutate(si.id)}
                    >
                      Now
                    </button>
                  )}
                </td>

                {/* End cell */}
                <td>
                  {si.end_time ? (
                    si.end_time
                  ) : si.start_time ? (
                    <button
                      className="btn btn-sm btn-outline-secondary"
                      disabled={endMutation.isPending}
                      onClick={() => endMutation.mutate(si.id)}
                    >
                      Now
                    </button>
                  ) : (
                    '—'
                  )}
                </td>

                {/* Elapsed cell — live for the active step, computed otherwise */}
                <td className="font-monospace">{formatDuration(stepElapsed(si))}</td>
              </tr>
            )
          })}
        </tbody>
      </table>

      {completeMutation.isError && (
        <div className="alert alert-danger mb-3">
          {completeMutation.error?.response?.data?.detail ??
            'Could not complete the operation. Check that all steps have an end time.'}
        </div>
      )}

      <div className="d-flex gap-2">
        <button
          className="btn btn-success"
          disabled={!allDone || completeMutation.isPending}
          onClick={() => completeMutation.mutate()}
          title={!allDone ? 'All steps must have an end time before completing' : undefined}
        >
          {completeMutation.isPending ? 'Completing…' : 'Complete Operation'}
        </button>
        <button className="btn btn-outline-secondary" onClick={() => navigate('/')}>
          Back to Dashboard
        </button>
      </div>
    </div>
  )
}
