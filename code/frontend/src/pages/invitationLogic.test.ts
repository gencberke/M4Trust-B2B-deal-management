import { describe, expect, it } from "vitest";

import { acceptErrorMessage, previewUnavailableMessage } from "./invitationLogic";

describe("previewUnavailableMessage", () => {
  it("generic geçersiz-davet metni döner", () => {
    expect(previewUnavailableMessage()).toContain("geçersiz");
  });
});

describe("acceptErrorMessage", () => {
  it("her C7 kodu için ayrı Türkçe metin döner", () => {
    expect(acceptErrorMessage("INVITATION_EMAIL_MISMATCH", 403)).toContain("başka bir e-posta");
    expect(acceptErrorMessage("INVITATION_NOT_ACCEPTABLE", 409)).toContain("daha önce kullanılmış");
    expect(acceptErrorMessage("PARTICIPANT_CONFLICT", 409)).toContain("entity çakışması");
    expect(acceptErrorMessage("INVITATION_FORBIDDEN", 403)).toContain("yetkiniz yok");
    expect(acceptErrorMessage("INVITATION_NOT_FOUND", 404)).toContain("bulunamadı");
  });

  it("kod yoksa status'a göre düşer", () => {
    expect(acceptErrorMessage("HTTP_409", 409)).toContain("daha önce kullanılmış");
    expect(acceptErrorMessage("HTTP_403", 403)).toContain("yetkiniz yok");
    expect(acceptErrorMessage("HTTP_404", 404)).toContain("bulunamadı");
  });

  it("bilinmeyen kod + status için generic fallback", () => {
    expect(acceptErrorMessage("MYSTERY", null)).toContain("kabul edilemedi");
    expect(acceptErrorMessage("MYSTERY", 500)).toContain("kabul edilemedi");
  });
});
