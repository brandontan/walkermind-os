export type LaunchFormInput = {
  productBrief: string;
  audience: string;
  launchDate: string;
  constraints: string;
  assets: string;
};

export type StreamEvent =
  | { type: 'text_delta'; delta: string }
  | { type: 'tool_event'; name: string; itemType: string }
  | { type: 'final_output'; text: string };
