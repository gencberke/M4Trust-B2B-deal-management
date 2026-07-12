import { describe, expect, it } from "vitest";

import {
  buildCreateTransactionForm,
  createFieldErrorMessage,
  CREATE_NETWORK_WARNING,
} from "./createTransactionForm";

function file(): File {
  return new File(["contract"], "c.md", { type: "text/markdown" });
}

describe("buildCreateTransactionForm", () => {
  it("geçerli girdiden FormData üretir ve boş e-postayı atlar", () => {
    const result = buildCreateTransactionForm({
      file: file(),
      actingEntityId: "ent-1",
      ownRole: "buyer",
      counterpartyEmail: "   ",
    });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.form.get("acting_entity_id")).toBe("ent-1");
    expect(result.form.get("own_role")).toBe("buyer");
    expect(result.form.get("counterparty_email")).toBeNull();
    expect(result.form.get("file")).toBeInstanceOf(File);
  });

  it("e-posta verilince ekler", () => {
    const result = buildCreateTransactionForm({
      file: file(),
      actingEntityId: "ent-1",
      ownRole: "seller",
      counterpartyEmail: " yusuf@example.com ",
    });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.form.get("counterparty_email")).toBe("yusuf@example.com");
  });

  it("entity seçili değilse hata döner", () => {
    const result = buildCreateTransactionForm({
      file: file(),
      actingEntityId: null,
      ownRole: "buyer",
      counterpartyEmail: "",
    });
    expect(result).toEqual({ ok: false, error: "Önce işlem yapılacak entity'yi seçin." });
  });

  it("dosya yoksa hata döner", () => {
    const result = buildCreateTransactionForm({
      file: null,
      actingEntityId: "ent-1",
      ownRole: "buyer",
      counterpartyEmail: "",
    });
    expect(result).toEqual({ ok: false, error: "Sözleşme dosyası seçin." });
  });
});

describe("createFieldErrorMessage", () => {
  it("bilinen 422 kodlarını çevirir", () => {
    expect(createFieldErrorMessage("ACCOUNT_CREATE_FIELDS_REQUIRED")).toContain("gerekli alanlar");
    expect(createFieldErrorMessage("INVALID_OWN_ROLE")).toContain("Rol geçersiz");
  });
  it("bilinmeyen kod için null döner", () => {
    expect(createFieldErrorMessage("SOMETHING_ELSE")).toBeNull();
  });
});

describe("CREATE_NETWORK_WARNING", () => {
  it("kör tekrar yerine liste kontrolü önerir", () => {
    expect(CREATE_NETWORK_WARNING).toContain("İşlemler listesini kontrol");
  });
});
