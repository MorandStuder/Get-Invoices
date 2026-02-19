import axios from 'axios';

const API_BASE_URL =
  process.env.REACT_APP_API_URL || 'http://localhost:8001';

export interface DownloadResponse {
  success: boolean;
  message: string;
  count: number;
  files: string[];
}

export interface DownloadProgress {
  current: number;
  total: number;
  message: string;
}

interface StatusResponse {
  status: string;
  message: string;
}

interface OTPResponse {
  success: boolean;
  message: string;
  requires_otp: boolean;
}

export interface ProviderInfo {
  id: string;
  name: string;
  configured: boolean;
  implemented: boolean;
}

interface ProvidersResponse {
  providers: ProviderInfo[];
}

export const getStatus = async (): Promise<StatusResponse> => {
  const response = await axios.get<StatusResponse>(`${API_BASE_URL}/api/status`);
  return response.data;
};

export const getProviders = async (): Promise<ProviderInfo[]> => {
  const response = await axios.get<ProvidersResponse>(`${API_BASE_URL}/api/providers`);
  return response.data.providers;
};

export interface DownloadParams {
  provider?: string;
  max_invoices: number;
  year?: number;
  month?: number;
  months?: number[];
  date_start?: string;
  date_end?: string;
  force_redownload?: boolean;
}

/**
 * Télécharge les factures via un flux SSE. Appelle onProgress à chaque événement de progression.
 * Retourne le résultat final ou lance en cas d'erreur / 2FA.
 */
export const downloadInvoices = async (
  params: DownloadParams,
  signal?: AbortSignal,
  onProgress?: (progress: DownloadProgress) => void
): Promise<DownloadResponse> => {
  const body: Record<string, unknown> = {
    max_invoices: params.max_invoices,
    force_redownload: params.force_redownload ?? false,
  };
  if (params.provider) body.provider = params.provider;
  if (params.year != null) body.year = params.year;
  if (params.month != null) body.month = params.month;
  if (params.months != null && params.months.length > 0) body.months = params.months;
  if (params.date_start) body.date_start = params.date_start;
  if (params.date_end) body.date_end = params.date_end;

  const response = await fetch(`${API_BASE_URL}/api/download`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok && !response.body) {
    const errData = await response.json().catch(() => ({}));
    const detail = (errData as { detail?: string }).detail || response.statusText;
    if (response.status === 401) {
      const err = new Error(detail) as Error & { requiresOtp?: boolean };
      err.requiresOtp = true;
      throw err;
    }
    throw new Error(detail);
  }

  if (!response.body) {
    throw new Error('Réponse vide');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let lastResult: DownloadResponse | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';
    let eventType = '';
    for (const line of lines) {
      if (line.startsWith('event: ')) {
        eventType = line.slice(7).trim();
      } else if (line.startsWith('data: ') && eventType) {
        try {
          const data = JSON.parse(line.slice(6)) as Record<string, unknown>;
          if (eventType === 'progress' && onProgress) {
            onProgress({
              current: (data.current as number) ?? 0,
              total: (data.total as number) ?? -1,
              message: (data.message as string) ?? '',
            });
          } else if (eventType === 'done') {
            lastResult = data as unknown as DownloadResponse;
          } else if (eventType === 'error') {
            const detail = (data.detail as string) || 'Erreur';
            const requiresOtp = (data.requires_otp as boolean) || /2FA|OTP/i.test(detail);
            const err = new Error(detail) as Error & { requiresOtp?: boolean };
            err.requiresOtp = requiresOtp;
            throw err;
          }
        } catch (e) {
          if (e instanceof SyntaxError) continue;
          throw e;
        }
      }
    }
  }

  if (!lastResult) {
    throw new Error('Téléchargement terminé sans résultat');
  }
  return lastResult;
};

export const submitOTP = async (otpCode: string): Promise<OTPResponse> => {
  const response = await axios.post<OTPResponse>(
    `${API_BASE_URL}/api/submit-otp`,
    {
      otp_code: otpCode,
    }
  );
  return response.data;
};

export const check2FA = async (): Promise<OTPResponse> => {
  const response = await axios.get<OTPResponse>(`${API_BASE_URL}/api/check-2fa`);
  return response.data;
};

