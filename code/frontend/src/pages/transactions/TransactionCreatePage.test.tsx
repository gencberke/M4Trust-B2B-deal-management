// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

vi.mock("../../entities/EntityContext", () => ({
  useEntities: () => ({ selectedEntity: null, loading: false }),
}));

vi.mock("../../api/transactions", () => ({
  createTransaction: vi.fn(),
}));

import { TransactionCreatePage } from "./TransactionCreatePage";

afterEach(cleanup);

describe("TransactionCreatePage without a selected entity", () => {
  it("keeps the form interactive and explains how to continue", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><TransactionCreatePage /></MemoryRouter>);

    expect((screen.getByLabelText("Sözleşme dosyası") as HTMLInputElement).disabled).toBe(false);
    expect((screen.getByRole("radio", { name: "Alıcı" }) as HTMLInputElement).disabled).toBe(false);
    expect((screen.getByLabelText("Karşı taraf e-postası (isteğe bağlı)") as HTMLInputElement).disabled).toBe(false);
    expect(screen.getByRole("link", { name: "Şirket ekle" }).getAttribute("href")).toBe("/entities/new");

    await user.click(screen.getByRole("button", { name: "İşlemi oluştur" }));
    expect(screen.getByText("Önce işlem yapılacak entity'yi seçin.")).not.toBeNull();
  });
});
