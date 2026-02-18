import React, { useState, useEffect } from 'react';
import './App.css';
import DownloadForm from './components/DownloadForm';
import StatusDisplay from './components/StatusDisplay';
import {
  downloadInvoices,
  getStatus,
  getProviders,
  submitOTP,
  type DownloadParams,
  type ProviderInfo,
} from './services/api';
import axios from 'axios';

interface DownloadResult {
  success: boolean;
  message: string;
  count: number;
  files: string[];
}

const App: React.FC = () => {
  const [status, setStatus] = useState<string>('Vérification...');
  const [result, setResult] = useState<DownloadResult | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [requiresOTP, setRequiresOTP] = useState<boolean>(false);
  const [otpCode, setOtpCode] = useState<string>('');
  const [otpError, setOtpError] = useState<string | null>(null);
  const [pendingDownload, setPendingDownload] = useState<DownloadParams | null>(null);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);

  useEffect(() => {
    checkStatus();
  }, []);

  useEffect(() => {
    getProviders()
      .then(setProviders)
      .catch(() => setProviders([]));
  }, []);

  const checkStatus = async (): Promise<void> => {
    try {
      const response = await getStatus();
      setStatus(response.message);
      
      // Vérifier si un code 2FA est requis
      if (response.status === 'otp_required') {
        setRequiresOTP(true);
      }
    } catch (err) {
      setStatus('Erreur de connexion au serveur');
      console.error(err);
    }
  };

  const handleDownload = async (params: DownloadParams): Promise<void> => {
    setLoading(true);
    setError(null);
    setResult(null);
    setRequiresOTP(false);
    setOtpError(null);

    try {
      const response = await downloadInvoices(params);
      setResult(response);
      setStatus('Téléchargement terminé');
      setRequiresOTP(false);
    } catch (err: unknown) {
      if (axios.isAxiosError(err) && err.response?.status === 401) {
        setRequiresOTP(true);
        setPendingDownload(params);
        setError('Code 2FA requis. Veuillez saisir le code reçu par SMS, email ou application.');
        setStatus('Code 2FA requis');
      } else {
        const errorMessage =
          err instanceof Error ? err.message : 'Erreur inconnue';
        setError(errorMessage);
        setStatus('Erreur lors du téléchargement');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleSubmitOTP = async (): Promise<void> => {
    if (!otpCode || otpCode.length < 4) {
      setOtpError('Le code doit contenir au moins 4 caractères');
      return;
    }

    setOtpError(null);
    setLoading(true);

    try {
      const response = await submitOTP(otpCode);
      
      if (response.success && !response.requires_otp) {
        setRequiresOTP(false);
        setStatus('Code OTP accepté');
        setOtpCode('');
        
        if (pendingDownload) {
          await handleDownload(pendingDownload);
          setPendingDownload(null);
        }
      } else {
        setOtpError(response.message || 'Code OTP incorrect ou expiré');
        setRequiresOTP(response.requires_otp);
      }
    } catch (err: unknown) {
      const errorMessage =
        err instanceof Error ? err.message : 'Erreur lors de la soumission du code';
      setOtpError(errorMessage);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="App">
      <header className="App-header">
        <h1>📦 Get-Invoices (V2)</h1>
        <p className="subtitle">Téléchargez vos factures Amazon, FNAC, Free…</p>
      </header>

      <main className="App-main">
        <StatusDisplay status={status} />
        
        {requiresOTP ? (
          <div className="otp-container">
            <div className="otp-form">
              <h2>🔐 Authentification à deux facteurs</h2>
              <p>Amazon a demandé un code de vérification.</p>
              <p className="otp-instructions">
                Entrez le code que vous avez reçu par SMS, email ou votre application d'authentification.
              </p>
              
              <div className="otp-input-group">
                <input
                  type="text"
                  className="otp-input"
                  placeholder="Code OTP (ex: 123456)"
                  value={otpCode}
                  onChange={(e): void => setOtpCode(e.target.value)}
                  maxLength={10}
                  disabled={loading}
                  onKeyPress={(e): void => {
                    if (e.key === 'Enter') {
                      handleSubmitOTP();
                    }
                  }}
                />
                <button
                  className="otp-submit-button"
                  onClick={handleSubmitOTP}
                  disabled={loading || !otpCode}
                >
                  {loading ? 'Vérification...' : 'Valider le code'}
                </button>
              </div>
              
              {otpError && (
                <div className="otp-error">
                  <strong>Erreur:</strong> {otpError}
                </div>
              )}
              
              <button
                className="otp-cancel-button"
                onClick={(): void => {
                  setRequiresOTP(false);
                  setOtpCode('');
                  setOtpError(null);
                  setPendingDownload(null);
                }}
                disabled={loading}
              >
                Annuler
              </button>
            </div>
          </div>
        ) : (
          <DownloadForm
            providers={providers}
            onDownload={handleDownload}
            loading={loading}
            result={result}
            error={error}
          />
        )}
      </main>

      <footer className="App-footer">
        <p>
          ⚠️ Assurez-vous que vos identifiants sont configurés dans le fichier
          .env
        </p>
      </footer>
    </div>
  );
};

export default App;

