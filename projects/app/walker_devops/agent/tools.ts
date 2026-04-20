import { z } from 'zod';
import { tool } from '@openai/agents';
import type { LaunchInput, PlanTask, RiskItem } from './types.js';

const launchSchema = z.object({
  productBrief: z.string().min(1),
  audience: z.string().min(1),
  launchDate: z.string().min(1),
  constraints: z.string().default(''),
  assets: z.string().default(''),
});

const rubric = [
  'Clear audience and launch goal',
  'Messaging assets drafted',
  'Tracking and analytics owner assigned',
  'Rollback and incident plan documented',
  'Support FAQ and on-call staffing defined',
  'Go/no-go checkpoint 24h before launch',
];

const parseList = (input: string): string[] =>
  input
    .split(/\n|,/)
    .map((s) => s.trim())
    .filter(Boolean);

export const extractTasksTool = tool({
  name: 'extract_launch_tasks',
  description: 'Extract actionable launch tasks from brief and constraints.',
  parameters: launchSchema,
  async execute(input: LaunchInput): Promise<PlanTask[]> {
    const constraints = parseList(input.constraints);
    const assets = parseList(input.assets);

    return [
      {
        title: 'Finalize launch narrative and success metrics',
        owner: 'PM',
        priority: 'P0',
        dueBy: input.launchDate,
        rationale: `Aligns product brief with target audience: ${input.audience.slice(0, 80)}...`,
      },
      {
        title: 'Create engineering cut checklist and freeze window',
        owner: 'Engineering',
        priority: 'P0',
        dueBy: input.launchDate,
        rationale: `Constraints to respect: ${constraints.join('; ') || 'none provided'}`,
      },
      {
        title: 'Draft channel launch copy package',
        owner: 'Marketing',
        priority: assets.length > 0 ? 'P1' : 'P0',
        dueBy: input.launchDate,
        rationale: `Existing assets: ${assets.join('; ') || 'none provided'}`,
      },
    ];
  },
});

export const launchReadinessTool = tool({
  name: 'check_launch_readiness',
  description: 'Evaluate launch readiness against a fixed rubric.',
  parameters: z.object({
    brief: z.string().min(1),
    constraints: z.string().default(''),
    assets: z.string().default(''),
  }),
  async execute({ brief, constraints, assets }) {
    const source = `${brief}\n${constraints}\n${assets}`.toLowerCase();
    const checks = rubric.map((criterion) => ({
      criterion,
      status: source.includes(criterion.split(' ')[0].toLowerCase()) ? 'likely-covered' : 'needs-detail',
    }));

    const readinessScore = Math.round(
      (checks.filter((c) => c.status === 'likely-covered').length / checks.length) * 100,
    );

    return { readinessScore, checks };
  },
});

export const ownerChecklistTool = tool({
  name: 'generate_owner_checklist',
  description: 'Generate launch owner checklists grouped by function.',
  parameters: launchSchema,
  async execute(input: LaunchInput) {
    return {
      PM: [
        `Approve launch date (${input.launchDate}) and go/no-go criteria`,
        'Confirm dependencies and blockers are tracked in one board',
      ],
      Engineering: [
        'Run smoke tests in production-like environment',
        'Prepare rollback instructions and ownership handoff',
      ],
      Marketing: [
        `Tailor announcement for audience: ${input.audience.slice(0, 60)}`,
        'Schedule post-launch distribution timeline',
      ],
      Support: ['Prepare FAQ/macros', 'Set escalation path for first 48 hours'],
    };
  },
});

export const launchCopyTool = tool({
  name: 'draft_launch_copy',
  description: 'Draft channel-specific launch copy in concise style.',
  parameters: z.object({
    productName: z.string().min(1),
    launchValue: z.string().min(1),
  }),
  async execute({ productName, launchValue }) {
    const headline = `${productName} is launching soon`;
    return {
      email: `Subject: ${headline}\n\nWe are launching ${productName}. ${launchValue}. Reply with questions before launch day.`,
      social: `Launching ${productName}: ${launchValue} #launch #product`,
      inApp: `${productName} arrives soon. ${launchValue}`,
      releaseNotes: `### ${productName}\n- ${launchValue}\n- Includes launch-readiness checklist and owner actions`,
    };
  },
});

export const riskRegisterTool = tool({
  name: 'create_risk_register',
  description: 'Generate a risk register for the launch plan.',
  parameters: launchSchema,
  async execute(input: LaunchInput): Promise<RiskItem[]> {
    return [
      {
        risk: 'Critical dependency slips before launch',
        likelihood: 'Medium',
        impact: 'High',
        mitigation: 'Set checkpoint with dependency owners 72h before launch.',
        owner: 'Engineering',
      },
      {
        risk: `Message mismatch for audience segment: ${input.audience.slice(0, 40)}`,
        likelihood: 'Medium',
        impact: 'Medium',
        mitigation: 'Review copy with PM and support before distribution.',
        owner: 'Marketing',
      },
    ];
  },
});

export const launchTools = [
  extractTasksTool,
  launchReadinessTool,
  ownerChecklistTool,
  launchCopyTool,
  riskRegisterTool,
];
