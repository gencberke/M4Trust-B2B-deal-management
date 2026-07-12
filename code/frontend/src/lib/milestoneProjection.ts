import type { EvidenceRecordSummary, MilestoneProjection } from "../types/evidence";

export interface MilestoneTimelineRow {
  id: string | null;
  ruleIndex: number | null;
  title: string;
  releaseMode: string;
  amountMinor: number;
  currency: string;
  requiredEvidence: string[];
  units: {
    id: string;
    sequence: number;
    amountMinor: number;
    status: string;
    releaseInstructionId: string | null;
  }[];
  evidence: EvidenceRecordSummary[];
}

export function buildMilestoneTimeline(
  milestones: MilestoneProjection[],
  evidence: EvidenceRecordSummary[],
): MilestoneTimelineRow[] {
  const rows: MilestoneTimelineRow[] = milestones.map((milestone) => ({
    id: milestone.id,
    ruleIndex: milestone.rule_index,
    title: milestone.title,
    releaseMode: milestone.release_mode,
    amountMinor: milestone.amount_minor,
    currency: milestone.currency,
    requiredEvidence: milestone.required_evidence,
    units: milestone.funding_units.map((unit) => ({
      id: unit.id,
      sequence: unit.sequence,
      amountMinor: unit.amount_minor,
      status: unit.status,
      releaseInstructionId: unit.release_instruction_id,
    })),
    evidence: evidence.filter((record) => record.milestone_id === milestone.id),
  }));
  const unmatched = evidence.filter(
    (record) =>
      !record.milestone_id ||
      !milestones.some((milestone) => milestone.id === record.milestone_id),
  );
  if (unmatched.length) {
    rows.push({
      id: null,
      ruleIndex: null,
      title: "Milestone'a bağlanmamış kanıtlar",
      releaseMode: "—",
      amountMinor: 0,
      currency: "",
      requiredEvidence: [],
      units: [],
      evidence: unmatched,
    });
  }
  return rows;
}
