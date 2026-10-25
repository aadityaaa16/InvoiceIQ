/**
 * API client: one Axios instance that attaches the access token and refreshes it
 * automatically when the backend answers 401.
 *
 * Token storage: the access token lives only in memory (not readable from storage
 * by injected scripts); the refresh token is in localStorage so a page reload stays
 * logged in. Production upgrade: an httpOnly cookie for the refresh token.
 */
import axios, { AxiosError, type InternalAxiosRequestConfig } from "axios";

export const API_URL: string = import.meta.env.VITE_API_URL ?? "http://localhost:8000/api/v1";
const REFRESH_KEY = "invoiceiq_refresh_token";

let accessToken: string | null = null;

export const tokens = {
  set(access: string, refresh: string) {
    accessToken = access;
    localStorage.setItem(REFRESH_KEY, refresh);
  },
  clear() {
    accessToken = null;
    localStorage.removeItem(REFRESH_KEY);
  },
  hasRefresh: () => localStorage.getItem(REFRESH_KEY) !== null,
};

export const api = axios.create({ baseURL: API_URL });

api.interceptors.request.use((config) => {
  if (accessToken) config.headers.Authorization = `Bearer ${accessToken}`;
  return config;
});

// Single-flight refresh: refresh tokens are single-use (rotation), so if several
// requests get 401 at once they must share ONE refresh call. Otherwise the second
// call would reuse an already-spent token and log the user out.
let refreshing: Promise<string | null> | null = null;

async function doRefresh(): Promise<string | null> {
  const refresh = localStorage.getItem(REFRESH_KEY);
  if (!refresh) return null;
  try {
    const { data } = await axios.post(`${API_URL}/auth/refresh`, { refresh_token: refresh });
    tokens.set(data.access_token, data.refresh_token);
    return data.access_token as string;
  } catch {
    tokens.clear();
    return null;
  }
}

export function refreshAccessToken(): Promise<string | null> {
  refreshing ??= doRefresh().finally(() => (refreshing = null));
  return refreshing;
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as (InternalAxiosRequestConfig & { _retried?: boolean }) | undefined;
    const isAuthCall = original?.url?.startsWith("/auth/login") || original?.url?.startsWith("/auth/register");
    if (error.response?.status === 401 && original && !original._retried && !isAuthCall) {
      original._retried = true; // retry once only, never loop
      const token = await refreshAccessToken();
      if (token) {
        original.headers.Authorization = `Bearer ${token}`;
        return api(original);
      }
      window.dispatchEvent(new Event("auth:logout"));
    }
    return Promise.reject(error);
  },
);

/** Turn the backend's {"error": {code, message, details}} into readable text. */
export function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const body = error.response?.data?.error;
    if (body) {
      const details = Array.isArray(body.details)
        ? body.details.map((d: { field: string; message: string }) => `${d.field}: ${d.message}`).join("; ")
        : "";
      return details ? `${body.message} — ${details}` : body.message;
    }
    return error.message;
  }
  return String(error);
}

// ---------------------------------------------------------------- types

export type Role = "admin" | "reviewer" | "uploader";
export type InvoiceStatus = "queued" | "processing" | "needs_review" | "approved" | "rejected" | "failed";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  organization: { id: string; name: string; gstin: string | null };
}

export interface ValidationIssue {
  code: string;
  field: string;
  message: string;
}

export interface Invoice {
  id: string;
  status: InvoiceStatus;
  original_filename: string;
  file_type: string;
  invoice_number: string | null;
  invoice_date: string | null;
  total_amount: string | null;
  confidence_score: number | null;
  vendor: { id: string; name: string; gstin: string } | null;
  created_at: string;
}

export interface InvoiceDetail extends Invoice {
  subtotal: string | null;
  cgst: string | null;
  sgst: string | null;
  igst: string | null;
  validation_errors: ValidationIssue[] | null;
  failure_reason: string | null;
  line_items: { id: string; description: string; hsn_code: string | null; amount: string }[];
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  pages: number;
}
