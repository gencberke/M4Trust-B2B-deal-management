export interface DisputeView{id:string;transaction_id:string;milestone_id:string|null;opened_by_user_id:string;opened_by_entity_id:string;reason_code:string;description:string;status:string;resolution_code:string|null;resolved_by_user_id:string|null;created_at:string;resolved_at:string|null}
export interface DisputeActionView{id:string;dispute_id:string;actor_user_id:string;acting_entity_id:string;action:string;evidence_id:string|null;payload:Record<string,unknown>;created_at:string}
export interface DisputeOpenInput{milestone_id?:string|null;reason_code:string;description:string}
export interface DisputeActionInput{action:string;comment?:string;resolution_code?:string;evidence_id?:string|null;review_case_id?:string|null}
