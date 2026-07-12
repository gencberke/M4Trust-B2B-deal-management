// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const SECRET_TOKEN = "super-secret-token-xyz";

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ user: null, loading: false }),
}));
vi.mock("../entities/EntityContext", () => ({
  useEntities: () => ({ entities: [], selectedEntityId: null }),
}));
vi.mock("../api/invitations", () => ({
  previewInvitation: () =>
    Promise.resolve({ participant_role: "seller", transaction_reference: "ABC12345" }),
  acceptInvitation: () => new Promise(() => {}),
}));

import { InvitationPage } from "./InvitationPage";

afterEach(cleanup);

describe("InvitationPage (logged-out)", () => {
  it("önizlemeyi gösterir ama token'ı DOM'a veya login href'ine sızdırmaz", async () => {
    render(
      <MemoryRouter initialEntries={[`/invitations/${SECRET_TOKEN}`]}>
        <InvitationPage />
      </MemoryRouter>,
    );

    // Önizleme yüklendi.
    await waitFor(() => expect(screen.getByText("ABC12345")).toBeTruthy());

    // Giriş yap linki var ve token içermiyor.
    const loginLink = screen.getByRole("link", { name: "Giriş yap" });
    expect(loginLink.getAttribute("href")).toBe("/login");

    // Token gövdenin HTML'inde hiçbir yerde geçmiyor.
    expect(document.body.innerHTML).not.toContain(SECRET_TOKEN);
  });
});
