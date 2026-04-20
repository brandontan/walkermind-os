export type LaunchInput = {
  productBrief: string;
  audience: string;
  launchDate: string;
  constraints: string;
  assets: string;
};

export type PlanTask = {
  title: string;
  owner: 'PM' | 'Engineering' | 'Marketing' | 'Design' | 'Legal' | 'Support';
  priority: 'P0' | 'P1' | 'P2';
  dueBy: string;
  rationale: string;
};

export type RiskItem = {
  risk: string;
  likelihood: 'Low' | 'Medium' | 'High';
  impact: 'Low' | 'Medium' | 'High';
  mitigation: string;
  owner: string;
};
