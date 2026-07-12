import { apiRequest } from "./client";
import type {
  CreateTransactionResponse,
  ExtractionRetryResponse,
  TransactionDetail,
  TransactionListItem,
} from "../types/transactions";

/**
 * account_v2 işlem oluşturur (multipart). Content-Type AYARLANMAZ — client
 * FormData'yı olduğu gibi geçirir (boundary'yi tarayıcı ekler). Retry güvenli
 * DEĞİLDİR: ağ hatasında kör tekrar yok (C1).
 */
export function createTransaction(form: FormData): Promise<CreateTransactionResponse> {
  return apiRequest<CreateTransactionResponse>("/transactions", {
    method: "POST",
    body: form,
    csrf: true,
    redirectOnError: false,
  });
}

export function listTransactions(): Promise<TransactionListItem[]> {
  return apiRequest<TransactionListItem[]>("/transactions");
}

export function getTransaction(id: string): Promise<TransactionDetail> {
  // Shell satır içi durumları (404/403) kendi render'lar; yönlendirme kapalı.
  return apiRequest<TransactionDetail>(`/transactions/${encodeURIComponent(id)}`, {
    redirectOnError: false,
  });
}

export function retryExtraction(id: string): Promise<ExtractionRetryResponse> {
  return apiRequest<ExtractionRetryResponse>(
    `/transactions/${encodeURIComponent(id)}/extraction/retry`,
    { method: "POST", csrf: true, redirectOnError: false },
  );
}
