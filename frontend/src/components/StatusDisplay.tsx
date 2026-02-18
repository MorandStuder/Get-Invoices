import React from 'react';
import './StatusDisplay.css';

interface StatusDisplayProps {
  status: string;
}

const StatusDisplay: React.FC<StatusDisplayProps> = ({ status }) => {
  return (
    <div className="status-display">
      <div className="status-indicator">
        <div className="status-dot"></div>
      </div>
      <span className="status-text">{status}</span>
    </div>
  );
};

export default StatusDisplay;

