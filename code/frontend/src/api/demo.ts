import { ApiClientError, apiRequest } from "./client";

// Backend `demo_scenarios.TARGET_STATES` ile birebir (Plan 14 / D1).
export type DemoTargetState =
  | "awaiting_review"
  | "awaiting_ratification"
  | "active"
  | "active_partial"
  | "settled"
  | "disputed";

export interface DemoStatus {
  demo_tools_enabled: boolean;
}

export interface DemoScenarioResult {
  transaction_id: string;
  state: string | null;
  lifecycle_version: string | null;
}

export interface CreateScenarioRequest {
  scenario: DemoTargetState;
  transaction_id?: string;
  title?: string;
}

/**
 * Bootstrap probe (Plan 14 / D3): flag açıkken `{demo_tools_enabled: true}` döner.
 * Flag kapalıyken router mount edilmez ve uç 404'tür — bu durumda `null` döneriz;
 * çağıran hiçbir demo UI render etmez (404 = frontend gate'i). 404 dışındaki
 * hatalar (401 vb.) yeniden fırlatılır.
 */
export async function probeDemoStatus(): Promise<DemoStatus | null> {
  try {
    return await apiRequest<DemoStatus>("/demo/status", { redirectOnError: false });
  } catch (error) {
    if (error instanceof ApiClientError && error.kind === "not_found") {
      return null;
    }
    throw error;
  }
}

/** Var olan bir demo işlemini seed'li taraflar adına hedef duruma ilerletir. */
export function advanceDemoTransaction(
  transactionId: string,
  targetState: DemoTargetState,
): Promise<DemoScenarioResult> {
  return apiRequest<DemoScenarioResult>(
    `/demo/transactions/${encodeURIComponent(transactionId)}/advance`,
    { method: "POST", body: { target_state: targetState }, csrf: true, redirectOnError: false },
  );
}

/** Seed'li taraflarla taze bir işlem oluşturup adlandırılmış state'e ilerletir. */
export function createDemoScenario(
  request: CreateScenarioRequest,
): Promise<DemoScenarioResult> {
  return apiRequest<DemoScenarioResult>("/demo/scenarios", {
    method: "POST",
    body: request,
    csrf: true,
    redirectOnError: false,
  });
}
