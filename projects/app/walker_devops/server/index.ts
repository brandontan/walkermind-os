import 'dotenv/config';
import express from 'express';
import cors from 'cors';
import { setTracingDisabled } from '@openai/agents';
import { launchRouter } from './routes/launch.js';

const app = express();
const port = Number(process.env.PORT || 8787);

if (process.env.OPENAI_AGENTS_DISABLE_TRACING === '1') {
  setTracingDisabled(true);
}

app.use(cors());
app.use(express.json({ limit: '1mb' }));

app.get('/api/health', (_req, res) => {
  res.json({ ok: true, service: 'walker-devops-api' });
});

app.use('/api', launchRouter);

app.listen(port, () => {
  // eslint-disable-next-line no-console
  console.log(`Walker DevOps API listening on http://localhost:${port}`);
});
