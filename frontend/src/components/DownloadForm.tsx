import React, { useState, useCallback, useEffect } from 'react';
import './DownloadForm.css';
import type { DownloadParams } from '../services/api';
import type { ProviderInfo } from '../services/api';
import { getLastDownloadDate } from '../services/api';

interface DownloadResult {
  success: boolean;
  message: string;
  count: number;
  files: string[];
}

interface DownloadFormProps {
  providers: ProviderInfo[];
  onDownload: (params: DownloadParams) => void;
  loading: boolean;
  result: DownloadResult | null;
  error: string | null;
}

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

type FilterType = 'none' | 'since_last' | 'year' | 'months' | 'range';

const DownloadForm: React.FC<DownloadFormProps> = ({
  providers,
  onDownload,
  loading,
  result,
  error,
}) => {
  const implementedAndConfigured = providers.filter(
    (p) => p.implemented && p.configured
  );
  const firstAvailableId = implementedAndConfigured[0]?.id ?? 'amazon';
  const [provider, setProvider] = useState<string>(firstAvailableId);

  useEffect(() => {
    const available = providers.filter((p) => p.implemented && p.configured);
    if (available.length === 0) return;
    const currentAvailable = available.some((p) => p.id === provider);
    if (!currentAvailable) setProvider(available[0].id);
  }, [providers]);

  const [maxInvoices, setMaxInvoices] = useState<number>(100);
  const [filterType, setFilterType] = useState<FilterType>('since_last');
  const [year, setYear] = useState<number | ''>(new Date().getFullYear());
  const [selectedMonths, setSelectedMonths] = useState<number[]>([]);
  const [dateStart, setDateStart] = useState<string>('');
  const [dateEnd, setDateEnd] = useState<string>('');
  const [forceRedownload, setForceRedownload] = useState<boolean>(false);
  const [lastDownloadDate, setLastDownloadDate] = useState<string | null>(null);
  const [lastDownloadLoading, setLastDownloadLoading] = useState<boolean>(false);

  // Charger la date du dernier téléchargement quand le provider change
  // ou quand l'option "depuis la dernière fois" est sélectionnée
  useEffect(() => {
    if (filterType !== 'since_last') return;
    setLastDownloadLoading(true);
    setLastDownloadDate(null);
    getLastDownloadDate(provider)
      .then((date) => setLastDownloadDate(date))
      .catch(() => setLastDownloadDate(null))
      .finally(() => setLastDownloadLoading(false));
  }, [provider, filterType]);

  const toggleMonth = useCallback((m: number): void => {
    setSelectedMonths((prev) =>
      prev.includes(m) ? prev.filter((x) => x !== m) : [...prev, m].sort((a, b) => a - b)
    );
  }, []);

  const handleSubmit = (e: React.FormEvent): void => {
    e.preventDefault();
    const params: DownloadParams = {
      provider,
      max_invoices: maxInvoices,
      force_redownload: forceRedownload,
    };
    if (filterType === 'since_last') {
      const today = new Date().toISOString().slice(0, 10);
      if (lastDownloadDate) {
        params.date_start = lastDownloadDate;
        params.date_end = today;
      }
      // Si pas de date connue, pas de filtre → télécharge tout (normal pour premier lancement)
    } else if (filterType === 'year' && year) {
      params.year = Number(year);
    } else if (filterType === 'months' && year && selectedMonths.length > 0) {
      params.year = Number(year);
      params.months = selectedMonths.slice();
    } else if (filterType === 'range' && dateStart && dateEnd) {
      params.date_start = dateStart;
      params.date_end = dateEnd;
    }
    onDownload(params);
  };

  const currentYear = new Date().getFullYear();
  const canSubmitRange = filterType !== 'range' || (dateStart && dateEnd);
  const canSubmitMonths = filterType !== 'months' || (year && selectedMonths.length > 0);
  const canSubmitSinceLast = filterType !== 'since_last' || !lastDownloadLoading;
  const canSubmit = canSubmitRange && canSubmitMonths && canSubmitSinceLast;

  return (
    <form onSubmit={handleSubmit} className="download-form">
      <div className="form-group">
        <label htmlFor="provider">Fournisseur</label>
        <select
          id="provider"
          value={provider}
          onChange={(e): void => setProvider(e.target.value)}
        >
          {providers.length === 0 ? (
            <option value="amazon">Amazon (chargement…)</option>
          ) : (
            providers.map((p) => (
              <option
                key={p.id}
                value={p.id}
                disabled={!p.implemented || !p.configured}
              >
                {p.name}
                {!p.implemented ? ' (à venir)' : !p.configured ? ' (non configuré)' : ''}
              </option>
            ))
          )}
        </select>
      </div>
      <div className="form-group">
        <label htmlFor="maxInvoices">
          Nombre maximum de factures à télécharger
        </label>
        <input
          id="maxInvoices"
          type="number"
          min="1"
          max="1000"
          value={maxInvoices}
          onChange={(e): void => setMaxInvoices(Number(e.target.value))}
          required
        />
      </div>

      <div className="form-group">
        <label htmlFor="filterType">Filtrer par période</label>
        <select
          id="filterType"
          value={filterType}
          onChange={(e): void => setFilterType(e.target.value as FilterType)}
        >
          <option value="since_last">Depuis la dernière fois</option>
          <option value="none">Toutes les commandes</option>
          <option value="year">Une année</option>
          <option value="months">Année + un ou plusieurs mois</option>
          <option value="range">Plage de dates</option>
        </select>
      </div>

      {filterType === 'since_last' && (
        <div className="since-last-info">
          {lastDownloadLoading ? (
            <span className="since-last-loading">Recherche du dernier téléchargement…</span>
          ) : lastDownloadDate ? (
            <span className="since-last-date">
              Dernière facture téléchargée : <strong>{lastDownloadDate}</strong>
              <br />
              <small>Téléchargera les factures à partir de cette date jusqu'à aujourd'hui.</small>
            </span>
          ) : (
            <span className="since-last-none">
              Aucun téléchargement précédent trouvé pour ce fournisseur.
              <br />
              <small>Toutes les factures disponibles seront téléchargées.</small>
            </span>
          )}
        </div>
      )}

      {filterType === 'year' && (
        <div className="form-group">
          <label htmlFor="year">Année</label>
          <input
            id="year"
            type="number"
            min="2020"
            max={currentYear}
            value={year}
            onChange={(e): void => setYear(e.target.value ? Number(e.target.value) : '')}
          />
        </div>
      )}

      {filterType === 'months' && (
        <>
          <div className="form-group">
            <label htmlFor="yearMonths">Année</label>
            <input
              id="yearMonths"
              type="number"
              min="2020"
              max={currentYear}
              value={year}
              onChange={(e): void => setYear(e.target.value ? Number(e.target.value) : '')}
            />
          </div>
          <div className="form-group">
            <span className="label-inline">Mois (plusieurs possibles)</span>
            <div className="months-checkboxes">
              {MONTHS.map(({ value, label }) => (
                <label key={value} className="month-checkbox">
                  <input
                    type="checkbox"
                    checked={selectedMonths.includes(value)}
                    onChange={(): void => toggleMonth(value)}
                  />
                  <span>{label}</span>
                </label>
              ))}
            </div>
          </div>
        </>
      )}

      {filterType === 'range' && (
        <div className="form-row">
          <div className="form-group">
            <label htmlFor="dateStart">Du</label>
            <input
              id="dateStart"
              type="date"
              value={dateStart}
              onChange={(e): void => setDateStart(e.target.value)}
            />
          </div>
          <div className="form-group">
            <label htmlFor="dateEnd">Au</label>
            <input
              id="dateEnd"
              type="date"
              value={dateEnd}
              onChange={(e): void => setDateEnd(e.target.value)}
            />
          </div>
        </div>
      )}

      <div className="form-group form-group-checkbox">
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={forceRedownload}
            onChange={(e): void => setForceRedownload(e.target.checked)}
          />
          <span>Forcer le re-téléchargement (ignorer le registre)</span>
        </label>
      </div>

      <button
        type="submit"
        className="download-button"
        disabled={loading || !canSubmit}
      >
        {loading ? 'Téléchargement en cours...' : 'Télécharger les factures'}
      </button>

      {error && (
        <div className="error-message">
          <strong>Erreur:</strong> {error}
        </div>
      )}

      {result && (
        <div className={`result-message ${result.success ? 'success' : 'error'}`}>
          <strong>{result.success ? '✅ Succès' : '❌ Échec'}:</strong>{' '}
          {result.message}
          {result.files.length > 0 && (
            <div className="files-list">
              <strong>Fichiers téléchargés:</strong>
              <ul>
                {result.files.map((file, index) => (
                  <li key={index}>{file}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </form>
  );
};

export default DownloadForm;
