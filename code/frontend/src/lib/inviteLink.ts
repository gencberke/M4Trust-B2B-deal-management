/**
 * Backend `invite_link` biçimi `/api/invitations/{token}/accept`'tir. Frontend
 * bu token'ı yalnız `/invitations/:token` rotasına taşır; başka hiçbir yere
 * yazmaz/loglamaz.
 */
export function extractInvitationToken(inviteLink: string): string | null {
  if (typeof inviteLink !== "string" || inviteLink.length === 0) return null;
  // Sorgu/parça kısımlarını at, path segmentlerini ayıkla.
  const withoutQuery = inviteLink.split(/[?#]/, 1)[0];
  const segments = withoutQuery.split("/").filter((segment) => segment.length > 0);
  const acceptIndex = segments.lastIndexOf("accept");
  if (acceptIndex < 1) return null;
  const token = segments[acceptIndex - 1];
  // "invitations/accept" gibi eksik token dizilimlerini reddet.
  if (!token || token === "invitations") return null;
  return token;
}

export function frontendInvitationPath(token: string): string {
  return `/invitations/${encodeURIComponent(token)}`;
}
