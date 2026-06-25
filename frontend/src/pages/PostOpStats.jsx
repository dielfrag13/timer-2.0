import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../context/AuthContext'
import client from '../api/client'

function formatDuration(seconds) {
  if (!seconds || seconds <= 0) return '—'
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return s > 0 ? `${m}m ${s}s` : `${m}m`
}

function rowClass(dist) {
  if (dist === null || dist === undefined) return ''
  const abs = Math.abs(dist)
  if (abs < 10) return 'table-success'
  if (abs < 25) return 'table-warning'
  return 'table-danger'
}

function formatDist(dist) {
  if (dist === null || dist === undefined) return null
  const sign = dist > 0 ? '+' : ''
  return `${sign}${dist.toFixed(1)}%`
}

export default function PostOpStats() {
  const { id } = useParams()
  const { user } = useAuth()

  const { data: operation, isLoading } = useQuery({
    queryKey: ['operation-instance', id],
    queryFn: () => client.get(`/operation-instances/${id}/`).then(r => r.data),
  })

  if (isLoading) {
    return <div className="container mt-4">Loading…</div>
  }

  const steps = operation?.steps ?? []

  return (
    <div className="container mt-4" style={{ maxWidth: 800 }}>
      <h2 className="mb-1">Post-op Stats</h2>
      <p className="text-muted mb-4">
        {operation?.operation_type_name} &middot; {operation?.date}
        {user?.is_staff && ` · ${operation?.surgeon_name}`}
        &nbsp;&middot;&nbsp;Total: {formatDuration(operation?.elapsed_time)}
      </p>

      {!operation?.complete && (
        <div className="alert alert-warning mb-3">
          This operation has not been completed yet. Stats may be incomplete.
        </div>
      )}

      <table className="table table-bordered align-middle mb-2">
        <thead className="table-light">
          <tr>
            <th style={{ width: '2rem' }}>#</th>
            <th>Step</th>
            <th style={{ width: '8rem' }}>Start</th>
            <th style={{ width: '8rem' }}>End</th>
            <th style={{ width: '6rem' }}>Elapsed</th>
            <th style={{ width: '7rem' }}>vs. Avg</th>
          </tr>
        </thead>
        <tbody>
          {steps.map((si, i) => (
            <tr key={si.id} className={rowClass(si.dist_from_average)}>
              <td className="text-muted">{i + 1}</td>
              <td>{si.step_title}</td>
              <td className="font-monospace">{si.start_time ?? '—'}</td>
              <td className="font-monospace">{si.end_time ?? '—'}</td>
              <td className="font-monospace">{formatDuration(si.elapsed_time)}</td>
              <td>
                {formatDist(si.dist_from_average) ?? (
                  <span className="text-muted">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Color legend */}
      <p className="text-muted small mb-4">
        <span className="badge bg-success me-1"> </span>within 10% of avg&nbsp;&nbsp;
        <span className="badge bg-warning text-dark me-1"> </span>10–25%&nbsp;&nbsp;
        <span className="badge bg-danger me-1"> </span>beyond 25%&nbsp;&nbsp;
        <span className="badge bg-secondary me-1"> </span>no history
      </p>

      <div className="d-flex gap-2">
        <a
          href={`/api/v1/operation-instances/${id}/export-csv/`}
          className="btn btn-outline-secondary"
        >
          Download CSV
        </a>
        <Link to="/" className="btn btn-outline-secondary">
          Back to Dashboard
        </Link>
      </div>
    </div>
  )
}
