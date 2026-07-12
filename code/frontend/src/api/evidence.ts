import { apiRequest } from "./client";
import type { EIrsaliyeSubmitRequest,EvidenceBundle,EvidenceRecordPublicView,EvidenceSnapshotResponse,MilestoneFundingProjection } from "../types/evidence";
export const submitEIrsaliye=(id:string,body:EIrsaliyeSubmitRequest)=>apiRequest<EvidenceRecordPublicView>(`/transactions/${encodeURIComponent(id)}/evidence/e-irsaliye`,{method:"POST",body,csrf:true,redirectOnError:false});
export const submitVideoEvidence=(id:string,form:FormData)=>apiRequest<EvidenceRecordPublicView>(`/transactions/${encodeURIComponent(id)}/evidence/video`,{method:"POST",body:form,csrf:true,redirectOnError:false});
export const getEvidenceBundle=(id:string)=>apiRequest<EvidenceBundle>(`/transactions/${encodeURIComponent(id)}/evidence-bundle`,{redirectOnError:false});
export const createEvidenceSnapshot=(id:string)=>apiRequest<EvidenceSnapshotResponse>(`/transactions/${encodeURIComponent(id)}/evidence-snapshots`,{method:"POST",body:{},csrf:true,redirectOnError:false});
export const getMilestones=(id:string)=>apiRequest<MilestoneFundingProjection>(`/transactions/${encodeURIComponent(id)}/milestones`,{redirectOnError:false});
