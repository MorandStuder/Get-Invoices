import React, { useState, useEffect, useRef } from 'react';
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
import type { DownloadProgress } from './services/api';
import axios from 'axios';

interface DownloadResult {
  success: boolean;
  message: string;
  count: number;
  files: string[];
}

const App: React.FC = () => {
  const [status, setStatus] = useState<string>('Vérification...');
  const [progress, setProgress] = useState<DownloadProgress | null>(null);
  const [result, setResult] = useState<DownloadResult | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [requiresOTP, setRequiresOTP] = useState<boolean>(false);
  const [otpCode, setOtpCode] = useState<string>('');
  const [otpError, setOtpError] = useState<string | null>(null);
  const [pendingDownload, setPendingDownload] = useState<DownloadParams | null>(null);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const abortControllerRef = useRef<AbortController | null>(null);

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
      if (axios.isAxiosError(err) && err.code === 'ERR_NETWORK') {
        setStatus('Backend injoignable. Lancez .\\start.ps1 ou le backend sur http://localhost:8001');
      } else {
        setStatus('Erreur de connexion au serveur');
      }
      console.error(err);
    }
  };

  const handleDownload = async (params: DownloadParams): Promise<void> => {
    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;

    setLoading(true);
    setError(null);
    setResult(null);
    setProgress(null);
    setRequiresOTP(false);
    setOtpError(null);
    setStatus('Connexion en cours…');

    try {
      const response = await downloadInvoices(
        params,
        controller.signal,
        (p: DownloadProgress) => {
          setProgress(p);
          setStatus(p.message || `${p.current} facture(s)`);
        }
      );
      setResult(response);
      setStatus('Téléchargement terminé');
      setProgress(null);
      setRequiresOTP(false);
    } catch (err: unknown) {
      setProgress(null);
      if (err instanceof Error && (err as Error & { name?: string }).name === 'AbortError') {
        setStatus('Téléchargement annulé');
        setError(null);
      } else if (err instanceof Error && (err as Error & { requiresOtp?: boolean }).requiresOtp) {
        setRequiresOTP(true);
        setPendingDownload(params);
        setError(err.message || 'Code 2FA requis. Veuillez saisir le code reçu par SMS, email ou application.');
        setStatus('Code 2FA requis');
      } else if (err instanceof Error && err.message.includes('Failed to fetch')) {
        setError(
          'Impossible de joindre le backend. Vérifiez qu\'il est démarré (http://localhost:8001).'
        );
        setStatus('Erreur réseau');
      } else if (err instanceof Error && err.message.includes('timeout')) {
        setError(err.message || 'Téléchargement interrompu (timeout). Réduisez la période ou le nombre de factures.');
        setStatus('Timeout');
      } else {
        const errorMessage =
          err instanceof Error ? err.message : 'Erreur inconnue';
        setError(errorMessage);
        setStatus('Erreur lors du téléchargement');
      }
    } finally {
      setLoading(false);
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
      }
    }
  };

  const handleCancelDownload = (): void => {
    abortControllerRef.current?.abort();
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
        <h1>📄 Invoice Downloader</h1>
        <p className="subtitle">Téléchargez vos factures Free, Free Mobile, Amazon…</p>
      </header>

      <main className="App-main">
        <StatusDisplay status={status} progress={progress} />
        
        {requiresOTP ? (
          <div className="otp-container">
            <div className="otp-form">
              <h2>🔐 Authentification à deux facteurs</h2>
              <p>Un code de vérification a été demandé.</p>
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
          <>
            <DownloadForm
              providers={providers}
              onDownload={handleDownload}
              loading={loading}
              result={result}
              error={error}
            />
            {loading && (
              <div className="cancel-row">
                <button
                  type="button"
                  className="cancel-button"
                  onClick={handleCancelDownload}
                >
                  Annuler le téléchargement
                </button>
              </div>
            )}
          </>
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

