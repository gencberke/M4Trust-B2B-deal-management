import { describe, expect, it } from "vitest";

import type { ParticipantPublicView } from "../../types/participants";
import {
  inviteErrorMessage,
  invitableRoles,
  profilePanelMode,
  profileSnapshotFromForm,
} from "./partiesLogic";

function participant(over: Partial<ParticipantPublicView>): ParticipantPublicView {
  return {
    id: "p",
    role: "buyer",
    status: "invited",
    display_name: null,
    confirmed: false,
    confirmed_at: null,
    ...over,
  };
}

describe("invitableRoles", () => {
  it("yalnız invited && !confirmed rolleri döner", () => {
    const participants = [
      participant({ role: "buyer", status: "confirmed", confirmed: true }),
      participant({ role: "seller", status: "invited", confirmed: false }),
    ];
    expect(invitableRoles(participants)).toEqual(["seller"]);
  });

  it("ready/confirmed rolleri sunmaz", () => {
    const participants = [
      participant({ role: "buyer", status: "ready" }),
      participant({ role: "seller", status: "confirmed", confirmed: true }),
    ];
    expect(invitableRoles(participants)).toEqual([]);
  });

  it("supersede: invited iken rol hâlâ davet edilebilir", () => {
    const participants = [participant({ role: "seller", status: "invited" })];
    expect(invitableRoles(participants)).toContain("seller");
  });
});

describe("profileSnapshotFromForm", () => {
  it("trim yapar, boşları null'a çevirir", () => {
    const snap = profileSnapshotFromForm({
      name: "  ABC A.Ş. ",
      tax_id: "  ",
      contact_email: " a@b.com ",
      contact_phone: "",
      address: "  İstanbul ",
    });
    expect(snap).toEqual({
      name: "ABC A.Ş.",
      tax_id: null,
      contact_email: "a@b.com",
      contact_phone: null,
      address: "İstanbul",
    });
  });
});

describe("inviteErrorMessage", () => {
  it("bilinen kodları çevirir", () => {
    expect(inviteErrorMessage("INVITATION_ROLE_ALREADY_BOUND")).toContain("zaten bir tarafa bağlı");
    expect(inviteErrorMessage("INVITATION_NOT_REVOCABLE")).toContain("iptal edilemez");
  });
  it("bilinmeyen kod için genel mesaj döner", () => {
    expect(inviteErrorMessage("WHATEVER")).toContain("tamamlanamadı");
  });
});

describe("profilePanelMode", () => {
  it("katılımcı yoksa gizli", () => {
    expect(profilePanelMode(null, false, true)).toBe("hidden");
  });
  it("yerel snapshot yok + ready ise overwrite guard", () => {
    expect(profilePanelMode("ready", false, false)).toBe("overwrite_guard");
  });
  it("yerel snapshot varsa düzenlenebilir", () => {
    expect(profilePanelMode("ready", true, false)).toBe("editable");
  });
  it("invited durumda düzenlenebilir", () => {
    expect(profilePanelMode("invited", false, false)).toBe("editable");
  });
});
