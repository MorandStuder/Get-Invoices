import React from 'react';
import './StatusDisplay.css';

export interface ProgressInfo {
  current: number;
  total: number;
  message: string;
}

interface StatusDisplayProps {
  status: string;
  progress?: ProgressInfo | null;
}

const StatusDisplay: React.FC<StatusDisplayProps> = ({ status, progress }) => {
  const showBar = progress && progress.total > 0;
  const percent = showBar
    ? Math.min(100, Math.round((progress!.current / progress!.total) * 100))
    : 0;

  return (
    <div className="status-display">
      <div className="status-indicator">
        <div className="status-dot"></div>
      </div>
      <div className="status-content">
        <span className="status-text">{status}</span>
        {showBar && (
          <div className="status-progress-bar">
            <div
              className="status-progress-fill"
              style={{ width: `${percent}%` }}
              role="progressbar"
              aria-valuenow={progress!.current}
              aria-valuemin={0}
              aria-valuemax={progress!.total}
            />
          </div>
        )}
      </div>
    </div>
  );
};

export default StatusDisplay;

