import { describe, expect, it, vi } from "vitest";
import { ApiClientError } from "../api/client";
import type { EntityPublic } from "../types/api";
import { resolveEntityBootstrap } from "./EntityContext";
const entity: EntityPublic = { id:"e1", entity_type:"company", legal_name:"M4Trust A.Ş.", tax_identifier_type:"vkn", tax_identifier_last4:"1234", tax_office:null, address_json:null, verification_status:"self_declared", my_role:"owner", created_at:"2026-07-12", updated_at:"2026-07-12" };
describe("entity bootstrap",()=>{
  it("fetch failure sonucunu güvenli error state olarak yakalar ve retry edilebilir",async()=>{const request=vi.fn().mockRejectedValueOnce(new ApiClientError({kind:"network",code:"NETWORK_ERROR"})).mockResolvedValueOnce([entity]);const first=await resolveEntityBootstrap(request);const second=await resolveEntityBootstrap(request);expect(first.kind).toBe("error");expect(first.error?.userMessage).not.toContain("backend");expect(second).toEqual({kind:"success",entities:[entity],error:null});});
  it("401 durumunu selector error yerine auth akışına bırakır",async()=>{const result=await resolveEntityBootstrap(vi.fn().mockRejectedValue(new ApiClientError({kind:"session_required",status:401,code:"HTTP_401"})));expect(result).toEqual({kind:"auth_required",entities:[],error:null});});
});
