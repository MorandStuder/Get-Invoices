import axios from 'axios';

const API_BASE_URL = 'http://localhost:8001';

interface DownloadResponse {
  success: boolean;
  message: string;
  count: number;
  files: string[];
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

export const downloadInvoices = async (
  params: DownloadParams
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
  const response = await axios.post<DownloadResponse>(
    `${API_BASE_URL}/api/download`,
    body
  );
  return response.data;
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

