import { describe, expect, it, vi } from "vitest";
import { ApiClientError } from "../api/client";
import type { UserPublic } from "../types/api";
import { resolveAuthBootstrap } from "./AuthContext";
const user: UserPublic = { id:"u1", email:"a@example.com", first_name:"Ada", last_name:"Lovelace", status:"active", platform_role:null, email_verified_at:null, created_at:"2026-07-12T00:00:00Z" };
describe("auth bootstrap",()=>{
  it("401 session_required sonucunu oturum yok olarak kabul eder",async()=>{const request=vi.fn().mockRejectedValue(new ApiClientError({kind:"session_required",status:401,code:"HTTP_401"}));await expect(resolveAuthBootstrap(request)).resolves.toEqual({kind:"anonymous",user:null,error:null});});
  it.each([new ApiClientError({kind:"network",code:"NETWORK_ERROR"}),new ApiClientError({kind:"server",status:500,code:"HTTP_500"}),new ApiClientError({kind:"invalid_response",status:200,code:"INVALID_JSON_RESPONSE"})])("network/500/invalid response hatasını bootstrap error olarak korur",async(error)=>{const result=await resolveAuthBootstrap(vi.fn().mockRejectedValue(error));expect(result.kind).toBe("error");expect(result.error).toBe(error);});
  it("retry başarılı olduğunda kullanıcı ve error state toparlanabilir",async()=>{const request=vi.fn().mockRejectedValueOnce(new ApiClientError({kind:"network",code:"NETWORK_ERROR"})).mockResolvedValueOnce(user);const first=await resolveAuthBootstrap(request);const second=await resolveAuthBootstrap(request);expect(first.kind).toBe("error");expect(second).toEqual({kind:"authenticated",user,error:null});});
});
