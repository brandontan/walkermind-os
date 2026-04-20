import express from 'express';
import { run } from '@openai/agents';
import { z } from 'zod';
import { launchPlannerAgent } from '../../agent/launchPlannerAgent.js';

const bodySchema = z.object({
  productBrief: z.string().min(1),
  audience: z.string().min(1),
  launchDate: z.string().min(1),
  constraints: z.string().default(''),
  assets: z.string().default(''),
});

const formatPrompt = (input: z.infer<typeof bodySchema>) => `
Build a launch plan with this context:
- Product brief: ${input.productBrief}
- Audience: ${input.audience}
- Launch date: ${input.launchDate}
- Constraints: ${input.constraints}
- Available assets: ${input.assets}
`;

export const launchRouter = express.Router();

launchRouter.post('/launch-plan/stream', async (req, res) => {
  const parsed = bodySchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.flatten() });
    return;
  }

  if (!process.env.OPENAI_API_KEY) {
    res.status(500).json({ error: 'OPENAI_API_KEY is not configured on the server.' });
    return;
  }

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache, no-transform');
  res.setHeader('Connection', 'keep-alive');
  res.flushHeaders?.();

  const stream = await run(launchPlannerAgent, formatPrompt(parsed.data), { stream: true });

  for await (const event of stream) {
    if (event.type === 'raw_model_stream_event' && event.data.type === 'output_text_delta') {
      res.write(`data: ${JSON.stringify({ type: 'text_delta', delta: event.data.delta })}\n\n`);
    }

    if (event.type === 'run_item_stream_event' && event.name.includes('tool')) {
      res.write(
        `data: ${JSON.stringify({ type: 'tool_event', name: event.name, itemType: event.item.type })}\n\n`,
      );
    }
  }

  const output = await stream.finalOutput;
  res.write(`data: ${JSON.stringify({ type: 'final_output', text: output })}\n\n`);
  res.write('event: done\ndata: end\n\n');
  res.end();
});
