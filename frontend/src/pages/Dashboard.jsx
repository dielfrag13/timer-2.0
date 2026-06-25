import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../context/AuthContext'
import client from '../api/client'

function formatDuration(seconds) {
  if (!seconds) return '—'
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return s > 0 ? `${m}m ${s}s` : `${m}m`
}

function ActiveCard({ op }) {
  const hasEnteredRoom = Boolean(op.in_room_time)
  return (
    <div className="col-sm-6 col-lg-4">
      <div className="card h-100 shadow-sm">
        <div className="card-body d-flex flex-column">
          <h5 className="card-title mb-1">{op.operation_type_name}</h5>
          <p className="card-text text-muted small mb-1">{op.surgeon_name}</p>
          <p className="card-text text-muted small mb-3">{op.date}</p>
          <div className="mt-auto d-flex gap-2">
            {hasEnteredRoom ? (
              <Link
                to={`/operations/${op.id}/ocs2`}
                className="btn btn-success btn-sm"
              >
                Resume Timing →
              </Link>
            ) : (
              <Link
                to={`/operations/${op.id}/ocs1`}
                className="btn btn-primary btn-sm"
              >
                Setup Steps →
              </Link>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default function Dashboard() {
  const { user } = useAuth()

  const { data: activeData, isLoading: activeLoading } = useQuery({
    queryKey: ['operation-instances', 'active'],
    queryFn: () =>
      client.get('/operation-instances/', { params: { complete: 'false' } })
        .then(r => r.data),
  })

  const { data: completedData, isLoading: completedLoading } = useQuery({
    queryKey: ['operation-instances', 'completed'],
    queryFn: () =>
      client.get('/operation-instances/', { params: { complete: 'true' } })
        .then(r => r.data),
  })

  const active = activeData?.results ?? []
  const completed = completedData?.results ?? []
  const completedCount = completedData?.count ?? 0

  return (
    <div className="container mt-4">

      {/* Header row */}
      <div className="d-flex justify-content-between align-items-center mb-4">
        <h2 className="mb-0">Dashboard</h2>
        <Link to="/operations/new" className="btn btn-primary">
          + Begin Operation
        </Link>
      </div>

      {/* Active operations */}
      <h5 className="text-muted mb-3">
        {activeLoading ? 'Loading…' : `Active (${active.length})`}
      </h5>

      {!activeLoading && active.length === 0 && (
        <p className="text-muted mb-4">
          No active operations.{' '}
          <Link to="/operations/new">Begin one now.</Link>
        </p>
      )}

      <div className="row g-3 mb-5">
        {active.map(op => <ActiveCard key={op.id} op={op} />)}
      </div>

      {/* Completed operations */}
      <h5 className="text-muted mb-3">
        {completedLoading
          ? 'Loading…'
          : `Completed (${completedCount})`}
      </h5>

      {!completedLoading && completed.length === 0 && (
        <p className="text-muted">No completed operations yet.</p>
      )}

      {completed.length > 0 && (
        <table className="table table-sm table-hover align-middle">
          <thead className="table-light">
            <tr>
              <th>Date</th>
              <th>Operation Type</th>
              {user?.is_staff && <th>Surgeon</th>}
              <th>Duration</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {completed.map(op => (
              <tr key={op.id}>
                <td>{op.date}</td>
                <td>{op.operation_type_name}</td>
                {user?.is_staff && <td>{op.surgeon_name}</td>}
                <td className="text-muted">{formatDuration(op.elapsed_time)}</td>
                <td className="text-end">
                  <Link
                    to={`/operations/${op.id}/stats`}
                    className="btn btn-sm btn-outline-secondary"
                  >
                    View Stats
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

    </div>
  )
}
