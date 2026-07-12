import { describe, expect, it } from "vitest";
import { ApiClientError } from "../api/client";
import { buildApiErrorNavigationState, conflictReturnPath } from "./navigation";
describe("conflict navigation",()=>{it("kaynak route'u navigation state içinde korur",()=>{const state=buildApiErrorNavigationState(new ApiClientError({kind:"conflict",status:409,code:"VERSION_CONFLICT"}),"/entities/e1?tab=profile");expect(state.sourcePath).toBe("/entities/e1?tab=profile");expect(conflictReturnPath(state)).toBe("/entities/e1?tab=profile");});it("conflict ekranını kaynak olarak tekrar kullanmaz",()=>{const state=buildApiErrorNavigationState(new ApiClientError({kind:"conflict",status:409}),"/conflict");expect(conflictReturnPath(state)).toBeNull();});});
