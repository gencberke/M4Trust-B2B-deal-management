import { describe, expect, it } from "vitest";

import { extractInvitationToken, frontendInvitationPath } from "./inviteLink";

describe("extractInvitationToken", () => {
  it("standart accept linkinden token çıkarır", () => {
    expect(extractInvitationToken("/api/invitations/tok-123/accept")).toBe("tok-123");
  });

  it("mutlak URL ve sorgu parçalarını tolere eder", () => {
    expect(
      extractInvitationToken("https://host/api/invitations/abc.def/accept?x=1"),
    ).toBe("abc.def");
  });

  it("token eksik dizilimini reddeder", () => {
    expect(extractInvitationToken("/api/invitations/accept")).toBeNull();
    expect(extractInvitationToken("/api/invitations//accept")).toBeNull();
  });

  it("çöp/boş girdi için null döner", () => {
    expect(extractInvitationToken("")).toBeNull();
    expect(extractInvitationToken("garbage")).toBeNull();
    expect(extractInvitationToken("/api/invitations/tok-1/preview")).toBeNull();
  });
});

describe("frontendInvitationPath", () => {
  it("frontend rota yolunu üretir", () => {
    expect(frontendInvitationPath("tok-123")).toBe("/invitations/tok-123");
  });
  it("özel karakterleri encode eder", () => {
    expect(frontendInvitationPath("a/b")).toBe("/invitations/a%2Fb");
  });
});
