// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";

// --- Kontrol edilebilir auth durumu ---
let mockUser: { id: string } | null = null;
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({
    user: mockUser,
    loading: false,
    bootstrapError: null,
    refresh: () => Promise.resolve(null),
  }),
}));
vi.mock("../entities/EntityContext", () => ({
  useEntities: () => ({
    entities: [{ id: "entity-1", legal_name: "Test Entity" }],
    selectedEntity: { id: "entity-1", legal_name: "Test Entity" },
    selectedEntityId: "entity-1",
    loading: false,
    error: null,
    refreshEntities: () => Promise.resolve([]),
    selectEntity: () => {},
  }),
}));
// Shell okuması minimal detay ile çözülür ki Outlet (ve index redirect) render olsun.
vi.mock("../api/transactions", () => ({
  getTransaction: () =>
    Promise.resolve({
      id: "tx-1",
      state: "active",
      created_at: "2026-07-12T00:00:00Z",
      lifecycle_version: "account_v2",
      canonical_state: null,
      extraction: null,
      validator: null,
      events: [],
      payment: null,
    }),
  listTransactions: () => new Promise(() => {}),
}));

import { AppRoutes } from "./AppRoutes";

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="pathname">{location.pathname}</div>;
}

afterEach(() => {
  cleanup();
  mockUser = null;
});

describe("AppRoutes", () => {
  it("/transactions/:id index → overview'e yönlendirir", async () => {
    mockUser = { id: "u1" };
    render(
      <MemoryRouter initialEntries={["/transactions/tx-1"]}>
        <AppRoutes />
        <LocationProbe />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("pathname").textContent).toBe("/transactions/tx-1/overview"),
    );
  });

  it("anonim kullanıcıyı korunan rotadan /session-required'a yönlendirir", async () => {
    mockUser = null;
    render(
      <MemoryRouter initialEntries={["/transactions"]}>
        <AppRoutes />
        <LocationProbe />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("pathname").textContent).toBe("/session-required"),
    );
  });
});
