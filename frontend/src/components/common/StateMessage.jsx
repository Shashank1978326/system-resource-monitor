export function ErrorBanner({ message, onRetry }) {
  if (!message) return null;
  return (
    <div className="error-banner" role="alert">
      <span className="status-dot status-dot-error" />
      <span>{message}</span>
      {onRetry && (
        <button className="text-button" type="button" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, message }) {
  return (
    <div className="empty-state">
      <span className="empty-state-mark" aria-hidden="true">
        —
      </span>
      <strong>{title}</strong>
      <p>{message}</p>
    </div>
  );
}

export function Skeleton({ className = "" }) {
  return <div className={`skeleton ${className}`} aria-label="Loading" />;
}
