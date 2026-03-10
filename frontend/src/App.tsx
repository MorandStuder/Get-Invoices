import React, { useState, useCallback, useEffect, useRef } from 'react';
import './App.css';
import DownloadForm from './components/DownloadForm';
import StatusDisplay from './components/StatusDisplay';
import {
  downloadInvoices,
  getLastDownloadDate,
  getStatus,
  getProviders,
  submitOTP,
  type DownloadParams,
  type ProviderInfo,
} from './services/api';
import type { DownloadProgress } from './services/api';
import axios from 'axios';

type FilterType = 'none' | 'since_last' | 'year' | 'months' | 'range';

const MONTHS = [
  { value: 1, label: 'Janvier' },
  { value: 2, label: 'Février' },
  { value: 3, label: 'Mars' },
  { value: 4, label: 'Avril' },
  { value: 5, label: 'Mai' },
  { value: 6, label: 'Juin' },
  { value: 7, label: 'Juillet' },
  { value: 8, label: 'Août' },
  { value: 9, label: 'Septembre' },
  { value: 10, label: 'Octobre' },
  { value: 11, label: 'Novembre' },
  { value: 12, label: 'Décembre' },
];

interface DownloadResult {
  success: boolean;
  message: string;
  count: number;
  files: string[];
}

interface ProviderRunResult {
  providerId: string;
  providerName: string;
  status: 'pending' | 'running' | 'done' | 'error';
  count: number;
  message: string;
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
  const [allResults, setAllResults] = useState<ProviderRunResult[] | null>(null);
  const [allLoading, setAllLoading] = useState<boolean>(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const allAbortRef = useRef<boolean>(false);

  // Options "Tout télécharger"
  const currentYear = new Date().getFullYear();
  const [allFilterType, setAllFilterType] = useState<FilterType>('since_last');
  const [allYear, setAllYear] = useState<number>(currentYear);
  const [allSelectedMonths, setAllSelectedMonths] = useState<number[]>([]);
  const [allDateStart, setAllDateStart] = useState<string>('');
  const [allDateEnd, setAllDateEnd] = useState<string>('');
  const [allForceRedownload, setAllForceRedownload] = useState<boolean>(false);

  const toggleAllMonth = useCallback((m: number): void => {
    setAllSelectedMonths((prev) =>
      prev.includes(m) ? prev.filter((x) => x !== m) : [...prev, m].sort((a, b) => a - b)
    );
  }, []);

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

  const buildAllParams = (providerId: string, lastDate: string | null): DownloadParams => {
    const today = new Date().toISOString().slice(0, 10);
    const params: DownloadParams = {
      provider: providerId,
      max_invoices: 100,
      force_redownload: allForceRedownload,
    };
    if (allFilterType === 'since_last') {
      if (lastDate) { params.date_start = lastDate; params.date_end = today; }
    } else if (allFilterType === 'year') {
      params.year = allYear;
    } else if (allFilterType === 'months' && allSelectedMonths.length > 0) {
      params.year = allYear;
      params.months = allSelectedMonths.slice();
    } else if (allFilterType === 'range' && allDateStart && allDateEnd) {
      params.date_start = allDateStart;
      params.date_end = allDateEnd;
    }
    return params;
  };

  const handleDownloadAll = async (): Promise<void> => {
    const available = providers.filter((p) => p.implemented && p.configured);
    if (available.length === 0) return;

    allAbortRef.current = false;
    setAllResults(
      available.map((p) => ({
        providerId: p.id,
        providerName: p.name,
        status: 'pending',
        count: 0,
        message: 'En attente…',
      }))
    );
    setAllLoading(true);
    setResult(null);
    setError(null);

    for (let i = 0; i < available.length; i++) {
      if (allAbortRef.current) break;
      const p = available[i];

      setAllResults((prev) =>
        prev!.map((r, idx) =>
          idx === i ? { ...r, status: 'running', message: 'Connexion…' } : r
        )
      );
      setStatus(`[${p.name}] Connexion…`);

      try {
        const lastDate = allFilterType === 'since_last' ? await getLastDownloadDate(p.id) : null;
        const params = buildAllParams(p.id, lastDate);

        const response = await downloadInvoices(params, undefined, (prog: DownloadProgress) => {
          const msg = prog.message || `${prog.current} facture(s)`;
          setAllResults((prev) =>
            prev!.map((r, idx) => (idx === i ? { ...r, message: msg } : r))
          );
          setStatus(`[${p.name}] ${msg}`);
        });

        setAllResults((prev) =>
          prev!.map((r, idx) =>
            idx === i
              ? { ...r, status: 'done', count: response.count, message: `${response.count} facture(s)` }
              : r
          )
        );
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Erreur';
        setAllResults((prev) =>
          prev!.map((r, idx) => (idx === i ? { ...r, status: 'error', message: msg } : r))
        );
      }
    }

    setAllLoading(false);
    setStatus('Tout télécharger : terminé');
  };

  const handleCancelAll = (): void => {
    allAbortRef.current = true;
    setAllLoading(false);
    setStatus('Annulé');
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

  const canLaunchAll =
    !allLoading &&
    !loading &&
    (allFilterType !== 'range' || (!!allDateStart && !!allDateEnd)) &&
    (allFilterType !== 'months' || allSelectedMonths.length > 0);

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
                  onKeyDown={(e): void => {
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
              loading={loading || allLoading}
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

            {providers.filter((p) => p.implemented && p.configured).length >= 2 && (
              <div className="download-all-section">
                <div className="download-all-header">
                  <span className="download-all-label">Tous les fournisseurs</span>
                  {allLoading ? (
                    <button
                      type="button"
                      className="cancel-button"
                      onClick={handleCancelAll}
                    >
                      Annuler
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="download-all-button"
                      onClick={handleDownloadAll}
                      disabled={!canLaunchAll}
                    >
                      Tout télécharger
                    </button>
                  )}
                </div>

                {/* Options de filtre */}
                <div className="form-group">
                  <label htmlFor="allFilterType">Période</label>
                  <select
                    id="allFilterType"
                    value={allFilterType}
                    onChange={(e): void => setAllFilterType(e.target.value as FilterType)}
                    disabled={allLoading}
                  >
                    <option value="since_last">Depuis la dernière fois</option>
                    <option value="none">Toutes les commandes</option>
                    <option value="year">Une année</option>
                    <option value="months">Année + mois</option>
                    <option value="range">Plage de dates</option>
                  </select>
                </div>

                {(allFilterType === 'year' || allFilterType === 'months') && (
                  <div className="form-group">
                    <label htmlFor="allYear">Année</label>
                    <input
                      id="allYear"
                      type="number"
                      min="2020"
                      max={currentYear}
                      value={allYear}
                      onChange={(e): void => setAllYear(Number(e.target.value))}
                      disabled={allLoading}
                    />
                  </div>
                )}

                {allFilterType === 'months' && (
                  <div className="form-group">
                    <span className="label-inline">Mois</span>
                    <div className="months-checkboxes">
                      {MONTHS.map(({ value, label }) => (
                        <label key={value} className="month-checkbox">
                          <input
                            type="checkbox"
                            checked={allSelectedMonths.includes(value)}
                            onChange={(): void => toggleAllMonth(value)}
                            disabled={allLoading}
                          />
                          <span>{label}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                )}

                {allFilterType === 'range' && (
                  <div className="form-row">
                    <div className="form-group">
                      <label htmlFor="allDateStart">Du</label>
                      <input
                        id="allDateStart"
                        type="date"
                        value={allDateStart}
                        onChange={(e): void => setAllDateStart(e.target.value)}
                        disabled={allLoading}
                      />
                    </div>
                    <div className="form-group">
                      <label htmlFor="allDateEnd">Au</label>
                      <input
                        id="allDateEnd"
                        type="date"
                        value={allDateEnd}
                        onChange={(e): void => setAllDateEnd(e.target.value)}
                        disabled={allLoading}
                      />
                    </div>
                  </div>
                )}

                <div className="form-group form-group-checkbox">
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={allForceRedownload}
                      onChange={(e): void => setAllForceRedownload(e.target.checked)}
                      disabled={allLoading}
                    />
                    <span>Forcer le re-téléchargement</span>
                  </label>
                </div>

                {allResults && (
                  <ul className="all-results-list">
                    {allResults.map((r) => (
                      <li key={r.providerId} className={`all-result-item all-result-${r.status}`}>
                        <span className="all-result-name">{r.providerName}</span>
                        <span className="all-result-msg">
                          {r.status === 'pending' && '⏳'}
                          {r.status === 'running' && '⏳ '}
                          {r.status === 'done' && '✅ '}
                          {r.status === 'error' && '❌ '}
                          {r.message}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
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
